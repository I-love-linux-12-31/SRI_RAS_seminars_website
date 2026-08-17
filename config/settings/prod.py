from .base import *  # noqa: F403
from .base import env

DEBUG = False

# За nginx, который терминирует TLS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)

# Проверка живости ходит к gunicorn напрямую, по http и в обход nginx, поэтому
# заголовка X-Forwarded-Proto у неё нет. Без этого исключения /healthz отвечает
# редиректом на https, контейнер навсегда остаётся unhealthy, а всё, что ждёт
# его готовности (воркер, nginx), не дожидается никогда.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Куки только по https. По умолчанию — как SECURE_SSL_REDIRECT: обе настройки
# отвечают на один вопрос «сайт отдаётся по TLS?», и расходиться им нельзя.
#
# Если оставить их включёнными на сайте без TLS, браузер просто не сохранит
# ни csrftoken, ни сессию, и любая форма упрётся в «CSRF cookie not set» —
# при верном CSRF_TRUSTED_ORIGINS, отчего причина выглядит совсем другой.
# Отдельные переменные оставлены на случай, когда TLS терминируется снаружи,
# а сюда трафик идёт по http без заголовка X-Forwarded-Proto.
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=SECURE_SSL_REDIRECT)
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
