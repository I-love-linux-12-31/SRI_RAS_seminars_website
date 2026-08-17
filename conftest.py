"""Общие фикстуры.

Здесь лежит то, что относится ко всему проекту: изоляция кеша и активного
языка между тестами и корректная подмена бэкенда фоновых задач.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_language():
    """Сбросить активный язык до и после теста.

    LocaleMiddleware включает язык запроса и обратно его не выключает, а
    активный язык живёт в памяти процесса. Поэтому один запрос к /en/ оставлял
    английский всем последующим тестам: reverse() начинал отдавать адреса с
    префиксом /en/, а шаблоны — английский перевод.
    """
    from django.utils import translation

    translation.deactivate()
    yield
    translation.deactivate()


@pytest.fixture(autouse=True)
def _isolate_cache():
    """Очистить кеш до и после теста.

    Кеш процессный (LocMem) и переживает границы тестов, поэтому счётчик
    ограничителя частоты копился бы от теста к тесту и ронял чужие проверки.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _isolate_media(settings, tmp_path):
    """Загрузки из тестов — во временный каталог.

    Иначе фотографии докладчиков и афиши, которые заливают проверки панели,
    оседают в media/ проекта и остаются там после прогона.
    """
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def db_task_backend(settings):
    """Переключить очередь задач на БД-бэкенд.

    Просто присвоить settings.TASKS недостаточно: в отличие от DATABASES и
    CACHES, Django не сбрасывает обработчик задач по сигналу setting_changed,
    поэтому уже созданный бэкенд остался бы прежним и подмена молча не
    сработала бы. Чистим кеш обработчика руками.
    """
    from django.tasks import task_backends

    settings.TASKS = {"default": {"BACKEND": "apps.notifications.backend.DatabaseTaskBackend"}}
    _reset(task_backends)
    yield
    _reset(task_backends)


def _reset(handler) -> None:
    from asgiref.local import Local

    handler.__dict__.pop("settings", None)
    handler._settings = None
    handler._connections = Local(thread_critical=handler.thread_critical)
