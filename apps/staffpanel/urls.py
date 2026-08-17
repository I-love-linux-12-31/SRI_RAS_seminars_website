from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "staffpanel"

login_view = auth_views.LoginView.as_view(
    template_name="staffpanel/login.html", redirect_authenticated_user=True
)

urlpatterns = [
    path("login/", login_view, name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.SeminarListView.as_view(), name="seminar_list"),
    path("seminar/new/", views.SeminarEditView.as_view(), name="seminar_create"),
    path("seminar/<int:pk>/", views.SeminarEditView.as_view(), name="seminar_edit"),
    path("seminar/<int:pk>/clone/", views.SeminarCloneView.as_view(), name="seminar_clone"),
    path("seminar/<int:pk>/toggle/", views.SeminarToggleView.as_view(), name="seminar_toggle"),
    path("registrations/", views.RegistrationListView.as_view(), name="registrations"),
    path(
        "registrations/export.<str:fmt>",
        views.RegistrationExportView.as_view(),
        name="registrations_export",
    ),
    path("registration/<int:pk>/pass/", views.PassStatusView.as_view(), name="pass_status"),
    path("settings/", views.SiteSettingsView.as_view(), name="settings"),
]
