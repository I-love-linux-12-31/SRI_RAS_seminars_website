"""Импорт архива заседаний со старого сайта seminar.cosmos.ru.

    uv run manage.py import_legacy --dry-run     посмотреть, что приедет
    uv run manage.py import_legacy               перенести
    uv run manage.py import_legacy --update      перенести заново поверх

Команда идемпотентна: уже импортированные узлы пропускаются, так что её можно
запускать повторно, когда на старом сайте появилось новое заседание.
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.legacy_import.client import DEFAULT_BASE_URL, DirectoryClient, FetchError, LegacyClient
from apps.legacy_import.importer import UNSORTED_TOPIC, Report, ensure_topic, import_seminar
from apps.legacy_import.parser import ParseError, parse_archive_page, parse_seminar_page
from apps.seminars.models import Seminar

MAX_ARCHIVE_PAGES = 50


class Command(BaseCommand):
    help = "Импортировать архив заседаний со старого сайта"

    def add_arguments(self, parser):
        parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="адрес старого сайта")
        parser.add_argument(
            "--from-dir",
            type=Path,
            help="читать сохранённые страницы из каталога вместо обращения к сайту",
        )
        parser.add_argument("--save-dir", type=Path, help="сохранить скачанные страницы в каталог")
        parser.add_argument("--limit", type=int, help="взять не больше N заседаний")
        parser.add_argument(
            "--dry-run", action="store_true", help="разобрать и показать, но не сохранять"
        )
        parser.add_argument(
            "--update", action="store_true", help="перезаписать уже импортированные заседания"
        )
        parser.add_argument(
            "--no-files",
            action="store_true",
            help="не скачивать PDF с аннотациями, оставить ссылки на старый сайт",
        )
        parser.add_argument(
            "--adopt-by-date",
            action="store_true",
            help=(
                "переписать заседания, уже заведённые на ту же дату "
                "(демонстрационные данные seed_demo)"
            ),
        )
        parser.add_argument(
            "--topic",
            default=UNSORTED_TOPIC["slug"],
            help="код тематики для импортированных заседаний",
        )
        parser.add_argument(
            "--status",
            default=Seminar.Status.PUBLISHED,
            choices=[value for value, _ in Seminar.Status.choices],
            help="статус публикации импортированных заседаний",
        )

    def handle(self, **options):
        if options["from_dir"] and options["save_dir"]:
            raise CommandError("--from-dir и --save-dir несовместимы")

        try:
            topic = ensure_topic(options["topic"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        source = self._open_source(options)
        report = Report()
        with source:
            links = self._collect_links(source, report)
            if options["limit"]:
                links = links[: options["limit"]]
            self.stdout.write(f"нашлось заседаний: {len(links)}")

            for href in links:
                self._handle_one(href, source, topic, report, options)

        self._print_report(report, dry_run=options["dry_run"])

    # --- источники -----------------------------------------------------------

    def _open_source(self, options):
        if options["from_dir"]:
            try:
                return DirectoryClient(options["from_dir"], base_url=options["base_url"])
            except FetchError as exc:
                raise CommandError(str(exc)) from exc
        client = LegacyClient(base_url=options["base_url"])
        if options["save_dir"]:
            client.save_dir = Path(options["save_dir"])
        return client

    def _collect_links(self, source, report: Report) -> list[str]:
        """Обойти пагинацию архива до первой пустой страницы."""
        links: list[str] = []
        for number in range(MAX_ARCHIVE_PAGES):
            try:
                html = source.archive_page(number)
            except FetchError as exc:
                if number == 0:
                    raise CommandError(f"не открыть архив: {exc}") from exc
                break
            found = parse_archive_page(html)
            if not found:
                break
            links.extend(href for href in found if href not in links)
        else:
            report.warn("archive", f"остановились на {MAX_ARCHIVE_PAGES} странице архива")
        return links

    # --- перенос -------------------------------------------------------------

    def _handle_one(self, href: str, source, topic, report: Report, options) -> None:
        url = href if href.startswith("http") else f"{options['base_url']}{href}"
        try:
            html = source.page(href)
        except FetchError as exc:
            report.failed += 1
            report.warn(url, f"страница не открылась: {exc}")
            return

        try:
            parsed = parse_seminar_page(html, url)
        except ParseError as exc:
            # Заготовки со звёздочками вместо темы — это не сбой, а нормальное
            # состояние ещё не заполненного узла на старом сайте.
            report.skipped += 1
            self.stdout.write(f"  пропуск {href}: {exc}")
            return

        if options["dry_run"]:
            self._preview(parsed)
            report.created += 1
            report.talks += len(parsed.talks)
            report.materials += sum(len(t.materials) for t in parsed.talks)
            for message in parsed.warnings:
                report.warn(url, message)
            return

        try:
            with transaction.atomic():
                seminar = import_seminar(
                    parsed,
                    topic=topic,
                    source=source,
                    status=options["status"],
                    download=not options["no_files"],
                    update=options["update"],
                    adopt_by_date=options["adopt_by_date"],
                    report=report,
                )
        except Exception as exc:  # один плохой узел не должен ронять весь импорт
            report.failed += 1
            report.warn(url, f"не перенесено: {exc}")
            return

        if seminar is None:
            self.stdout.write(f"  уже импортировано: {href}")
        else:
            self.stdout.write(f"  {parsed.date:%d.%m.%Y} {seminar.slug}")

    def _preview(self, parsed) -> None:
        self.stdout.write(f"  {parsed.date:%d.%m.%Y} {parsed.start_time:%H:%M} — {parsed.title}")
        for talk in parsed.talks:
            who = ", ".join(s.full_name for s in talk.speakers)
            self.stdout.write(f"      {talk.title[:70]} — {who}")

    def _print_report(self, report: Report, *, dry_run: bool) -> None:
        self.stdout.write("")
        for line in report.as_lines():
            self.stdout.write(line)
        if report.warnings:
            self.stdout.write(self.style.WARNING(f"\nпредупреждений: {len(report.warnings)}"))
            for warning in report.warnings:
                self.stdout.write(f"  {warning}")
        if dry_run:
            self.stdout.write(self.style.NOTICE("\nэто был --dry-run, ничего не сохранено"))
        else:
            self.stdout.write(self.style.SUCCESS("\nимпорт завершён"))
