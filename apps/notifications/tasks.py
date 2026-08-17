"""Письма по заявкам на семинар.

Задачи ставятся в очередь внутри транзакции запроса (ATOMIC_REQUESTS), поэтому
заявка и письмо о ней либо сохраняются вместе, либо не сохраняются вовсе.
Отправкой занимается воркер: лежащий SMTP не должен превращаться в таймаут
у человека, заполнившего форму.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.tasks import task
from django.template.loader import render_to_string
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)


def _send(subject: str, body: str, to: list[str]) -> str:
    if not to:
        return "no recipients"
    # using=<алиас MAILERS>, а не connection=: последний объявлен устаревшим
    # в 6.1 вместе с остальным старым почтовым API.
    EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
    ).send(using="default")
    return f"sent to {len(to)}"


@task()
def send_registration_confirmation(registration_id: int) -> str:
    """Подтверждение участнику: что записан и что будет дальше."""
    from apps.registrations.models import Registration

    registration = Registration.objects.select_related("seminar").filter(pk=registration_id).first()
    if registration is None:
        # Заявку могли удалить, пока письмо ждало очереди. Это не ошибка.
        logger.info("Заявка %s исчезла до отправки подтверждения", registration_id)
        return "registration gone"

    body = render_to_string(
        "registrations/email/confirmation.txt",
        {"registration": registration, "seminar": registration.seminar},
    )
    subject = _("Заявка принята: семинар ИКИ РАН %(date)s") % {
        "date": registration.seminar.date.strftime("%d.%m.%Y")
    }
    return _send(subject, body, [registration.email])


@task()
def notify_admin_new_registration(registration_id: int) -> str:
    """Уведомление секретарю семинара о новой заявке."""
    from apps.core.models import SiteSettings
    from apps.registrations.models import Registration

    registration = Registration.objects.select_related("seminar").filter(pk=registration_id).first()
    if registration is None:
        return "registration gone"

    site = SiteSettings.load()
    if not site.notify_on_registration:
        return "notifications disabled"

    recipient = site.notify_email or site.email or settings.SEMINAR_ADMIN_EMAIL
    body = render_to_string(
        "registrations/email/admin_notice.txt",
        {"registration": registration, "seminar": registration.seminar},
    )
    subject = _("Новая заявка: %(name)s, %(org)s") % {
        "name": registration.full_name,
        "org": registration.organization,
    }
    return _send(subject, body, [recipient])
