"""Проверки вычисляемого состояния заседания.

Главное здесь — что «прошло / не прошло» и «регистрация открыта» считаются
от даты, а не хранятся флагом. Ни один тест не запускает фоновых задач.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.seminars.models import Seminar

from .factories import add_talk, make_seminar

pytestmark = pytest.mark.django_db


def test_seminar_today_is_still_upcoming():
    """Заседание считается предстоящим весь свой день, а не до полуночи накануне."""
    today = make_seminar(timezone.localdate())

    assert today in Seminar.objects.upcoming()
    assert today not in Seminar.objects.archive()
    assert today.is_past is False


def test_yesterday_moves_to_archive_without_any_job():
    yesterday = make_seminar(timezone.localdate() - timedelta(days=1))

    assert yesterday in Seminar.objects.archive()
    assert yesterday not in Seminar.objects.upcoming()
    assert yesterday.is_archived is True


def test_draft_and_hidden_are_not_public():
    make_seminar(timezone.localdate(), suffix="d", status=Seminar.Status.DRAFT)
    make_seminar(timezone.localdate(), suffix="h", status=Seminar.Status.HIDDEN)

    assert Seminar.objects.published().count() == 0
    assert Seminar.objects.upcoming().count() == 0


def test_archive_excludes_unpublished_past():
    """Скрытое прошедшее заседание не должно всплыть в архиве."""
    make_seminar(timezone.localdate() - timedelta(days=5), status=Seminar.Status.HIDDEN, suffix="h")

    assert Seminar.objects.archive().count() == 0


def test_registration_closes_by_explicit_deadline():
    seminar = make_seminar(
        timezone.localdate() + timedelta(days=10),
        registration_closes_at=timezone.now() - timedelta(minutes=1),
    )

    assert seminar.registration_open is False


def test_registration_open_before_deadline():
    seminar = make_seminar(
        timezone.localdate() + timedelta(days=10),
        registration_closes_at=timezone.now() + timedelta(days=1),
    )

    assert seminar.registration_open is True


def test_deadline_falls_back_to_site_setting():
    """Без явного дедлайна берётся отступ из настроек сайта, а не хардкод."""
    from apps.core.models import SiteSettings

    site = SiteSettings.load()
    site.registration_lead_hours = 48
    site.save()

    seminar = make_seminar(timezone.localdate() + timedelta(days=10))

    assert seminar.registration_deadline == seminar.starts_at - timedelta(hours=48)


def test_past_seminar_never_accepts_registration():
    seminar = make_seminar(
        timezone.localdate() - timedelta(days=1),
        registration_closes_at=timezone.now() + timedelta(days=30),
    )

    assert seminar.registration_open is False


def test_starts_at_is_moscow_time():
    seminar = make_seminar(timezone.localdate() + timedelta(days=1))

    assert seminar.starts_at.utcoffset() == timedelta(hours=3)
    assert seminar.starts_at.hour == 11


def test_speaker_order_follows_link_not_alphabet():
    """Первый автор — не произвольный: порядок задаётся связующей таблицей."""
    seminar = make_seminar(timezone.localdate())
    talk = add_talk(
        seminar,
        "Магниторецепция",
        [("Чернецов Никита Севирович", "ЗИН РАН"), ("Кавокин Кирилл Витальевич", "СПбГУ")],
    )

    names = [s.full_name_ru for s in talk.ordered_speakers]

    assert names == ["Чернецов Никита Севирович", "Кавокин Кирилл Витальевич"]


def test_search_text_includes_talks_and_speakers():
    seminar = make_seminar(timezone.localdate())
    add_talk(seminar, "Корональная сейсмология", [("Рудерман Михаил", "ИКИ РАН")])

    seminar.refresh_from_db()

    assert "Корональная сейсмология" in seminar.search_text
    assert "Рудерман Михаил" in seminar.search_text


def test_search_text_updates_when_talk_removed():
    seminar = make_seminar(timezone.localdate())
    talk = add_talk(seminar, "Временный доклад", [("Иванов И. И.", "ИКИ РАН")])

    talk.delete()
    seminar.refresh_from_db()

    assert "Временный доклад" not in seminar.search_text
