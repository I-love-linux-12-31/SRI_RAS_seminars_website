"""Перевод контентных полей.

Интерфейсные строки живут в .po через gettext, а содержимое (темы докладов,
имена докладчиков) — в парах колонок `*_ru` / `*_en` на самой модели.

Почему так, а не django-modeltranslation: языка всего два, переводимых полей
около десятка, а будущее автозаполнение английского через LibreTranslate
сводится к проходу по пустым `*_en` — никакой магии и монкипатчинга.

Русский всегда основной: если английского перевода нет, показываем русский,
а не пустоту.
"""

from django.utils.translation import get_language

DEFAULT_LANGUAGE = "ru"


def translate(obj, field: str) -> str:
    lang = (get_language() or DEFAULT_LANGUAGE).split("-")[0]
    if lang != DEFAULT_LANGUAGE:
        value = getattr(obj, f"{field}_{lang}", "")
        if value:
            return value
    return getattr(obj, f"{field}_{DEFAULT_LANGUAGE}", "") or ""


class TranslatedMixin:
    """Добавляет `.tr("title")` моделям с полями `title_ru` / `title_en`."""

    def tr(self, field: str) -> str:
        return translate(self, field)
