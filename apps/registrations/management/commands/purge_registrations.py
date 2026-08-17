"""Удаление устаревших заявок.

Хранить персональные данные дольше, чем нужно для цели сбора, нельзя.
Цель — организация участия и оформление пропуска, поэтому через настраиваемый
срок после заседания заявки удаляются. Запускается systemd-таймером раз в сутки.
"""

import calendar
from datetime import date

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import SiteSettings
from apps.registrations.models import Registration


def months_ago(count: int) -> date:
    """Дата на N месяцев раньше сегодняшней.

    Ради одной функции тянуть dateutil незачем. Число месяца прижимается
    к последнему дню, если в целевом месяце его нет (31 марта → 28 февраля).
    """
    today = timezone.localdate()
    year, month = today.year, today.month - count
    while month <= 0:
        month += 12
        year -= 1
    day = min(today.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class Command(BaseCommand):
    help = "Удалить заявки на заседания, прошедшие более N месяцев назад."

    def add_arguments(self, parser):
        parser.add_argument(
            "--months", type=int, default=None, help="переопределить срок из настроек сайта"
        )
        parser.add_argument("--dry-run", action="store_true", help="показать, что было бы удалено")

    def handle(self, *args, **options):
        months = options["months"] or SiteSettings.load().retention_months
        cutoff = months_ago(months)

        stale = Registration.objects.filter(seminar__date__lt=cutoff)
        count = stale.count()

        if options["dry_run"]:
            self.stdout.write(f"Под удаление попадает заявок: {count} (заседания до {cutoff})")
            return

        stale.delete()
        self.stdout.write(self.style.SUCCESS(f"Удалено заявок: {count} (заседания до {cutoff})"))
