from typing import ClassVar

from django.db import models
from django.utils.translation import gettext_lazy as _


class LegacySeminarLink(models.Model):
    """Откуда приехало заседание при импорте со старого сайта.

    Нужна ради двух вещей.

    Во-первых, повторный запуск импорта. Без отметки «этот узел уже импортирован»
    команда либо плодила бы дубликаты, либо угадывала бы соответствие по дате и
    заголовку — а заголовок секретарь как раз и правит после импорта.

    Во-вторых, адреса. На старом сайте заседания лежат по `/seminar/<slug>`, и
    ровно такой же префикс у нового сайта, но slug мы генерируем свой. Сохранённый
    здесь `legacy_slug` позволяет потом собрать карту редиректов и не потерять
    ссылки из писем и поисковой выдачи.
    """

    seminar = models.OneToOneField(
        "seminars.Seminar",
        verbose_name=_("заседание"),
        on_delete=models.CASCADE,
        related_name="legacy_link",
    )
    node_id = models.CharField(_("узел старого сайта"), max_length=20, unique=True)
    legacy_slug = models.CharField(_("адрес на старом сайте"), max_length=220, blank=True)
    legacy_url = models.URLField(_("страница-источник"), max_length=500)
    imported_at = models.DateTimeField(_("импортировано"), auto_now=True)

    class Meta:
        verbose_name = _("связь со старым сайтом")
        verbose_name_plural = _("связи со старым сайтом")
        ordering: ClassVar[list[str]] = ["node_id"]

    def __str__(self):
        return f"node/{self.node_id} → {self.seminar_id}"
