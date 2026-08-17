"""Форма записи на заседание.

Антиспам без CAPTCHA: reCAPTCHA внешняя и несвободная, а институтский сайт
должен работать в закрытом контуре. Вместо неё три дешёвых приёма, ни один
из которых не мешает живому человеку и не ломает доступность:

1. honeypot — поле, скрытое от людей; бот его заполняет;
2. ловушка по времени — подписанная метка рендера, мгновенная отправка отсеивается;
3. ограничение частоты по отпечатку IP (во view).
"""

import time
from typing import ClassVar

from django import forms
from django.core import signing
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.seminars.models import Seminar

from .models import Registration

# Быстрее этого форму не заполнит даже человек, копирующий из буфера.
MIN_FILL_SECONDS = 3
# Подписанная метка живёт ограниченно, чтобы её нельзя было переиспользовать.
MAX_FORM_AGE_SECONDS = 60 * 60 * 6
FORM_TIMESTAMP_SALT = "registration-form-timestamp"


class RegistrationForm(forms.ModelForm):
    # Honeypot. Название правдоподобное — боты заполняют такие охотнее.
    website = forms.CharField(required=False, widget=forms.HiddenInput)
    ts = forms.CharField(required=False, widget=forms.HiddenInput)

    consent_pd = forms.BooleanField(
        required=True,
        label=_("Я согласен на обработку персональных данных"),
        error_messages={
            "required": _("Без согласия на обработку персональных данных заявку принять нельзя.")
        },
    )

    class Meta:
        model = Registration
        fields: ClassVar[list[str]] = [
            "attendance",
            "full_name",
            "organization",
            "position",
            "email",
            "consent_pd",
        ]
        widgets: ClassVar[dict] = {
            "attendance": forms.RadioSelect,
            "full_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "organization": forms.TextInput(attrs={"autocomplete": "organization"}),
            "position": forms.TextInput(attrs={"autocomplete": "organization-title"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email", "inputmode": "email"}),
        }

    def __init__(self, *args, seminar: Seminar, **kwargs):
        super().__init__(*args, **kwargs)
        self.seminar = seminar
        self.fields["ts"].initial = signing.dumps(time.time(), salt=FORM_TIMESTAMP_SALT)

        if not seminar.allows_onsite:
            self.fields["attendance"].initial = Registration.Attendance.ONLINE
        if not seminar.allows_online:
            self.fields["attendance"].initial = Registration.Attendance.ONSITE

        # Оставляем только те форматы, которые заседание действительно допускает.
        self.fields["attendance"].choices = [
            (value, label)
            for value, label in Registration.Attendance.choices
            if (value == Registration.Attendance.ONSITE and seminar.allows_onsite)
            or (value == Registration.Attendance.ONLINE and seminar.allows_online)
        ]

        for name in ("full_name", "organization", "position", "email"):
            self.fields[name].widget.attrs.setdefault("class", "field")

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError(_("Не удалось отправить заявку."), code="honeypot")
        return ""

    def clean_ts(self):
        raw = self.cleaned_data.get("ts") or ""
        try:
            rendered_at = signing.loads(raw, salt=FORM_TIMESTAMP_SALT, max_age=MAX_FORM_AGE_SECONDS)
        except signing.BadSignature as exc:
            # Подделанная или протухшая метка: просим открыть форму заново.
            raise forms.ValidationError(
                _("Форма устарела. Обновите страницу и попробуйте ещё раз."), code="stale"
            ) from exc

        if time.time() - float(rendered_at) < MIN_FILL_SECONDS:
            raise forms.ValidationError(_("Не удалось отправить заявку."), code="too_fast")
        return raw

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        already = (
            Registration.objects.annotate(email_lower=Lower("email"))
            .filter(email_lower=email.lower(), seminar=self.seminar)
            .exists()
        )
        if already:
            raise forms.ValidationError(
                _("Заявка с этой почтой на данное заседание уже принята."), code="duplicate"
            )
        return email

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if len(name) < 3:
            raise forms.ValidationError(_("Укажите фамилию, имя и отчество."))
        return name

    def clean_organization(self):
        return " ".join(self.cleaned_data["organization"].split())

    def clean(self):
        cleaned = super().clean()
        # Дублирует проверку во view: форма может быть открыта до дедлайна,
        # а отправлена после.
        if not self.seminar.registration_open:
            raise forms.ValidationError(_("Приём заявок на это заседание закрыт."), code="closed")
        return cleaned

    def save(self, commit=True, ip: str | None = None):
        from .models import hash_ip

        registration = super().save(commit=False)
        registration.seminar = self.seminar
        registration.consent_at = timezone.now()
        registration.ip_hash = hash_ip(ip)
        registration.pass_status = (
            Registration.PassStatus.PENDING
            if registration.needs_pass
            else Registration.PassStatus.NOT_NEEDED
        )
        if commit:
            registration.save()
        return registration
