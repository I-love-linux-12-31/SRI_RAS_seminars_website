from django.db import connection
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.cache import cache_control


def healthz(request):
    """Проверка живости для контейнера и мониторинга: приложение плюс БД."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return HttpResponse("db unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


def privacy(request):
    """Страница согласия на обработку персональных данных.

    Текст заполняет заказчик через настройки сайта. Пока он пуст, страница
    честно говорит об этом — заглушка не должна выглядеть как настоящий
    юридический документ.
    """
    from django.shortcuts import render

    from .models import SiteSettings

    return render(request, "core/privacy.html", {"policy": SiteSettings.load()})


@cache_control(max_age=86400)
def robots_txt(request):
    sitemap = request.build_absolute_uri(reverse("sitemap"))
    lines = [
        "User-agent: *",
        # Панель и служебные адреса поисковикам не нужны.
        "Disallow: /manage/",
        "Disallow: /django-admin/",
        "Allow: /",
        "",
        f"Sitemap: {sitemap}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
