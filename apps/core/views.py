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
    """Согласие на обработку персональных данных.

    Заказчик отдаёт его документом, а не текстом, поэтому адрес отдаёт сам
    файл: ссылка в подвале и в форме записи открывает утверждённый PDF прямо
    в браузере. Пока файла нет, на его месте честная заглушка — подсовывать
    вместо согласия правдоподобный, но не согласованный текст хуже, чем
    не иметь его вовсе.
    """
    from django.http import FileResponse
    from django.shortcuts import render

    from .models import SiteSettings

    policy = SiteSettings.load()
    if policy.privacy_policy_file:
        return FileResponse(
            policy.privacy_policy_file.open("rb"),
            content_type="application/pdf",
            # inline: документ открывается по ссылке, а не скачивается файлом.
            as_attachment=False,
            filename="privacy-policy.pdf",
        )
    return render(request, "core/privacy.html", {"policy": policy})


def captcha_image(request):
    """Картинка с кодом. Код кладётся в сессию, ответ не кешируется."""
    from .captcha import new_code, render_png
    from .ratelimit import hit

    key = f"captcha:{request.META.get('REMOTE_ADDR', '')}"
    if hit(key, limit=60, window_seconds=600):
        return HttpResponse(status=429)

    response = HttpResponse(render_png(new_code(request.session)), content_type="image/png")
    response["Cache-Control"] = "no-store"
    return response


@cache_control(max_age=86400)
def robots_txt(request):
    sitemap = request.build_absolute_uri(reverse("sitemap"))
    lines = [
        "User-agent: *",
        # Панель и служебные адреса поисковикам не нужны.
        "Disallow: /manage/",
        "Disallow: /django-admin/",
        # Шлюз внешних ссылок: индексировать в нём нечего, а обходить его
        # краулерами — ровно то, от чего он и поставлен.
        "Disallow: /link/",
        "Disallow: /en/link/",
        "Allow: /",
        "",
        f"Sitemap: {sitemap}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
