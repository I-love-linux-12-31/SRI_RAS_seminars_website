from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _
from django.views import View

from apps.core.ratelimit import hit
from apps.notifications.tasks import notify_admin_new_registration, send_registration_confirmation
from apps.registrations.models import hash_ip
from apps.seminars.models import Seminar

from .forms import RegistrationForm

# Предел на адрес, а не на человека: сотрудники института и целые лаборатории
# сидят за общим NAT и приходят с одного IP. При аудитории ~30 человек
# тридцать попыток в час — заведомо больше любого честного всплеска,
# но уже отсекает поток. Основную работу делают honeypot и ловушка по времени.
RATE_LIMIT = 30
RATE_WINDOW_SECONDS = 60 * 60


def client_ip(request) -> str:
    """IP клиента с учётом обратного прокси.

    Берём последний элемент X-Forwarded-For: его подставляет наш nginx,
    а всё, что левее, клиент может подделать.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


class RegisterView(View):
    """Запись на заседание.

    Работает и как обычная страница с полной перезагрузкой, и как содержимое
    модального окна: htmx подставляет те же куски разметки. Без JavaScript
    форма остаётся полностью рабочей.
    """

    def get_seminar(self, slug: str) -> Seminar:
        return get_object_or_404(Seminar.objects.published(), slug=slug)

    def is_htmx(self) -> bool:
        return self.request.headers.get("HX-Request") == "true"

    def render_form(self, seminar: Seminar, form: RegistrationForm, status: int = 200):
        context = {"seminar": seminar, "form": form}
        template = "registrations/_form.html" if self.is_htmx() else "registrations/page.html"
        return render(self.request, template, context, status=status)

    def get(self, request, slug):
        seminar = self.get_seminar(slug)
        if not seminar.registration_open:
            return self.render_closed(seminar)
        return self.render_form(seminar, RegistrationForm(seminar=seminar))

    def post(self, request, slug):
        seminar = self.get_seminar(slug)
        if not seminar.registration_open:
            return self.render_closed(seminar)

        ip = client_ip(request)
        if hit(f"reg:{hash_ip(ip)}", limit=RATE_LIMIT, window_seconds=RATE_WINDOW_SECONDS):
            return self.render_throttled(seminar)

        form = RegistrationForm(request.POST, seminar=seminar)
        if not form.is_valid():
            # 422, чтобы htmx не считал ответ успешным, но всё равно показал разметку.
            return self.render_form(seminar, form, status=422)

        registration = form.save(ip=ip)

        # Задачи ложатся в ту же транзакцию, что и сама заявка: письмо не уйдёт,
        # если сохранение откатится, и не потеряется, если SMTP недоступен.
        send_registration_confirmation.enqueue(registration.pk)
        notify_admin_new_registration.enqueue(registration.pk)

        context = {"seminar": seminar, "registration": registration}
        template = "registrations/_success.html" if self.is_htmx() else "registrations/success.html"
        return render(request, template, context)

    def render_closed(self, seminar: Seminar):
        context = {
            "seminar": seminar,
            "message": _("Приём заявок на это заседание закрыт."),
        }
        template = "registrations/_notice.html" if self.is_htmx() else "registrations/notice.html"
        return render(self.request, template, context, status=200)

    def render_throttled(self, seminar: Seminar) -> HttpResponse:
        context = {
            "seminar": seminar,
            "message": _(
                "Слишком много попыток с этого адреса. "
                "Попробуйте позже или напишите на почту семинара."
            ),
        }
        template = "registrations/_notice.html" if self.is_htmx() else "registrations/notice.html"
        return render(self.request, template, context, status=429)
