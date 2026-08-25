"""Перенос разобранных заседаний в базу.

Проверяется главным образом повторный запуск: импорт задуман как команда,
которую гоняют не один раз, и второй прогон не должен ни удваивать архив,
ни затирать правки секретаря. Второй сюжет — разбиение: узел старого сайта
с двумя докладами это два заседания, а не одно.
"""

import pytest
from django.core.management import call_command

from apps.legacy_import.importer import Report, import_seminar
from apps.legacy_import.models import LegacySeminarLink
from apps.seminars.models import Material, Seminar, Speaker
from apps.seminars.tests.factories import add_talk, make_seminar

from .test_parser import FIXTURES, parse

pytestmark = pytest.mark.django_db


def run(name: str, **kwargs) -> list[Seminar]:
    """Импортировать одну фикстуру. Файлы не качаем — сети в тестах нет."""
    options = {"source": _Source(), "download": False}
    return import_seminar(parse(name), **(options | kwargs))


def run_one(name: str, **kwargs) -> Seminar:
    """Фикстура с одним докладом: одно заседание."""
    created = run(name, **kwargs)
    assert len(created) == 1, f"ожидалось одно заседание, получено {len(created)}"
    return created[0]


class _Source:
    """Заглушка источника: нужна только для абсолютных ссылок на файлы."""

    base_url = "https://seminar.cosmos.ru"

    def file(self, path):  # pragma: no cover — при download=False не вызывается
        raise AssertionError("файлы качать не должны")


def test_import_creates_seminar_with_talk_and_speakers():
    seminar = run_one("seminar_13052026-nestik-t")

    assert seminar.status == Seminar.Status.PUBLISHED
    assert seminar.talks.count() == 1
    assert Speaker.objects.filter(full_name_ru="Нестик Тимофей Александрович").exists()


def test_node_with_two_talks_becomes_two_seminars():
    """Два доклада в один день — это два заседания, а не одно с двумя докладами.

    На старом сайте они лежат в одном узле, но отличить «одно заседание с
    двумя докладами» от «двух заседаний» по разметке нельзя, а собственной
    темы у заседания нет — значит, делим по докладам.
    """
    created = run("seminar_1022023-ivanov-ba-dyachkova-mv")

    assert len(created) == 2
    assert {s.date for s in created} == {parse("seminar_1022023-ivanov-ba-dyachkova-mv").date}
    assert [s.talks.count() for s in created] == [1, 1]
    titles = [s.talks.get().title_ru for s in created]
    assert titles[0].startswith("Проблемы численного моделирования")
    assert titles[1].startswith("Места посадки")


def test_split_seminars_get_their_own_addresses():
    created = run("seminar_1022023-ivanov-ba-dyachkova-mv")

    slugs = [s.slug for s in created]
    assert len(set(slugs)) == 2, "у двух заседаний одного дня адреса должны различаться"
    assert all(s.startswith("2023-02-01") for s in slugs)
    assert "problemy" in slugs[0], "адрес собирается из темы доклада в транслитерации"


def test_split_keeps_each_speaker_with_their_own_talk():
    created = run("seminar_1022023-ivanov-ba-dyachkova-mv")

    names = [[sp.full_name_ru for sp in s.talks.get().ordered_speakers] for s in created]
    assert names == [["Иванов Б.А."], ["Дьячкова М.В."]]


def test_speakers_keep_their_order_inside_a_talk():
    """Первый автор — не произвольный, порядок из старого сайта надо сохранить."""
    seminar = run_one("seminar_14012026-chernecov-n-s-kavokin-k-v")

    names = [s.full_name_ru for s in seminar.talks.first().ordered_speakers]
    assert names == ["Никита Севирович Чернецов", "Кирилл Витальевич Кавокин"]


def test_material_keeps_a_link_when_files_are_not_downloaded():
    seminar = run_one("seminar_13052026-nestik-t")
    material = Material.objects.get(talk__seminar=seminar)

    assert material.kind == Material.Kind.ABSTRACT
    assert material.url.startswith("https://seminar.cosmos.ru/sites/default/files/")
    assert material.talk_id == seminar.talks.get().pk


def test_second_run_skips_an_already_imported_node():
    first = run_one("seminar_13052026-nestik-t")
    again = run("seminar_13052026-nestik-t")

    assert again == []
    assert Seminar.objects.count() == 1
    assert LegacySeminarLink.objects.get().seminar_id == first.pk


