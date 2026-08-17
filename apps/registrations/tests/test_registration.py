"""Проверки формы записи на заседание."""

import time
from datetime import timedelta

import pytest
from django.core import mail, signing
from django.urls import reverse
from django.utils import timezone

from apps.registrations.forms import FORM_TIMESTAMP_SALT
from apps.registrations.models import Registration
from apps.seminars.models import Seminar
from apps.seminars.tests.factories import make_seminar

pytestmark = pytest.mark.django_db


def old_ts(seconds: int = 30) -> str:
    """Метка «форма отрисована N секунд назад», чтобы пройти ловушку по времени."""
    return signing.dumps(time.time() - seconds, salt=FORM_TIMESTAMP_SALT)


def payload(**overrides) -> dict:
    data = {
        "ts": old_ts(),
        "website": "",
        "attendance": Registration.Attendance.ONSITE,
        "full_name": "Иванов Иван Иванович",
        "organization": "МГУ, физический факультет",
        "position": "аспирант",
        "email": "ivanov@physics.msu.ru",
        "consent_pd": "on",
    }
    return data | overrides


@pytest.fixture
def seminar():
    return make_seminar(timezone.localdate() + timedelta(days=10))


def url_for(seminar: Seminar) -> str:
    return reverse("registrations:register", kwargs={"slug": seminar.slug})


# --- Успешный путь ------------------------------------------------------------


def test_registration_is_saved(client, seminar):
    response = client.post(url_for(seminar), payload())

    assert response.status_code == 200
    registration = Registration.objects.get()
    assert registration.full_name == "Иванов Иван Иванович"
    assert registration.seminar == seminar
    assert registration.consent_pd is True
    assert registration.consent_at is not None


def test_onsite_registration_requests_pass(client, seminar):
    client.post(url_for(seminar), payload(attendance="onsite"))

    assert Registration.objects.get().pass_status == Registration.PassStatus.PENDING


def test_online_registration_needs_no_pass(client, seminar):
    client.post(url_for(seminar), payload(attendance="online"))

    assert Registration.objects.get().pass_status == Registration.PassStatus.NOT_NEEDED


def test_raw_ip_is_never_stored(client, seminar):
    """IP — сам по себе персональные данные, храним только необратимый отпечаток."""
    client.post(url_for(seminar), payload(), REMOTE_ADDR="192.0.2.77")

    registration = Registration.objects.get()
    assert "192.0.2.77" not in registration.ip_hash
    assert len(registration.ip_hash) == 32


def test_full_name_whitespace_is_normalised(client, seminar):
    client.post(url_for(seminar), payload(full_name="  Иванов   Иван  Иванович "))

    assert Registration.objects.get().full_name == "Иванов Иван Иванович"


# --- Согласие на обработку ПД -------------------------------------------------


def test_registration_without_consent_is_rejected(client, seminar):
    response = client.post(url_for(seminar), payload(consent_pd=""))

    assert response.status_code == 422
    assert Registration.objects.count() == 0
    assert "согласия на обработку персональных данных" in response.content.decode()


def test_form_links_to_privacy_page(client, seminar):
    content = client.get(url_for(seminar)).content.decode()

    assert reverse("seminars:privacy") in content


# --- Антиспам -----------------------------------------------------------------


def test_honeypot_blocks_submission(client, seminar):
    response = client.post(url_for(seminar), payload(website="https://spam.example"))

    assert response.status_code == 422
    assert Registration.objects.count() == 0


def test_instant_submission_is_rejected(client, seminar):
    """Человек не заполняет форму за доли секунды — а бот заполняет."""
    response = client.post(
        url_for(seminar), payload(ts=signing.dumps(time.time(), salt=FORM_TIMESTAMP_SALT))
    )

    assert response.status_code == 422
    assert Registration.objects.count() == 0


def test_forged_timestamp_is_rejected(client, seminar):
    response = client.post(url_for(seminar), payload(ts="совершенно-точно-настоящая-метка"))

    assert response.status_code == 422
    assert Registration.objects.count() == 0


def test_rate_limit_blocks_flood(client, seminar):
    from apps.registrations.views import RATE_LIMIT

    last = None
    for i in range(RATE_LIMIT + 1):
        last = client.post(
            url_for(seminar),
            payload(email=f"user{i}@example.org"),
            REMOTE_ADDR="203.0.113.9",
        )

    assert last.status_code == 429
    assert Registration.objects.count() == RATE_LIMIT


