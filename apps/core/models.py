from asgiref.local import Local
from django.core.cache import cache
from django.core.signals import request_started
from django.core.validators import FileExtensionValidator
from django.db import models
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

# Память на время запроса.
#
# Общий кеш живёт в базе (см. CACHES), поэтому каждый cache.get() — это
# отдельный запрос. Настройки же запрашиваются по нескольку раз за рендер:
# из контекст-процессора и из Seminar.registration_deadline, который шаблон
# дёргает на каждую проверку «регистрация открыта». Без этой памятки одна
# главная страница стоила пяти лишних походов в БД, то есть кеш работал
# в минус. Внутри запроса настройки заведомо не меняются.
_request_local = Local()


class SiteSettings(models.Model):
    """Singleton с текстами, которые редактирует секретарь семинара.

    Всё, что в макете зашито в вёрстку (контакты, руководитель, адрес,
    порядок посещения), должно меняться без правки кода.
    """

    chair_ru = models.CharField(_("руководитель"), max_length=200, default="")
    chair_en = models.CharField(max_length=200, blank=True, default="")
    chair_title_ru = models.CharField(_("звание руководителя"), max_length=200, default="")
    chair_title_en = models.CharField(max_length=200, blank=True, default="")

    secretary_ru = models.CharField(_("секретарь"), max_length=200, default="")
    secretary_en = models.CharField(max_length=200, blank=True, default="")
    secretary_title_ru = models.CharField(_("звание секретаря"), max_length=200, default="")
    secretary_title_en = models.CharField(max_length=200, blank=True, default="")

    email = models.EmailField(_("почта семинара"), default="seminar@cosmos.ru")
    address_ru = models.CharField(_("адрес"), max_length=300, default="")
    address_en = models.CharField(max_length=300, blank=True, default="")

    # Дефолт для новых семинаров: за сколько часов до начала закрывать приём заявок.
    # Бизнес-правило «до 18:00 за два дня» меняется, поэтому не хардкодим.
    registration_lead_hours = models.PositiveSmallIntegerField(
        _("закрывать заявки за N часов до начала"), default=48
    )
    # Пропуск не гражданину РФ бюро оформляет дольше, чем гражданину, поэтому
    # очные заявки от иностранцев закрываются раньше остальных. Срок такой же
    # настраиваемый: правила бюро пропусков меняются.
    foreign_extra_lead_hours = models.PositiveSmallIntegerField(
        _("закрывать очные заявки не граждан РФ на N часов раньше"),
        default=48,
        help_text=_("Считается от общего срока приёма заявок. Только для очного участия."),
    )

    notify_on_registration = models.BooleanField(_("письмо о каждой заявке"), default=True)
    notify_email = models.EmailField(_("куда слать уведомления"), blank=True, default="")

    # Согласие на обработку ПД — единственное, что заказчик отдаёт документом,
    # а не текстом: формулировку утверждают на бумаге, и на сайте она должна
    # лежать ровно тем файлом, который утверждён. Ссылка на чужой сайт тоже
    # не годится — документ обязан открываться со своего адреса.
    privacy_policy_file = models.FileField(
        _("документ согласия на обработку ПД"),
        upload_to="policy/",
        blank=True,
        validators=[FileExtensionValidator(["pdf"])],
        help_text=_(
            "PDF. Открывается по ссылке «Обработка персональных данных» "
            "в подвале и в форме записи. Пока файла нет, на странице стоит заглушка."
        ),
    )

    online_link_captcha = models.BooleanField(
        _("проверять посетителя перед показом ссылки на трансляцию"),
        default=True,
        help_text=_(
            "Ссылка на видеоконференцию отдаётся после ввода кода с картинки. "
            "Пройденная проверка помнится два часа."
        ),
    )

    retention_months = models.PositiveSmallIntegerField(
        _("хранить заявки, месяцев после заседания"),
        default=6,
        help_text=_("По истечении срока заявки удаляет команда purge_registrations."),
    )

    CACHE_KEY = "site_settings"

    class Meta:
        verbose_name = _("настройки сайта")
        verbose_name_plural = _("настройки сайта")

    def __str__(self):
        return "Настройки сайта"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)
        _request_local.value = None

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Настройки сайта удалять нельзя.")

    @classmethod
    def load(cls) -> "SiteSettings":
        cached = getattr(_request_local, "value", None)
        if cached is not None:
            return cached

        obj = cache.get(cls.CACHE_KEY)
        if obj is None:
            obj, _created = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, obj, 300)

        _request_local.value = obj
        return obj


@receiver(request_started)
def _drop_request_cache(**kwargs):
    """Сбросить памятку на границе запроса, чтобы правки настроек подхватывались."""
    _request_local.value = None
