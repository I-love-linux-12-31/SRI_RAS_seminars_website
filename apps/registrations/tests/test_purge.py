"""Проверки срока хранения персональных данных."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.core.models import SiteSettings
from apps.registrations.models import Registration
from apps.seminars.tests.factories import make_seminar

pytestmark = pytest.mark.django_db


def make_registration(seminar, email="a@example.org") -> Registration:
    return Registration.objects.create(
        seminar=seminar,
        full_name="Иванов Иван Иванович",
        organization="МГУ",
        email=email,
        consent_pd=True,
        consent_at=timezone.now(),
    )


def test_old_registrations_are_deleted():
    old = make_seminar(timezone.localdate() - timedelta(days=400), suffix="old")
    make_registration(old)

    call_command("purge_registrations", months=6)

    assert Registration.objects.count() == 0


def test_recent_registrations_survive():
    recent = make_seminar(timezone.localdate() - timedelta(days=10), suffix="new")
    make_registration(recent)

    call_command("purge_registrations", months=6)

    assert Registration.objects.count() == 1


def test_seminar_itself_is_kept():
    """Удаляются персональные данные, а не архив: заседание должно остаться."""
    from apps.seminars.models import Seminar

    old = make_seminar(timezone.localdate() - timedelta(days=400), suffix="old")
    make_registration(old)

    call_command("purge_registrations", months=6)

    assert Seminar.objects.filter(pk=old.pk).exists()


def test_retention_period_comes_from_site_settings():
    site = SiteSettings.load()
    site.retention_months = 1
    site.save()

    seminar = make_seminar(timezone.localdate() - timedelta(days=70), suffix="mid")
    make_registration(seminar)

    call_command("purge_registrations")

    assert Registration.objects.count() == 0


def test_dry_run_deletes_nothing():
    old = make_seminar(timezone.localdate() - timedelta(days=400), suffix="old")
    make_registration(old)

    call_command("purge_registrations", months=6, dry_run=True)

    assert Registration.objects.count() == 1
