from django import template
from django.urls import translate_url

from apps.core.i18n import translate

register = template.Library()


@register.filter(name="tr")
def tr(obj, field: str) -> str:
    """{{ seminar|tr:"title" }} — поле на активном языке с откатом на русский."""
    return translate(obj, field)


@register.simple_tag(takes_context=True)
def switch_language_url(context, lang_code: str) -> str:
    """Тот же адрес на другом языке.

    Переключатель — обычные ссылки, а не форма с POST: так работают
    средний клик, «открыть в новой вкладке» и индексация hreflang.
    """
    request = context.get("request")
    if request is None:
        return "/"
    return translate_url(request.get_full_path(), lang_code)
