"""Перенос разобранных заседаний в базу.

Проверяется главным образом повторный запуск: импорт задуман как команда,
которую гоняют не один раз, и второй прогон не должен ни удваивать архив,
ни затирать правки секретаря.
"""

import pytest
from django.core.management import call_command

from apps.legacy_import.importer import Report, ensure_topic, import_seminar
from apps.legacy_import.models import LegacySeminarLink
from apps.seminars.models import Material, Seminar, Speaker
from apps.seminars.tests.factories import make_seminar, make_topic

from .test_parser import FIXTURES, parse

pytestmark = pytest.mark.django_db


def run(name: str, **kwargs):
    """Импортировать одну фикстуру. Файлы не качаем — сети в тестах нет."""
    options = {"topic": ensure_topic("unsorted"), "source": _Source(), "download": False}
    return import_seminar(parse(name), **(options | kwargs))


class _Source:
    """Заглушка источника: нужна только для абсолютных ссылок на файлы."""

    base_url = "https://seminar.cosmos.ru"

    def file(self, path):  # pragma: no cover — при download=False не вызывается
        raise AssertionError("файлы качать не должны")


def test_import_creates_seminar_with_talks_and_speakers():
    seminar = run("seminar_1022023-ivanov-ba-dyachkova-mv")

    assert seminar.status == Seminar.Status.PUBLISHED
    assert seminar.talks.count() == 2
    assert seminar.title_ru == seminar.talks.first().title_ru
    assert Speaker.objects.filter(full_name_ru="Иванов Б.А.").exists()


def test_talk_order_is_preserved():
    seminar = run("seminar_1022023-ivanov-ba-dyachkova-mv")

    titles = [talk.title_ru for talk in seminar.talks.all()]
    assert titles[0].startswith("Проблемы численного моделирования")
    assert titles[1].startswith("Места посадки")


def test_speakers_keep_their_order_inside_a_talk():
    """Первый автор — не произвольный, порядок из старого сайта надо сохранить."""
    seminar = run("seminar_14012026-chernecov-n-s-kavokin-k-v")

    names = [s.full_name_ru for s in seminar.talks.first().ordered_speakers]
    assert names == ["Никита Севирович Чернецов", "Кирилл Витальевич Кавокин"]


def test_material_keeps_a_link_when_files_are_not_downloaded():
    seminar = run("seminar_13052026-nestik-t")
    material = Material.objects.get(seminar=seminar)

    assert material.kind == Material.Kind.ABSTRACT
    assert material.url.startswith("https://seminar.cosmos.ru/sites/default/files/")
    assert material.talk_id is not None


def test_second_run_skips_an_already_imported_node():
    first = run("seminar_13052026-nestik-t")
    again = run("seminar_13052026-nestik-t")

    assert again is None
    assert Seminar.objects.count() == 1
    assert LegacySeminarLink.objects.get().seminar_id == first.pk


def test_update_replaces_talks_without_creating_a_second_seminar():
    first = run("seminar_13052026-nestik-t")
    first.talks.create(title_ru="Лишний доклад, добавленный по ошибке", order=9)

    again = run("seminar_13052026-nestik-t", update=True)

    assert again.pk == first.pk
    assert Seminar.objects.count() == 1
    assert again.talks.count() == 1


def test_update_keeps_the_address_so_links_do_not_break():
    first = run("seminar_13052026-nestik-t")

    assert run("seminar_13052026-nestik-t", update=True).slug == first.slug


def test_repeated_speaker_is_reused_not_duplicated():
    run("seminar_13052026-nestik-t")
    run("seminar_18022026-kirsanova-ms")
    run("seminar_13052026-nestik-t", update=True)

    assert Speaker.objects.filter(full_name_ru="Нестик Тимофей Александрович").count() == 1


def test_seminar_with_a_broadcast_link_is_hybrid():
    seminar = run("seminar_13052026-nestik-t")

    assert seminar.seminar_format == Seminar.Format.HYBRID
    assert seminar.online_url == "https://tconf.geosmis.ru/c/456987"


def test_broadcast_password_is_reported_as_dropped():
    """Поля под пароль нет; молча терять его нельзя — он должен попасть в отчёт."""
    report = Report()
    run("seminar_13052026-nestik-t", report=report)

    assert any("пароль" in warning for warning in report.warnings)


def test_imported_seminars_land_in_the_catch_all_topic():
    """На старом сайте тематики нет — заседания должны быть видны как неразобранные."""
    seminar = run("seminar_13052026-nestik-t")

    assert seminar.topic.slug == "unsorted"


def test_import_fills_search_text_so_archive_search_finds_it():
    seminar = run("seminar_13052026-nestik-t")
    seminar.refresh_from_db()

    assert "Нестик" in seminar.search_text


# --- столкновение с уже заведёнными заседаниями ------------------------------
#
# Быстрый старт из README советует залить демонстрационные данные `seed_demo`,
# а сняты они с этого же сайта. Значит, к моменту импорта половина заседаний
# в базе уже есть — и это тот случай, когда импорт обязан не навредить.


def test_seminar_already_in_the_database_is_not_duplicated():
    parsed = parse("seminar_13052026-nestik-t")
    make_seminar(parsed.date, title_ru="Заведено руками")

    assert run("seminar_13052026-nestik-t") is None
    assert Seminar.objects.count() == 1


def test_collision_is_explained_in_the_report():
    parsed = parse("seminar_13052026-nestik-t")
    make_seminar(parsed.date, title_ru="Заведено руками")
    report = Report()

    run("seminar_13052026-nestik-t", report=report)

    assert any("--adopt-by-date" in warning for warning in report.warnings)


def test_adopt_by_date_overwrites_the_existing_seminar():
    parsed = parse("seminar_13052026-nestik-t")
    existing = make_seminar(parsed.date, title_ru="Демонстрационное заседание")

    seminar = run("seminar_13052026-nestik-t", adopt_by_date=True)

    assert seminar.pk == existing.pk
    assert Seminar.objects.count() == 1
    assert seminar.title_ru.startswith("Интерес к космическим исследованиям")


def test_adopted_seminar_keeps_its_topic_and_address():
    """У демонстрационных данных тематика проставлена — терять её незачем."""
    parsed = parse("seminar_13052026-nestik-t")
    topic = make_topic(slug="society")
    existing = make_seminar(parsed.date, topic=topic, title_ru="Демонстрационное заседание")

    seminar = run("seminar_13052026-nestik-t", adopt_by_date=True)

    assert seminar.topic_id == topic.pk
    assert seminar.slug == existing.slug


# --- команда -----------------------------------------------------------------


def test_command_imports_the_whole_archive_from_a_directory(capsys):
    call_command("import_legacy", "--from-dir", str(FIXTURES), "--no-files")

    assert Seminar.objects.count() == 3  # четвёртая карточка в архиве — заготовка «***»
    assert LegacySeminarLink.objects.count() == 3


def test_command_is_safe_to_run_twice():
    call_command("import_legacy", "--from-dir", str(FIXTURES), "--no-files")
    call_command("import_legacy", "--from-dir", str(FIXTURES), "--no-files")

    assert Seminar.objects.count() == 3


def test_dry_run_changes_nothing():
    call_command("import_legacy", "--from-dir", str(FIXTURES), "--no-files", "--dry-run")

    assert Seminar.objects.count() == 0


def test_command_can_import_as_drafts():
    call_command("import_legacy", "--from-dir", str(FIXTURES), "--no-files", "--status", "draft")

    assert Seminar.objects.filter(status=Seminar.Status.DRAFT).count() == 3
    assert Seminar.objects.published().count() == 0
