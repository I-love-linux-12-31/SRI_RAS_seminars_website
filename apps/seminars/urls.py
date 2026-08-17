from django.urls import path

from apps.core.views import privacy

from . import views

app_name = "seminars"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("about/", views.AboutView.as_view(), name="about"),
    path("privacy/", privacy, name="privacy"),
    path("archive/", views.ArchiveView.as_view(), name="archive"),
    path("seminar/<slug:slug>/", views.SeminarDetailView.as_view(), name="detail"),
]
