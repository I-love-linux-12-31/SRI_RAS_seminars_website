from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.core.views import captcha_image, healthz, robots_txt
from apps.seminars.sitemaps import sitemaps

# Вне i18n_patterns: служебные адреса не должны существовать в двух языковых копиях.
urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("robots.txt", robots_txt, name="robots"),
    path("captcha.png", captcha_image, name="captcha_image"),
    path("sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="sitemap"),
    # Аварийный доступ суперпользователя. Основная панель — /manage/.
    path("django-admin/", admin.site.urls),
]

# prefix_default_language=False: русский живёт на /, английский на /en/.
urlpatterns += i18n_patterns(
    path("", include("apps.registrations.urls")),
    path("", include("apps.seminars.urls")),
    path("manage/", include("apps.staffpanel.urls")),
    prefix_default_language=False,
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
