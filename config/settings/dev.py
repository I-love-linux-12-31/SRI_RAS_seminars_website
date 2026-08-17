from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# В dev манифест статики мешает: collectstatic ещё не запускали.
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}

# Отдавать статику через finders, не требуя собранного STATIC_ROOT.
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True
