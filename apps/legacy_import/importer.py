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

from apps.seminars.models import Material, Seminar, Speaker, Talk, TalkSpeaker

from .client import FetchError
from .models import LegacySeminarLink
from .parser import LegacySeminar, LegacySpeaker


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


def _build_slug(seminar: Seminar, label: str) -> str:
    """Адрес заседания по общему для проекта правилу.

    Берём генератор из формы панели управления, чтобы правило жило в одном
    месте. `label` — тема первого доклада: доклады сохраняются уже после
    заседания, а адреса перенесённого архива должны остаться прежними.
    """
    from apps.staffpanel.forms import SeminarForm

    return SeminarForm._build_slug(seminar, label)


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


def _clash_on(date):
    """Заседание на ту же дату, заведённое не импортом.

    Двух заседаний в один день бояться больше нечего — на старом сайте так и
    было, и узел с двумя докладами как раз превращается в два заседания.
    А вот затирать заведённое руками или демонстрационное по-прежнему нельзя.
    """
    return Seminar.objects.filter(date=date, legacy_link__isnull=True).first()


@transaction.atomic
def import_seminar(
    parsed: LegacySeminar,
    *,
    source,
    status: str = Seminar.Status.PUBLISHED,
    download: bool = True,
    update: bool = False,
    adopt_by_date: bool = False,
    report: Report | None = None,
) -> list[Seminar]:
    """Перенести один узел старого сайта. Возвращает заведённые заседания.

    **Один доклад — одно заседание.** На старом сайте два доклада одного дня
    лежат в одном узле, но это были два заседания, а не одно с двумя докладами:
    отличить их по разметке нельзя, зато у заседания нет и собственной темы,
    так что делить по докладам — единственное последовательное правило.

    Каждый узел идёт своей транзакцией: сбой на одном не должен откатывать
    уже перенесённый архив.
    """
    report = report or Report()
    links = {
        link.talk_index: link
        for link in LegacySeminarLink.objects.filter(node_id=parsed.node_id).select_related(
            "seminar"
        )
    }
    if links and not update:
        report.skipped += 1
        return []

    done: list[Seminar] = []
    for index, parsed_talk in enumerate(parsed.talks):
        seminar = _import_one(
            parsed,
            parsed_talk,
            index,
            link=links.get(index),
            source=source,
            status=status,
            download=download,
            adopt_by_date=adopt_by_date,
            report=report,
        )
        if seminar is not None:
            done.append(seminar)

    for message in parsed.warnings:
        report.warn(parsed.url, message)
    if "пароль" in parsed.online_note.lower():
        # У заседания есть только ссылка на трансляцию, отдельного поля под
        # пароль нет. Для прошедших заседаний он бесполезен, а выкладывать
        # пароли от конференций в открытый архив и не следовало бы.
        report.warn(parsed.url, "пароль от трансляции не перенесён")
    return done


def _import_one(
    parsed: LegacySeminar,
    parsed_talk,
    index: int,
    *,
    link,
    source,
    status: str,
    download: bool,
    adopt_by_date: bool,
    report: Report,
) -> Seminar | None:
    """Одно заседание: один доклад узла со своими докладчиками и материалами."""
    if link is None:
        # Заседание на эту дату уже есть, но метки об импорте у него нет: либо
        # это демонстрационные данные seed_demo (они сняты с этого же сайта),
        # либо секретарь завёл заседание руками. Молча создавать второе нельзя
        # — в архиве появится двойник; молча переписывать чужое тоже нельзя.
        # Поэтому по умолчанию отказываемся и объясняем, а перезапись включается
        # отдельным ключом.
        clash = _clash_on(parsed.date)
        if clash is not None:
            if not adopt_by_date:
                report.skipped += 1
                report.warn(
                    parsed.url,
                    f"на {parsed.date:%d.%m.%Y} уже есть заседание «{clash.label[:40]}» "
                    f"({clash.slug}) — пропущено, чтобы не создать двойник; "
                    f"перезаписать: --adopt-by-date",
                )
                return None
            link = LegacySeminarLink(seminar=clash)

    seminar = link.seminar if link is not None else Seminar()
    seminar.date = parsed.date
    seminar.start_time = parsed.start_time
    seminar.place_ru = parsed.place[:300]
    seminar.online_url = parsed.online_url
    seminar.status = status
    seminar.seminar_format = (
        Seminar.Format.HYBRID
        if parsed.online_url or "онлайн" in parsed.place.lower()
        else Seminar.Format.ONSITE
    )
    if not seminar.slug:
        seminar.slug = _build_slug(seminar, parsed_talk.title)
    seminar.save()

    if link is not None:
        # Доклад пересобирается целиком: сверять его не с чем — у докладов на
        # старом сайте нет собственных идентификаторов.
        seminar.talks.all().delete()

    talk = Talk.objects.create(seminar=seminar, order=0, title_ru=parsed_talk.title[:500])
    report.talks += 1
    for position, parsed_speaker in enumerate(parsed_talk.speakers):
        TalkSpeaker.objects.create(
            talk=talk, speaker=_sync_speaker(parsed_speaker, report), order=position
        )
    for parsed_material in parsed_talk.materials:
        _attach_material(talk, parsed_material, source, download=download, report=report)

    LegacySeminarLink.objects.update_or_create(
        node_id=parsed.node_id,
        talk_index=index,
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
    return seminar
