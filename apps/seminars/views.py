from django.contrib.postgres.search import SearchQuery, SearchVector
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.core import captcha
from apps.core.models import SiteSettings
from apps.core.ratelimit import hit

from .models import RUSSIAN_SEARCH_CONFIG, Material, Seminar

ARCHIVE_PAGE_SIZE = 20
RECENT_ON_HOME = 3
RELATED_ON_DETAIL = 3

_WRONG_CODE = _("Код с картинки не совпал. Попробуйте ещё раз.")
_TOO_MANY_TRIES = _("Слишком много попыток. Подождите немного и повторите.")


class HomeView(TemplateView):
    template_name = "seminars/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["nav"] = "home"
        # with_materials(): ближайшее заседание показывается тем же блоком, что
        # и на своей странице, а там есть материалы.
        context["upcoming"] = Seminar.objects.with_related().with_materials().upcoming().first()
        context["recent"] = Seminar.objects.with_related().archive()[:RECENT_ON_HOME]
        return context


class AboutView(TemplateView):
    template_name = "seminars/about.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["nav"] = "about"
        return context


class ArchiveView(ListView):
    template_name = "seminars/archive.html"
    context_object_name = "seminars"
    paginate_by = ARCHIVE_PAGE_SIZE

    def get_queryset(self):
        queryset = Seminar.objects.with_related().with_materials().archive()

        query = self.request.GET.get("q", "").strip()
        if query:
            # Полнотекстовый поиск с русской морфологией; выражение совпадает
            # с функциональным GIN-индексом seminar_search_gin.
            queryset = queryset.annotate(
                vector=SearchVector("search_text", config=RUSSIAN_SEARCH_CONFIG)
            ).filter(vector=SearchQuery(query, config=RUSSIAN_SEARCH_CONFIG))

        year = self.request.GET.get("year", "")
        if year.isdigit():
            queryset = queryset.filter(date__year=int(year))

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["nav"] = "archive"
        context["q"] = self.request.GET.get("q", "")
        context["year"] = self.request.GET.get("year", "")
        context["has_filters"] = any([context["q"], context["year"]])

        archive = Seminar.objects.archive()
        context["years"] = [d.year for d in archive.dates("date", "year", order="DESC")]
        return context


class SeminarDetailView(DetailView):
    template_name = "seminars/detail.html"
    context_object_name = "seminar"

    def get_queryset(self):
        # Сотрудник видит черновики и скрытые — это режим предпросмотра.
        return Seminar.objects.with_related().with_materials().visible_to(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["nav"] = "archive" if self.object.is_past else "home"
        # Тематики больше нет, и подбирать «похожие» не по чему — рядом идут
        # просто последние прошедшие заседания.
        context["related"] = (
            Seminar.objects.with_related().archive().exclude(pk=self.object.pk)[:RELATED_ON_DETAIL]
        )
        return context


class OutboundLinkView(View):
    """Шлюз, через который уходят все внешние ссылки сайта.

    В разметке внешних адресов нет — только локальные адреса этого шлюза, а
    куда вести, он выясняет сам по записи в базе. Поэтому произвольный адрес
    через него не подставить: открытого редиректа здесь нет по устройству.

    Ссылку на видеоконференцию шлюз отдаёт после проверки посетителя, остальные
    пропускает сразу: капча перед архивным PDF мешала бы без всякой пользы.
    """

    protected = False
    template_name = "seminars/link_challenge.html"

    def target(self) -> str:
        raise NotImplementedError

    def title(self) -> str:
        raise NotImplementedError

    def needs_challenge(self) -> bool:
        if not self.protected or not SiteSettings.load().online_link_captcha:
            return False
        return not captcha.is_verified(self.request.session)

    def leave(self, url: str) -> HttpResponseRedirect:
        response = HttpResponseRedirect(url)
        # Заголовок дублирует robots.txt: файл — просьба, заголовок — указание
        # тому краулеру, который до адреса всё-таки добрался.
        response["X-Robots-Tag"] = "noindex, nofollow"
        response["Referrer-Policy"] = "no-referrer"
        return response

    def challenge(self, error: str = "", status: int = 200):
        context = {"link_title": self.title(), "error": error, "nav": ""}
        response = render(self.request, self.template_name, context, status=status)
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response

    def get(self, request, **kwargs):
        if self.needs_challenge():
            return self.challenge()
        return self.leave(self.target())

    def post(self, request, **kwargs):
        url = self.target()
        if not self.needs_challenge():
            return self.leave(url)

        key = f"captcha-answer:{request.META.get('REMOTE_ADDR', '')}"
        if hit(key, limit=20, window_seconds=600):
            return self.challenge(_TOO_MANY_TRIES, status=429)

        if captcha.check(request.session, request.POST.get("answer", "")):
            return self.leave(url)
        return self.challenge(_WRONG_CODE, status=422)


class OnlineLinkView(OutboundLinkView):
    """Ссылка на видеоконференцию заседания."""

    protected = True

    def seminar(self) -> Seminar:
        if not hasattr(self, "_seminar"):
            self._seminar = get_object_or_404(
                Seminar.objects.visible_to(self.request.user).exclude(online_url=""),
                slug=self.kwargs["slug"],
            )
        return self._seminar

    def target(self) -> str:
        return self.seminar().online_url

    def title(self) -> str:
        return self.seminar().label


class MaterialLinkView(OutboundLinkView):
    """Материал заседания, лежащий ссылкой на другом сайте."""

    def material(self) -> Material:
        return get_object_or_404(
            Material.objects.select_related("seminar").exclude(url=""), pk=self.kwargs["pk"]
        )

    def target(self) -> str:
        return self.material().url

    def title(self) -> str:
        return self.material().get_kind_display()
