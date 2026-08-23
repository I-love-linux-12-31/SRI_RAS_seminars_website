from django.urls import path

from apps.core.views import privacy

from . import views

app_name = "seminars"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("about/", views.AboutView.as_view(), name="about"),
    path("privacy/", privacy, name="privacy"),
    path("archive/", views.ArchiveView.as_view(), name="archive"),
    # Шлюз внешних ссылок: прямых внешних адресов в разметке сайта нет.
    path("link/seminar/<slug:slug>/online/", views.OnlineLinkView.as_view(), name="online_link"),
    path("link/material/<int:pk>/", views.MaterialLinkView.as_view(), name="material_link"),
    path("seminar/<slug:slug>/", views.SeminarDetailView.as_view(), name="detail"),
]
