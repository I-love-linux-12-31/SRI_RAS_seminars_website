"""Имена сохранённых страниц.

Снимок сайта и импорт из снимка — разные запуски команды, иногда на разных
машинах: так архив попадает в закрытый контур. Значит, имя файла должно
считаться одинаково с обеих сторон, а страницы архива — не сливаться в одну.
"""

from apps.legacy_import.client import DirectoryClient, page_filename

from .test_parser import FIXTURES


def test_seminar_page_keeps_its_address_in_the_name():
    assert page_filename("/seminar/13052026-nestik-t") == "seminar_13052026-nestik-t.html"


def test_archive_pages_do_not_collide():
    """Страницы архива различаются только строкой запроса.

    Если её отбросить, весь пейджер ляжет в один файл: последней запишется
    пустая страница, которой заканчивается обход, и снимок окажется пустым.
    """
    names = {page_filename(f"/archive?page={number}") for number in range(3)}

    assert len(names) == 3
    assert "archive_page_1.html" in names


def test_absolute_and_relative_addresses_give_the_same_name():
    assert page_filename("https://seminar.cosmos.ru/archive?page=1") == page_filename(
        "/archive?page=1"
    )


def test_directory_client_reads_what_the_snapshot_wrote():
    client = DirectoryClient(FIXTURES)

    assert "zasedanie-seminara" in client.archive_page(0)
    assert client.page("/seminar/13052026-nestik-t")
