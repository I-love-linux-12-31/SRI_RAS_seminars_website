from django.contrib.postgres.search import SearchQuery, SearchVector
from django.views.generic import DetailView, ListView, TemplateView

from .models import RUSSIAN_SEARCH_CONFIG, Seminar

ARCHIVE_PAGE_SIZE = 20
RECENT_ON_HOME = 3
RELATED_ON_DETAIL = 3


class HomeView(TemplateView):
    template_name = "seminars/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["nav"] = "home"
        context["upcoming"] = Seminar.objects.with_related().upcoming().first()
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