# --- Дубликаты и закрытие приёма ----------------------------------------------


def test_duplicate_email_is_rejected_with_clear_message(client, seminar):
    client.post(url_for(seminar), payload())

    response = client.post(url_for(seminar), payload())

    assert response.status_code == 422
    assert Registration.objects.count() == 1
    assert "уже принята" in response.content.decode()


def test_duplicate_check_ignores_email_case(client, seminar):
    client.post(url_for(seminar), payload(email="ivanov@msu.ru"))

    response = client.post(url_for(seminar), payload(email="IVANOV@MSU.RU"))

    assert Registration.objects.count() == 1
    assert response.status_code == 422


def test_same_email_may_register_for_another_seminar(client, seminar):
    other = make_seminar(timezone.localdate() + timedelta(days=40), suffix="other")

    client.post(url_for(seminar), payload())
    client.post(url_for(other), payload())

    assert Registration.objects.count() == 2


def test_registration_closed_after_deadline(client):
    seminar = make_seminar(
        timezone.localdate() + timedelta(days=10),
        registration_closes_at=timezone.now() - timedelta(minutes=1),
    )

    response = client.post(url_for(seminar), payload())

    assert Registration.objects.count() == 0
    assert "закрыт" in response.content.decode()


def test_form_submitted_after_deadline_is_rejected(client, seminar):
    """Форму могли открыть до дедлайна, а отправить после — это должно ловиться."""
    content = client.get(url_for(seminar))
    assert content.status_code == 200

    seminar.registration_closes_at = timezone.now() - timedelta(seconds=1)
    seminar.save()

    client.post(url_for(seminar), payload())

    assert Registration.objects.count() == 0


def test_past_seminar_refuses_registration(client):
    seminar = make_seminar(timezone.localdate() - timedelta(days=1))

    client.post(url_for(seminar), payload())

    assert Registration.objects.count() == 0


def test_unpublished_seminar_has_no_registration_page(client):
    seminar = make_seminar(timezone.localdate() + timedelta(days=5), status=Seminar.Status.DRAFT)

    assert client.get(url_for(seminar)).status_code == 404


# --- Формат участия -----------------------------------------------------------


def test_online_only_seminar_offers_no_onsite_option(client):
    seminar = make_seminar(
        timezone.localdate() + timedelta(days=5),
        seminar_format=Seminar.Format.ONLINE,
    )

    content = client.get(url_for(seminar)).content.decode()

    assert 'value="onsite"' not in content


def test_onsite_choice_rejected_for_online_only_seminar(client):
    seminar = make_seminar(
        timezone.localdate() + timedelta(days=5),
        seminar_format=Seminar.Format.ONLINE,
    )

    response = client.post(url_for(seminar), payload(attendance="onsite"))

    assert response.status_code == 422
    assert Registration.objects.count() == 0


# --- Уведомления --------------------------------------------------------------


def test_both_notifications_are_queued(client, seminar, db_task_backend):
    """Задачи ставятся в очередь, а не отправляются в обработчике запроса."""
    from apps.notifications.models import TaskRecord

    client.post(url_for(seminar), payload())

    queued = set(TaskRecord.objects.values_list("task_path", flat=True))
    assert any("send_registration_confirmation" in path for path in queued)
    assert any("notify_admin_new_registration" in path for path in queued)


def test_worker_sends_confirmation_and_admin_notice(client, seminar, db_task_backend):
    from django.core.management import call_command

    client.post(url_for(seminar), payload())
    call_command("run_task_worker")

    assert len(mail.outbox) == 2
    to_participant = [m for m in mail.outbox if "ivanov@physics.msu.ru" in m.to]
    assert len(to_participant) == 1
    assert "Иванов Иван Иванович" in to_participant[0].body


def test_admin_notice_respects_disabled_setting(client, seminar, db_task_backend):
    from django.core.management import call_command

    from apps.core.models import SiteSettings

    site = SiteSettings.load()
    site.notify_on_registration = False
    site.save()

    client.post(url_for(seminar), payload())
    call_command("run_task_worker")

    assert len(mail.outbox) == 1, "участнику письмо идёт всегда, администратору — по настройке"


def test_failed_registration_queues_nothing(client, seminar, db_task_backend):
    from apps.notifications.models import TaskRecord

    client.post(url_for(seminar), payload(consent_pd=""))

    assert TaskRecord.objects.count() == 0
