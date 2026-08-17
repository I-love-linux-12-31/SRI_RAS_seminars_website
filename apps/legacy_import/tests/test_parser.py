"""Разбор разметки старого сайта.

Фикстуры — настоящие страницы seminar.cosmos.ru, а не выдуманная разметка:
импорт делается один раз по живому сайту, и проверять его надо на том, что
там действительно лежит. Каждая фикстура закрывает свой случай, который на
сайте встретился.
"""

from datetime import date, time
from pathlib import Path

import pytest

from apps.legacy_import.parser import (
    ParseError,
    parse_archive_page,
    parse_seminar_page,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


def parse(name: str):
    return parse_seminar_page(load(name), f"https://seminar.cosmos.ru/seminar/{name}")


# --- обход архива ------------------------------------------------------------


def test_archive_page_gives_links_to_seminars():
    links = parse_archive_page(load("archive_page_0"))

    assert "/seminar/13052026-nestik-t" in links
    assert len(links) == len(set(links))


def test_empty_archive_page_ends_pagination():
    """Пустой список — единственный признак конца: у пейджера Drupal его нет."""
    assert parse_archive_page(load("archive_page_1")) == []


# --- дата и время ------------------------------------------------------------


def test_time_comes_from_text_when_attribute_is_utc():
    """У этого узла в атрибуте настоящий UTC: 09:00Z, а на сайте показано 12:00."""
    seminar = parse("seminar_13052026-nestik-t")

    assert seminar.date == date(2026, 5, 13)
    assert seminar.start_time == time(12, 0)


def test_time_comes_from_text_when_attribute_is_moscow():
    """А у этого в поле UTC лежит московское время с припиской «Z»: 15:00Z → 15:00.

    Два узла с одинаковым по смыслу временем и разными атрибутами — причина,
    по которой время берётся из текста, а не из `datetime`.
    """
    seminar = parse("seminar_1022023-ivanov-ba-dyachkova-mv")

    assert seminar.date == date(2023, 2, 1)
    assert seminar.start_time == time(15, 0)


def test_weekday_in_text_matches_the_date():
    """Сверка дня недели: если бы дату брали не из того часового пояса, она бы съехала."""
    assert parse("seminar_13052026-nestik-t").warnings == []


# --- доклады -----------------------------------------------------------------


def test_seminar_title_is_the_first_talk():
    seminar = parse("seminar_1022023-ivanov-ba-dyachkova-mv")

    assert len(seminar.talks) == 2
    assert seminar.title == seminar.talks[0].title
    assert seminar.title.startswith("Проблемы численного моделирования")


def test_stub_node_is_not_a_seminar():
    """Незаполненный узел: и тема, и докладчик стоят как «***»."""
    with pytest.raises(ParseError):
        parse("node_37")


# --- докладчики --------------------------------------------------------------


def test_bold_marks_the_name_and_the_rest_is_affiliation():
    speaker = parse("seminar_13052026-nestik-t").talks[0].speakers[0]

    assert speaker.full_name == "Нестик Тимофей Александрович"
    assert speaker.affiliation.startswith("профессор РАН, д. психол. н.")


def test_comma_inside_bold_does_not_stick_to_the_name():
    """«<strong>Мария Сергеевна Кирсанова, </strong>д.ф-м.н., …»"""
    speaker = parse("seminar_18022026-kirsanova-ms").talks[0].speakers[0]

    assert speaker.full_name == "Мария Сергеевна Кирсанова"
    assert speaker.affiliation == "д.ф-м.н., Институт астрономии РАН"


def test_two_speakers_are_split_by_line_break():
    speakers = parse("seminar_14012026-chernecov-n-s-kavokin-k-v").talks[0].speakers

    assert [s.full_name for s in speakers] == [
        "Никита Севирович Чернецов",
        "Кирилл Витальевич Кавокин",
    ]
    assert speakers[1].affiliation.startswith("д.ф.-м.н.")


def test_name_without_bold_is_cut_at_the_first_comma():
    speaker = parse("seminar_1022023-ivanov-ba-dyachkova-mv").talks[0].speakers[0]

    assert speaker.full_name == "Иванов Б.А."
    assert speaker.affiliation == "д.ф.-м.н., в.н.с., Институт динамики геосфер РАН"


def test_two_names_before_a_shared_affiliation():
    """«Томилина Т.М., Ким А.А, Институт машиноведения…» — двое, организация общая.

    Без разбора на «Фамилия И.О.» второй докладчик уехал бы в должность первого.
    """
    speakers = parse("seminar_28022024").talks[0].speakers

    assert [s.full_name for s in speakers] == ["Томилина Т.М.", "Ким А.А"]
    assert {s.affiliation for s in speakers} == {"Институт машиноведения им. А.А. Благонравова РАН"}


# --- материалы и прочие поля -------------------------------------------------


def test_annotation_link_is_collected():
    material = parse("seminar_13052026-nestik-t").talks[0].materials[0]

    assert material.label == "Аннотация"
    assert material.url.endswith(".pdf")
    assert material.filename.startswith("НестикТА")


def test_file_name_falls_back_to_the_address():
    """У этого узла нет атрибута title, а текстом ссылки стоит само имя файла."""
    material = parse("seminar_18022026-kirsanova-ms").talks[0].materials[0]

    assert material.label == "Аннотация"
    assert material.filename == "Происхождение и перенос воды во Вселенной.pdf"


def test_place_drops_the_directions_link():
    place = parse("seminar_13052026-nestik-t").place

    assert place.startswith("Институт Космических Исследований РАН, Москва")
    assert "проехать" not in place.lower()


def test_online_link_is_extracted_from_the_instructions():
    seminar = parse("seminar_13052026-nestik-t")

    assert seminar.online_url == "https://tconf.geosmis.ru/c/456987"
