"""Статические проверки шаблонов."""

import re
from pathlib import Path

from django.conf import settings

TEMPLATE_ROOT = Path(settings.BASE_DIR) / "templates"


def test_no_multiline_hash_comments():
    """`{# … #}` в Django однострочный.

    Лексер шаблонов ищет комментарий регуляркой без DOTALL, поэтому запись
    через перенос строки комментарием не считается и целиком выводится
    посетителю. Один такой «комментарий» уже успел показаться в панели
    управления. Для многострочных пояснений есть {% comment %}.
    """
    offenders = []
    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            _before, marker, tail = line.partition("{#")
            if marker and "#}" not in tail:
                relative = path.relative_to(TEMPLATE_ROOT)
                offenders.append(f"{relative}:{number}")

    assert not offenders, (
        "Многострочный {# … #} выводится на страницу как текст. "
        "Замените на {% comment %}: " + ", ".join(offenders)
    )


def test_templates_render_no_stray_template_syntax():
    """Незакрытые теги легко пропустить глазами — ловим грубые случаи."""
    pattern = re.compile(r"\{%\s*(if|for|block|comment|with)\b")
    closing = re.compile(r"\{%\s*end(if|for|block|comment|with)\b")

    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        text = path.read_text()
        opened = len(pattern.findall(text))
        closed = len(closing.findall(text))
        assert opened == closed, (
            f"{path.relative_to(TEMPLATE_ROOT)}: {opened} тегов, {closed} закрытий"
        )
