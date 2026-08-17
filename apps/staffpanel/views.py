from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import TemplateView

from apps.registrations.models import Registration
from apps.seminars.models import Seminar, TalkSpeaker

from .export import registrations_csv, registrations_xlsx
from .forms import MaterialFormSet, SeminarForm, SiteSettingsForm, TalkFormSet


def back_to(request, fallback: str) -> str:
    """Вернуться туда, откуда пришли, но только если это наш адрес.

    Referer подставляет браузер, и доверять ему как цели редиректа нельзя:
    иначе получается открытый редирект на чужой сайт.
    """
    referer = request.META.get("HTTP_REFERER", "")
    if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return referer
    return fallback


class StaffRequiredMixin(UserPassesTestMixin):
    """Панель доступна только сотрудникам.

    Анонимов Django уводит на форму входа, вошедшим без прав отдаёт 403 —
    гонять залогиненного человека по кругу на логин бессмысленно.

    Если у представления задан `required_permission`, проверяется ещё и он:
    так секретарь ведёт заседания и заявки, но не правит тексты сайта.
    Группы создаёт команда `setup_groups`.
    """

    required_permission: str | None = None

    def test_func(self):
        user = self.request.user
        if not (user.is_authenticated and user.is_staff):
            return False
        if self.required_permission is None:
            return True
        return user.has_perm(self.required_permission)


class SeminarListView(StaffRequiredMixin, TemplateView):
    template_name = "staffpanel/seminar_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["nav"] = "manage"
        context["tab"] = "seminars"

        seminars = (
            Seminar.objects.select_related("topic")
            .annotate(registration_count=Count("registrations"))
            .order_by("-date")
        )
        context["seminars"] = seminars

        today = timezone.localdate()
        upcoming = Seminar.objects.upcoming().first()
        context["stats"] = [
            (_("Опубликовано"), Seminar.objects.filter(status=Seminar.Status.PUBLISHED).count()),
            (_("Черновики"), Seminar.objects.filter(status=Seminar.Status.DRAFT).count()),
            (
                _("Заявок на ближайшее"),
                upcoming.registrations.count() if upcoming else 0,
            ),
            (
                _("Пропусков в работе"),
                Registration.objects.filter(
                    pass_status=Registration.PassStatus.PENDING, seminar__date__gte=today
                ).count(),
            ),
        ]
        return context


class SeminarEditView(StaffRequiredMixin, View):
    """Создание и правка заседания вместе с докладами и материалами."""

    required_permission = "seminars.change_seminar"
    template_name = "staffpanel/seminar_form.html"

    def get_object(self, pk: int | None) -> Seminar | None:
        if pk is None:
            return None
        return get_object_or_404(Seminar, pk=pk)

    def build(self, seminar: Seminar | None, data=None, files=None):
        return (
            SeminarForm(data, files, instance=seminar),
            TalkFormSet(data, files, instance=seminar, prefix="talks"),
            MaterialFormSet(data, files, instance=seminar, prefix="materials"),
        )

    def render(self, request, seminar, form, talks, materials, status=200):
        context = {
            "nav": "manage",
            "seminar": seminar,
            "form": form,
            "talks": talks,
            "materials": materials,
            "is_new": seminar is None,
        }
        return render(request, self.template_name, context, status=status)

    def get(self, request, pk=None):
        seminar = self.get_object(pk)
        return self.render(request, seminar, *self.build(seminar))

    def post(self, request, pk=None):
        seminar = self.get_object(pk)
        form, talks, materials = self.build(seminar, request.POST, request.FILES)

        if not (form.is_valid() and talks.is_valid() and materials.is_valid()):
            return self.render(request, seminar, form, talks, materials, status=422)

        with transaction.atomic():
            if seminar is None:
                form.instance.created_by = request.user
            seminar = form.save()

            talks.instance = seminar
            for talk in talks.save():
                # Докладчиков сохраняет сама форма доклада: связь идёт через
                # промежуточную модель с порядком, обычный save() её не тронет.
                talk_form = next(f for f in talks.forms if f.instance.pk == talk.pk)
                talk_form.sync_speakers(talk)

            materials.instance = seminar
            materials.save()

            # Поисковый текст зависит от докладов, а они сохранились после семинара.
            seminar.rebuild_search_text()

        messages.success(request, _("Заседание сохранено."))
        return redirect("staffpanel:seminar_list")


