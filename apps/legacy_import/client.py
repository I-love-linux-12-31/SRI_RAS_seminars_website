"""Доступ к страницам и файлам старого сайта.

Два источника за одним интерфейсом: живой сайт по HTTP и каталог со скачанными
страницами. Второй нужен не только для тестов — импорт в закрытый контур делают
на машине, у которой доступа к seminar.cosmos.ru нет вовсе: страницы сначала
выкачивают снаружи (`--save-dir`), переносят и импортируют (`--from-dir`).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

DEFAULT_BASE_URL = "https://seminar.cosmos.ru"
USER_AGENT = "iki-seminar-import/1.0 (+https://seminar.cosmos.ru)"


class FetchError(Exception):
    pass


def page_filename(url: str) -> str:
    """Имя файла для сохранённой страницы.

        /seminar/13052026-nestik-t → seminar_13052026-nestik-t.html
        /archive?page=1            → archive_page_1.html

    Строку запроса обязательно учитывать: страницы архива различаются только
    ею, и без неё весь пейджер лёг бы в один файл, затирая сам себя.
    """
    parts = urlsplit(unquote(url))
    name = "_".join(filter(None, [parts.path.strip("/"), parts.query]))
    return (re.sub(r"[/?&=]+", "_", name).strip("_") or "index") + ".html"


class LegacyClient:
    """Сайт по HTTP. Вежливо: один поток и пауза между запросами."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, delay: float = 0.5, timeout: float = 30.0):
        try:
            import httpx
        except ModuleNotFoundError as exc:  # pragma: no cover — зависит от окружения
            raise RuntimeError(
                "Не установлены зависимости импорта. Поставьте их: uv sync --group legacy-import"
            ) from exc
        self.base_url = base_url.rstrip("/")
        self.delay = delay
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )
        self._last_request = 0.0
        self.save_dir: Path | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._client.close()

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()

    def _get(self, url: str):
        import httpx

        self._wait()
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise FetchError(f"{url}: {exc}") from exc
        return response

    def page(self, path: str) -> str:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        text = self._get(url).text
        if self.save_dir is not None:
            target = self.save_dir / page_filename(url)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return text

    def archive_page(self, number: int) -> str:
        return self.page(f"/archive?page={number}")

    def file(self, path: str) -> bytes:
        return self._get(urljoin(self.base_url + "/", path.lstrip("/"))).content


class DirectoryClient:
    """Страницы из каталога. Файлы аннотаций отдаёт, только если они рядом.

    Имена файлов те же, что кладёт `LegacyClient.save_dir`, так что каталог,
    снятый одним запуском, читается другим без переименований.
    """

    def __init__(self, directory: Path, base_url: str = DEFAULT_BASE_URL):
        self.directory = Path(directory)
        self.base_url = base_url.rstrip("/")
        if not self.directory.is_dir():
            raise FetchError(f"каталог {self.directory} не найден")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def page(self, path: str) -> str:
        candidate = self.directory / page_filename(path)
        if not candidate.exists():
            raise FetchError(f"нет файла {candidate}")
        return candidate.read_text(encoding="utf-8")

    def archive_page(self, number: int) -> str:
        # Первая страница у Drupal доступна и без `?page=0`, поэтому каталог,
        # собранный руками, может содержать просто archive.html.
        names = [page_filename(f"/archive?page={number}")]
        if number == 0:
            names.append("archive.html")
        for name in names:
            candidate = self.directory / name
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        raise FetchError(f"нет страницы архива №{number} в {self.directory}")

    def file(self, path: str) -> bytes:
        candidate = self.directory / "files" / unquote(path).lstrip("/").rsplit("/", 1)[-1]
        if not candidate.exists():
            raise FetchError(f"нет файла {candidate}")
        return candidate.read_bytes()