def test_update_replaces_the_talk_without_creating_a_second_seminar():
    first = run_one("seminar_13052026-nestik-t")
    first.talks.create(title_ru="Лишний доклад, добавленный по ошибке", order=9)

    again = run_one("seminar_13052026-nestik-t", update=True)

    assert again.pk == first.pk
    assert Seminar.objects.count() == 1
    assert again.talks.count() == 1


def test_update_does_not_multiply_split_seminars():
    """Повторный прогон по узлу с двумя докладами не должен плодить заседания."""
    first = run("seminar_1022023-ivanov-ba-dyachkova-mv")

    again = run("seminar_1022023-ivanov-ba-dyachkova-mv", update=True)

    assert [s.pk for s in again] == [s.pk for s in first]
    assert Seminar.objects.count() == 2
    assert LegacySeminarLink.objects.count() == 2


def test_update_keeps_the_address_so_links_do_not_break():
    first = run_one("seminar_13052026-nestik-t")

    assert run_one("seminar_13052026-nestik-t", update=True).slug == first.slug


def test_repeated_speaker_is_reused_not_duplicated():
    run("seminar_13052026-nestik-t")
    run("seminar_18022026-kirsanova-ms")
    run("seminar_13052026-nestik-t", update=True)

    assert Speaker.objects.filter(full_name_ru="Нестик Тимофей Александрович").count() == 1


def test_seminar_with_a_broadcast_link_is_hybrid():
    seminar = run_one("seminar_13052026-nestik-t")

    assert seminar.seminar_format == Seminar.Format.HYBRID
    assert seminar.online_url == "https://tconf.geosmis.ru/c/456987"


def test_broadcast_password_is_reported_as_dropped():
    """Поля под пароль нет; молча терять его нельзя — он должен попасть в отчёт."""
    report = Report()
    run("seminar_13052026-nestik-t", report=report)

    assert any("пароль" in warning for warning in report.warnings)


def test_import_fills_search_text_so_archive_search_finds_it():
    seminar = run_one("seminar_13052026-nestik-t")
    seminar.refresh_from_db()

    assert "Нестик" in seminar.search_text


# --- столкновение с уже заведёнными заседаниями ------------------------------
#
# Быстрый старт из README советует залить демонстрационные данные `seed_demo`,
# а сняты они с этого же сайта. Значит, к моменту импорта половина заседаний
# в базе уже есть — и это тот случай, когда импорт обязан не навредить.


def test_seminar_already_in_the_database_is_not_duplicated():
    parsed = parse("seminar_13052026-nestik-t")
    make_seminar(parsed.date)

    assert run("seminar_13052026-nestik-t") == []
    assert Seminar.objects.count() == 1


def test_collision_is_explained_in_the_report():
    parsed = parse("seminar_13052026-nestik-t")
    add_talk(make_seminar(parsed.date), "Заведено руками", [("Иванов И. И.", "ИКИ РАН")])
    report = Report()

    run("seminar_13052026-nestik-t", report=report)

    assert any("--adopt-by-date" in warning for warning in report.warnings)


def test_adopt_by_date_overwrites_the_existing_seminar():
    parsed = parse("seminar_13052026-nestik-t")
    existing = make_seminar(parsed.date)
    add_talk(existing, "Демонстрационный доклад", [("Иванов И. И.", "ИКИ РАН")])

    seminar = run_one("seminar_13052026-nestik-t", adopt_by_date=True)

    assert seminar.pk == existing.pk
    assert Seminar.objects.count() == 1
    assert seminar.lead_talk.title_ru.startswith("Интерес к космическим исследованиям")


def test_adopted_seminar_keeps_its_address():
    """Адрес заведённого заседания менять нельзя — по нему уже ходят ссылки."""
    parsed = parse("seminar_13052026-nestik-t")
    existing = make_seminar(parsed.date)

    seminar = run_one("seminar_13052026-nestik-t", adopt_by_date=True)

    assert seminar.slug == existing.slug


# --- команда -----------------------------------------------------------------


def test_command_imports_the_whole_archive_from_a_directory(capsys):
    call_command("import_legacy", "--from-dir", str(FIXTURES), "--no-files")

    # В архиве-фикстуре четыре карточки, четвёртая — заготовка «***».
    # У всех трёх узлов по одному докладу, значит и заседаний три.
    assert Seminar.objects.count() == 3
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
