"""Ограничение частоты запросов через общий кеш.

Считает попытки, а не только успешные заявки: бот, который валится на
валидации, тоже должен упираться в предел. Кеш обязан быть общим для всех
процессов gunicorn — в проде это БД-бэкенд, см. CACHES в настройках.
"""

from django.core.cache import cache

PREFIX = "rl"


def hit(key: str, *, limit: int, window_seconds: int) -> bool:
    """Учесть попытку. True — предел превышен, запрос надо отклонить."""
    cache_key = f"{PREFIX}:{key}"
    count = cache.get(cache_key)

    if count is None:
        # add(), а не set(): не затираем счётчик, если другой процесс успел раньше.
        if cache.add(cache_key, 1, window_seconds):
            return False
        count = cache.get(cache_key) or 0

    if count >= limit:
        return True

    try:
        cache.incr(cache_key)
    except ValueError:
        # Ключ истёк между чтением и инкрементом — начинаем окно заново.
        cache.add(cache_key, 1, window_seconds)
    return False


def reset(key: str) -> None:
    cache.delete(f"{PREFIX}:{key}")
