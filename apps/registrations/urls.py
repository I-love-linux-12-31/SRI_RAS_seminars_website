from django.urls import path

from . import views

app_name = "registrations"

urlpatterns = [
    path("seminar/<slug:slug>/register/", views.RegisterView.as_view(), name="register"),
]