class SeminarCloneView(StaffRequiredMixin, View):
    """«На основе существующего»: копия без даты, заявок и статуса."""

    required_permission = "seminars.add_seminar"

    def post(self, request, pk):
        source = get_object_or_404(Seminar.objects.prefetch_related("talks__speaker_links"), pk=pk)

        with transaction.atomic():
            clone = Seminar.objects.get(pk=pk)
            clone.pk = None
            clone.slug = ""
            clone.status = Seminar.Status.DRAFT
            clone.registration_closes_at = None
            clone.created_by = request.user
            clone.title_ru = _("Копия: %s") % source.title_ru
            clone.slug = SeminarForm._build_slug(clone)
            clone.save()

            for talk in source.talks.all():
                links = list(talk.speaker_links.all())
                talk.pk = None
                talk.seminar = clone
                talk.save()
                for link in links:
                    TalkSpeaker.objects.create(talk=talk, speaker=link.speaker, order=link.order)

            clone.rebuild_search_text()

        messages.success(
            request,
            _("Создана копия. Укажите дату и опубликуйте, когда всё будет готово."),
        )
        return redirect("staffpanel:seminar_edit", pk=clone.pk)


class SeminarToggleView(StaffRequiredMixin, View):
    """Скрыть или показать заседание."""

    required_permission = "seminars.change_seminar"

    def post(self, request, pk):
        seminar = get_object_or_404(Seminar, pk=pk)

        if seminar.status == Seminar.Status.PUBLISHED:
            seminar.status = Seminar.Status.HIDDEN
            note = _("Заседание скрыто от посетителей.")
        else:
            seminar.status = Seminar.Status.PUBLISHED
            note = _("Заседание опубликовано.")
        seminar.save(update_fields=["status", "updated_at"])

        messages.success(request, note)
        return redirect(back_to(request, reverse("staffpanel:seminar_list")))


class RegistrationListView(StaffRequiredMixin, TemplateView):
    required_permission = "registrations.view_registration"
    template_name = "staffpanel/registrations.html"

    def get_seminar(self) -> Seminar | None:
        raw = self.request.GET.get("seminar")
        if not raw or not raw.isdigit():
            return Seminar.objects.upcoming().first()
        return Seminar.objects.filter(pk=int(raw)).first()

    def get_queryset(self):
        queryset = Registration.objects.select_related("seminar")
        seminar = self.get_seminar()
        if seminar is not None:
            queryset = queryset.filter(seminar=seminar)

        status = self.request.GET.get("pass")
        if status in Registration.PassStatus.values:
            queryset = queryset.filter(pass_status=status)

        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(full_name__icontains=query)
                | Q(organization__icontains=query)
                | Q(email__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["nav"] = "manage"
        context["tab"] = "registrations"
        context["seminar"] = self.get_seminar()
        context["registrations"] = self.get_queryset()
        context["seminars"] = Seminar.objects.order_by("-date")[:50]
        context["q"] = self.request.GET.get("q", "")
        context["pass_filter"] = self.request.GET.get("pass", "")
        context["pass_statuses"] = Registration.PassStatus.choices
        return context


class RegistrationExportView(RegistrationListView):
    """Выгрузка того же набора, что видно на экране, с учётом фильтров."""

    def get(self, request, fmt: str):
        seminar = self.get_seminar()
        registrations = self.get_queryset()

        if fmt == "xlsx":
            return registrations_xlsx(registrations, seminar)
        if fmt == "csv":
            return registrations_csv(registrations, seminar)
        raise Http404


class PassStatusView(StaffRequiredMixin, View):
    """Отметка о состоянии пропуска."""

    required_permission = "registrations.change_registration"

    def post(self, request, pk):
        registration = get_object_or_404(Registration, pk=pk)
        status = request.POST.get("pass_status")

        if status not in Registration.PassStatus.values:
            messages.error(request, _("Неизвестный статус пропуска."))
        else:
            registration.pass_status = status
            registration.save(update_fields=["pass_status"])
            messages.success(request, _("Статус пропуска обновлён."))

        return HttpResponseRedirect(back_to(request, reverse("staffpanel:registrations")))


class SiteSettingsView(StaffRequiredMixin, View):
    """Тексты сайта и настройки уведомлений.

    Отдельное право: формулировку согласия на обработку ПД и контакты
    меняет руководитель, а не любой сотрудник с доступом к панели.
    """

    required_permission = "core.change_sitesettings"
    template_name = "staffpanel/settings.html"
    success_url = reverse_lazy("staffpanel:settings")

    @staticmethod
    def context(form) -> dict:
        return {"form": form, "nav": "manage", "tab": "settings"}

    def get(self, request):
        from apps.core.models import SiteSettings

        form = SiteSettingsForm(instance=SiteSettings.load())
        return render(request, self.template_name, self.context(form))

    def post(self, request):
        from apps.core.models import SiteSettings

        form = SiteSettingsForm(request.POST, instance=SiteSettings.load())
        if not form.is_valid():
            return render(request, self.template_name, self.context(form), status=422)

        form.save()
        messages.success(request, _("Настройки сохранены."))
        return redirect(self.success_url)
