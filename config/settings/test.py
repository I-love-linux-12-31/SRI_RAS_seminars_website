from .base import *  # noqa: F403

DEBUG = False

STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Тесты не должны делить состояние ограничителя частоты между собой.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}

# Тесты гоняют задачи синхронно — воркер поднимать не нужно.
TASKS = {"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"}}
