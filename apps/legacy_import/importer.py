"""Перенос разобранных заседаний в базу.

Разбор разметки лежит в `parser`, доступ к сайту — в `client`, здесь только
отображение на модели. Граница нужна ради тестов: импорт проверяется на
сохранённых страницах, без сети.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import unquote

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.text import get_valid_filename

from apps.seminars.models import Material, Seminar, Speaker, Talk, TalkSpeaker, Topic

from .client import FetchError
from .models import LegacySeminarLink
from .parser import LegacySeminar, LegacySpeaker

# На старом сайте тематики нет вовсе: рубрики появились только в новом макете.
# Поэтому импорт складывает всё в одну рубрику-накопитель, а секретарь потом
# разбирает архив по темам руками. Ставить рубрику наугад по ключевым словам
# было бы хуже: неверная рубрика в фильтре архива незаметна, а пустая — видна.
UNSORTED_TOPIC = {
    "slug": "unsorted",
    "name_ru": "Без тематики",
    "name_en": "Uncategorised",
    "short_ru": "Без тематики",
    "short_en": "Uncategorised",
    "order": 99,
}


@dataclass
class Report:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    talks: int = 0
    speakers_created: int = 0
    materials: int = 0
    files_downloaded: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, url: str, message: str) -> None:
        self.warnings.append(f"{url}: {message}")

    def as_lines(self) -> list[str]:
        return [
            f"создано заседаний:     {self.created}",
            f"обновлено:             {self.updated}",
            f"пропущено (уже есть):  {self.skipped}",
            f"не удалось:            {self.failed}",
            f"докладов:              {self.talks}",
            f"новых докладчиков:     {self.speakers_created}",
            f"материалов:            {self.materials} (скачано файлов: {self.files_downloaded})",
        ]


def ensure_topic(slug: str) -> Topic:
    """Рубрика для импортированных заседаний."""
    if slug == UNSORTED_TOPIC["slug"]:
        topic, _ = Topic.objects.get_or_create(
            slug=slug, defaults={k: v for k, v in UNSORTED_TOPIC.items() if k != "slug"}
        )
        return topic
    try:
        return Topic.objects.get(slug=slug)
    except Topic.DoesNotExist as exc:
        raise ValueError(f"тематика «{slug}» не заведена") from exc


def _build_slug(seminar: Seminar) -> str:
    """Адрес заседания по общему для проекта правилу.

    Берём генератор из формы панели управления, чтобы импортированные и
    заведённые руками заседания получали адреса по одному правилу и чтобы
    правило жило в одном месте.
    """
    from apps.staffpanel.forms import SeminarForm

    return SeminarForm._build_slug(seminar)


def _sync_speaker(parsed: LegacySpeaker, report: Report) -> Speaker:
    """Найти докладчика по ФИО или завести нового.

    Совпадение по ФИО — то же правило, по которому докладчиков вводит
    секретарь в панели: люди выступают повторно, и плодить карточки не нужно.
    """
    speaker = Speaker.objects.filter(full_name_ru=parsed.full_name).first()
    if speaker is None:
        report.speakers_created += 1
        return Speaker.objects.create(
            full_name_ru=parsed.full_name, affiliation_ru=parsed.affiliation
        )
    if not speaker.affiliation_ru and parsed.affiliation:
        speaker.affiliation_ru = parsed.affiliation
        speaker.save(update_fields=["affiliation_ru"])
    return speaker


def _attach_material(talk: Talk, parsed, source, *, download: bool, report: Report) -> None:
    material = Material(
        seminar=talk.seminar,
        talk=talk,
        kind=Material.Kind.ABSTRACT,
        title_ru=parsed.label,
    )
    absolute = parsed.url
    if absolute.startswith("/"):
        absolute = f"{source.base_url}{absolute}"

    if download:
        try:
            content = source.file(parsed.url)
        except FetchError as exc:
            # Файл не забрали — ссылка всё равно остаётся рабочей, пока жив
            # старый сайт. Терять из-за этого заседание целиком незачем.
            report.warn(talk.seminar.slug, f"не скачан файл {parsed.filename}: {exc}")
            material.url = absolute
        else:
            name = get_valid_filename(parsed.filename or unquote(parsed.url.rsplit("/", 1)[-1]))
            material.file.save(name, ContentFile(content), save=False)
            report.files_downloaded += 1
    else:
        material.url = absolute

    material.save()
    report.materials += 1


@transaction.atomic
def import_seminar(
    parsed: LegacySeminar,
    *,
    topic: Topic,
    source,
    status: str = Seminar.Status.PUBLISHED,
    download: bool = True,
    update: bool = False,
    adopt_by_date: bool = False,
    report: Report | None = None,
) -> Seminar | None:
    """Перенести одно заседание. Возвращает None, если переносить не стали.

    Каждое заседание идёт своей транзакцией: сбой на одном узле не должен
    откатывать уже перенесённый архив.
    """
    report = report or Report()
    link = (
        LegacySeminarLink.objects.filter(node_id=parsed.node_id).select_related("seminar").first()
    )
    if link is not None and not update:
        report.skipped += 1
        return None

    if link is None:
        # Заседание на эту дату уже есть, но метки об импорте у него нет: либо
        # это демонстрационные данные seed_demo (они сняты с этого же сайта),
        # либо секретарь завёл заседание руками. Молча создавать второе нельзя
        # — в архиве появится двойник; молча переписывать чужое тоже нельзя.
        # Поэтому по умолчанию отказываемся и объясняем, а перезапись включается
        # отдельным ключом.
        clash = Seminar.objects.filter(date=parsed.date).first()
        if clash is not None:
            if not adopt_by_date:
                report.skipped += 1
                report.warn(
                    parsed.url,
                    f"на {parsed.date:%d.%m.%Y} уже есть заседание «{clash.title_ru[:40]}» "
                    f"({clash.slug}) — пропущено, чтобы не создать двойник; "
                    f"перезаписать: --adopt-by-date",
                )
                return None
            link = LegacySeminarLink(seminar=clash)

    seminar = link.seminar if link is not None else Seminar()
    seminar.date = parsed.date
    seminar.start_time = parsed.start_time
    seminar.title_ru = parsed.title[:500]
    seminar.place_ru = parsed.place[:300]
    seminar.online_url = parsed.online_url
    seminar.status = status
    if not seminar.topic_id:
        seminar.topic = topic
    seminar.seminar_format = (
        Seminar.Format.HYBRID
        if parsed.online_url or "онлайн" in parsed.place.lower()
        else Seminar.Format.ONSITE
    )
    if not seminar.slug:
        seminar.slug = _build_slug(seminar)
    seminar.save()

    if link is not None:
        # Доклады пересобираются целиком: сверять их по одному не с чем —
        # у докладов на старом сайте нет собственных идентификаторов.
        seminar.materials.all().delete()
        seminar.talks.all().delete()

    for order, parsed_talk in enumerate(parsed.talks):
        talk = Talk.objects.create(
            seminar=seminar,
            order=order,
            title_ru=parsed_talk.title[:500],
        )
        report.talks += 1
        for position, parsed_speaker in enumerate(parsed_talk.speakers):
            TalkSpeaker.objects.create(
                talk=talk, speaker=_sync_speaker(parsed_speaker, report), order=position
            )
        for parsed_material in parsed_talk.materials:
            _attach_material(talk, parsed_material, source, download=download, report=report)

    LegacySeminarLink.objects.update_or_create(
        node_id=parsed.node_id,
        defaults={
            "seminar": seminar,
            "legacy_slug": parsed.slug,
            "legacy_url": parsed.url,
        },
    )

    if link is None:
        report.created += 1
    else:
        report.updated += 1
    for message in parsed.warnings:
        report.warn(parsed.url, message)
    if "пароль" in parsed.online_note.lower():
        # У заседания есть только ссылка на трансляцию, отдельного поля под
        # пароль нет. Для прошедших заседаний он бесполезен, а выкладывать
        # пароли от конференций в открытый архив и не следовало бы.
        report.warn(parsed.url, "пароль от трансляции не перенесён")
    return seminar
