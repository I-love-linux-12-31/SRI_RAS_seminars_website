"""Общие настройки. Переопределения — в dev.py / prod.py / test.py."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django.contrib.sitemaps",
    "apps.core",
    "apps.seminars",
    "apps.registrations",
    "apps.staffpanel",
    "apps.notifications",
    "apps.legacy_import",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                # Даёт шаблонам LANGUAGE_CODE — без него <html lang> всегда «ru».
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site_settings",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{name}"}
    for name in (
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    )
]

# --- Локализация -------------------------------------------------------------
# Весь сайт живёт по московскому времени: заседания назначаются в MSK,
# и сравнения «прошло / не прошло» должны считаться именно в этой зоне.
LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True
LANGUAGES = [("ru", "Русский"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]

# --- Статика и медиа ---------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Кеш ---------------------------------------------------------------------
# БД, а не LocMem: ограничитель частоты обязан быть общим для всех процессов
# gunicorn, иначе предел умножается на число воркеров. Redis ради ~30 заявок
# в месяц заводить незачем. Таблицу создаёт миграция apps.core.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

# --- Фоновые задачи ----------------------------------------------------------
# В Django 6.1 у django.tasks есть только dummy- и immediate-бэкенды, БД-бэкенда нет.
# Свой лежит в apps.notifications.backend и реализует тот же BaseTaskBackend,
# поэтому переход на официальный (ожидается в 6.2) — смена одной строки ниже.
TASKS = {
    "default": {
        "BACKEND": "apps.notifications.backend.DatabaseTaskBackend",
        "QUEUES": ["default"],
    }
}

# --- Почта -------------------------------------------------------------------
# Django 6.1 объявил настройки EMAIL_* устаревшими (удаление в 7.0) в пользу
# MAILERS. django-environ пока умеет разбирать URL только в старую схему,
# поэтому переупаковываем результат сами.
_email = env.email_url("EMAIL_URL", default="consolemail://")
_backend = _email["EMAIL_BACKEND"]
_options: dict = {}
if _backend.endswith("smtp.EmailBackend"):
    _options = {
        "host": _email.get("EMAIL_HOST") or "localhost",
        "port": _email.get("EMAIL_PORT") or 25,
        "username": _email.get("EMAIL_HOST_USER") or "",
        "password": _email.get("EMAIL_HOST_PASSWORD") or "",
        "use_tls": bool(_email.get("EMAIL_USE_TLS")),
        "use_ssl": bool(_email.get("EMAIL_USE_SSL")),
        "timeout": env.int("EMAIL_TIMEOUT", default=10),
    }
elif _backend.endswith("filebased.EmailBackend"):
    _options = {"file_path": _email.get("EMAIL_FILE_PATH")}

MAILERS = {"default": {"BACKEND": _backend, "OPTIONS": _options}}

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="seminar@cosmos.ru")
SEMINAR_ADMIN_EMAIL = env("SEMINAR_ADMIN_EMAIL", default="seminar@cosmos.ru")

LOGIN_URL = "staffpanel:login"
LOGIN_REDIRECT_URL = "staffpanel:seminar_list"
LOGOUT_REDIRECT_URL = "seminars:home"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{levelname} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
