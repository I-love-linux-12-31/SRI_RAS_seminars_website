import hashlib
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.seminars.models import Seminar


def hash_ip(ip: str | None) -> str:
    """Отпечаток IP для антиспама.

    Сырой IP не храним: он сам по себе персональные данные, а для ограничения
    частоты достаточно необратимого отпечатка. Соль — SECRET_KEY, поэтому
    хеши нельзя перебрать по списку адресов, не зная ключа.
    """
    if not ip:
        return ""
    digest = hashlib.sha256(f"{settings.SECRET_KEY}:{ip}".encode())
    return digest.hexdigest()[:32]


class Registration(models.Model):
    """Заявка на участие в заседании.

    Содержит персональные данные (152-ФЗ): ФИО, организация, должность, почта.
    ФИО и организация передаются в бюро пропусков, поэтому согласие
    фиксируется явно, вместе с моментом его получения.
    """

    class Attendance(models.TextChoices):
        ONSITE = "onsite", _("Очно")
        ONLINE = "online", _("Онлайн")

    class PassStatus(models.TextChoices):
        NOT_NEEDED = "not_needed", _("не требуется")
        PENDING = "pending", _("в обработке")
        ISSUED = "issued", _("оформлен")

    seminar = models.ForeignKey(
        Seminar, verbose_name=_("заседание"), on_delete=models.CASCADE, related_name="registrations"
    )

    full_name = models.CharField(_("ФИО"), max_length=200)
    organization = models.CharField(_("организация"), max_length=300)
    position = models.CharField(_("должность"), max_length=200, blank=True, default="")
    email = models.EmailField(_("контактная почта"))

    attendance = models.CharField(
        _("формат участия"), max_length=10, choices=Attendance.choices, default=Attendance.ONSITE
    )
    # Гражданство в заявке — не праздный вопрос: бюро пропусков оформляет
    # пропуск не гражданину РФ дольше, поэтому очные заявки от иностранцев
    # закрываются раньше остальных (см. Seminar.foreign_registration_open).
    is_foreign = models.BooleanField(_("не гражданин РФ"), default=False)
    pass_status = models.CharField(
        _("пропуск"), max_length=12, choices=PassStatus.choices, default=PassStatus.NOT_NEEDED
    )

    consent_pd = models.BooleanField(_("согласие на обработку ПД"), default=False)
    consent_at = models.DateTimeField(_("момент согласия"), null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    ip_hash = models.CharField(max_length=32, blank=True, default="", editable=False)

    class Meta:
        verbose_name = _("заявка")
        verbose_name_plural = _("заявки")
        ordering: ClassVar[list[str]] = ["-created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # Один человек — одна заявка на заседание. Ловит повторную отправку
            # формы и двойные клики.
            models.UniqueConstraint(
                models.functions.Lower("email"),
                "seminar",
                name="unique_registration_per_seminar",
            )
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["seminar", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.full_name} — {self.seminar_id}"

    @property
    def needs_pass(self) -> bool:
        return self.attendance == self.Attendance.ONSITE and self.seminar.pass_required

    @property
    def citizenship_display(self) -> str:
        """Для списка и выгрузки: бюро пропусков смотрит именно на это."""
        return str(_("не РФ") if self.is_foreign else _("РФ"))
