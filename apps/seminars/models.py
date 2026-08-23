from datetime import datetime, time, timedelta
from typing import ClassVar

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.i18n import TranslatedMixin

RUSSIAN_SEARCH_CONFIG = "russian"


class Speaker(TranslatedMixin, models.Model):
    """Докладчик. Отдельная сущность, потому что люди выступают повторно."""

    full_name_ru = models.CharField(_("ФИО"), max_length=200)
    full_name_en = models.CharField(max_length=200, blank=True, default="")
    affiliation_ru = models.CharField(
        _("должность и организация"), max_length=400, blank=True, default=""
    )
    affiliation_en = models.CharField(max_length=400, blank=True, default="")

    class Meta:
        verbose_name = _("докладчик")
        verbose_name_plural = _("докладчики")
        ordering: ClassVar[list[str]] = ["full_name_ru"]

    def __str__(self):
        return self.full_name_ru


class SeminarQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Seminar.Status.PUBLISHED)

    def upcoming(self):
        """Предстоящие: заседание считается предстоящим весь свой день."""
        return (
            self.published().filter(date__gte=timezone.localdate()).order_by("date", "start_time")
        )

    def archive(self):
        return self.published().filter(date__lt=timezone.localdate()).order_by("-date")

    def visible_to(self, user):
        """Сотрудники видят черновики и скрытые, остальные — только опубликованные."""
        if user is not None and user.is_authenticated and user.is_staff:
            return self
        return self.published()

    def with_related(self):
        """Доклады и докладчики — минимум для любого списка."""
        return self.prefetch_related("talks__speaker_links__speaker")

    def with_materials(self):
        """Дополнительно материалы. Главной они не нужны — не грузим их зря."""
        return self.prefetch_related("materials", "talks__materials")


class Seminar(TranslatedMixin, models.Model):
    """Заседание семинара. На одном заседании бывает несколько докладов."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Черновик")
        PUBLISHED = "published", _("Опубликован")
        HIDDEN = "hidden", _("Скрыт")

    class Format(models.TextChoices):
        ONSITE = "onsite", _("Только очно")
        ONLINE = "online", _("Только онлайн")
        HYBRID = "hybrid", _("Очно и онлайн")

    slug = models.SlugField(_("адрес"), max_length=220, unique=True)
    date = models.DateField(_("дата"))
    start_time = models.TimeField(_("время начала"), default=time(11, 0))

    abstract_ru = models.TextField(_("аннотация"), blank=True, default="")
    abstract_en = models.TextField(blank=True, default="")

    place_ru = models.CharField(_("место"), max_length=300, blank=True, default="")
    place_en = models.CharField(max_length=300, blank=True, default="")
    seminar_format = models.CharField(
        _("формат"), max_length=10, choices=Format.choices, default=Format.HYBRID
    )
    # 200 символов по умолчанию не хватает: ссылки на конференции носят
    # одноразовые токены, а в адресах файлов старого сайта лежит кириллица
    # в процентном кодировании — один русский символ занимает 9 знаков, и
    # самая длинная ссылка в архиве вытянула 771. Отсюда запас до 1000.
    online_url = models.URLField(
        _("ссылка на видеоконференцию"), max_length=1000, blank=True, default=""
    )

    status = models.CharField(
        _("статус"), max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    pass_required = models.BooleanField(_("нужен пропуск"), default=True)
    registration_closes_at = models.DateTimeField(
        _("приём заявок до"),
        null=True,
        blank=True,
        help_text=_("Если не задано, считается по умолчанию из настроек сайта."),
    )

    # Денормализованный текст для полнотекстового поиска: аннотация, доклады
    # и докладчики на обоих языках. Пересобирается в rebuild_search_text().
    search_text = models.TextField(editable=False, blank=True, default="")

    created_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SeminarQuerySet.as_manager()

    class Meta:
        verbose_name = _("заседание")
        verbose_name_plural = _("заседания")
        ordering: ClassVar[list[str]] = ["-date"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "-date"]),
            # Функциональный GIN по tsvector: поиск с русской морфологией
            # («турбулентности» находит «турбулентность»), чего icontains не умеет.
            GinIndex(
                SearchVector("search_text", config=RUSSIAN_SEARCH_CONFIG),
                name="seminar_search_gin",
            ),
        ]

    def __str__(self):
        return f"{self.date:%d.%m.%Y} — {self.label[:60]}"

    def save(self, *args, **kwargs):
        self.search_text = self.rebuild_search_text(save=False)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("seminars:detail", kwargs={"slug": self.slug})

    # --- Доклады -------------------------------------------------------------
    # Собственной темы у заседания нет: заседание — это один или несколько
    # докладов, и в заголовке идёт тема первого. Так же устроен и старый сайт.

    @property
    def lead_talk(self) -> "Talk | None":
        """Первый доклад. Через iter(), чтобы не терять prefetch лишним срезом."""
        return next(iter(self.talks.all()), None)

    @property
    def other_talks(self) -> list["Talk"]:
        return list(self.talks.all())[1:]

    @property
    def label(self) -> str:
        """Название заседания для служебных мест: списка панели, писем, логов."""
        talk = self.lead_talk
        return talk.title_ru if talk else str(_("Заседание без докладов"))

    # --- Производные величины ------------------------------------------------
    # Ничего из этого не хранится в базе: «прошло / не прошло» и «регистрация
    # открыта» вычисляются от даты. Поэтому нет ни фоновой задачи архивирования,
    # ни риска, что флаг разъедется с реальностью.

    @property
    def starts_at(self) -> datetime:
        naive = datetime.combine(self.date, self.start_time)
        return timezone.make_aware(naive, timezone.get_current_timezone())

    @property
    def is_past(self) -> bool:
        return self.date < timezone.localdate()

    @property
    def is_archived(self) -> bool:
        return self.is_past and self.status == self.Status.PUBLISHED

    @property
    def registration_deadline(self) -> datetime:
        if self.registration_closes_at:
            return self.registration_closes_at
        from apps.core.models import SiteSettings

        return self.starts_at - timedelta(hours=SiteSettings.load().registration_lead_hours)

    @property
    def registration_open(self) -> bool:
        return (
            self.status == self.Status.PUBLISHED
            and not self.is_past
            and timezone.now() < self.registration_deadline
        )

    @property
    def allows_onsite(self) -> bool:
        return self.seminar_format in (self.Format.ONSITE, self.Format.HYBRID)

    @property
    def allows_online(self) -> bool:
        return self.seminar_format in (self.Format.ONLINE, self.Format.HYBRID)

    # --- Поиск ---------------------------------------------------------------

    def rebuild_search_text(self, *, save: bool = True) -> str:
        parts = [
            self.abstract_ru,
            self.abstract_en,
        ]
        if self.pk:
            for talk in self.talks.prefetch_related("speakers"):
                parts += [talk.title_ru, talk.title_en]
                for speaker in talk.speakers.all():
                    parts += [
                        speaker.full_name_ru,
                        speaker.full_name_en,
                        speaker.affiliation_ru,
                    ]
        text = " ".join(p for p in parts if p)
        if save and text != self.search_text:
            self.search_text = text
            Seminar.objects.filter(pk=self.pk).update(search_text=text)
        return text


class Talk(TranslatedMixin, models.Model):
    """Доклад в рамках заседания."""

    seminar = models.ForeignKey(
        Seminar, verbose_name=_("заседание"), on_delete=models.CASCADE, related_name="talks"
    )
    order = models.PositiveSmallIntegerField(_("порядок"), default=0)
    title_ru = models.CharField(_("название доклада"), max_length=500)
    title_en = models.CharField(max_length=500, blank=True, default="")
    abstract_ru = models.TextField(_("аннотация"), blank=True, default="")
    abstract_en = models.TextField(blank=True, default="")
    speakers = models.ManyToManyField(
        Speaker, through="TalkSpeaker", related_name="talks", verbose_name=_("докладчики")
    )

    class Meta:
        verbose_name = _("доклад")
        verbose_name_plural = _("доклады")
        ordering: ClassVar[list[str]] = ["order", "id"]

    def __str__(self):
        return self.title_ru[:80]

    @property
    def ordered_speakers(self) -> list[Speaker]:
        """Докладчики в заданном порядке.

        Обращаться к `self.speakers.all()` нельзя: M2M сортирует по
        Meta.ordering модели Speaker (алфавит) и теряет порядок из
        связующей таблицы, а первый автор — не произвольный.
        """
        return [link.speaker for link in self.speaker_links.all()]


class TalkSpeaker(models.Model):
    """Связь доклада с докладчиком: у одного доклада бывает несколько авторов."""

    talk = models.ForeignKey(Talk, on_delete=models.CASCADE, related_name="speaker_links")
    speaker = models.ForeignKey(Speaker, on_delete=models.PROTECT, related_name="talk_links")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering: ClassVar[list[str]] = ["order", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["talk", "speaker"], name="unique_talk_speaker")
        ]

    def __str__(self):
        return f"{self.speaker} → {self.talk}"


class Material(TranslatedMixin, models.Model):
    """Материал заседания: аннотация, презентация, видеозапись."""

    class Kind(models.TextChoices):
        ABSTRACT = "abstract", _("Аннотация")
        SLIDES = "slides", _("Презентация")
        VIDEO = "video", _("Видеозапись")
        OTHER = "other", _("Материал")

    seminar = models.ForeignKey(
        Seminar, verbose_name=_("заседание"), on_delete=models.CASCADE, related_name="materials"
    )
    talk = models.ForeignKey(
        Talk,
        verbose_name=_("доклад"),
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="materials",
        help_text=_("Пусто — материал относится ко всему заседанию."),
    )
    kind = models.CharField(_("тип"), max_length=10, choices=Kind.choices, default=Kind.ABSTRACT)
    title_ru = models.CharField(_("подпись"), max_length=200, blank=True, default="")
    title_en = models.CharField(max_length=200, blank=True, default="")
    file = models.FileField(_("файл"), upload_to="materials/%Y/", blank=True)
    url = models.URLField(_("ссылка"), max_length=1000, blank=True, default="")

    class Meta:
        verbose_name = _("материал")
        verbose_name_plural = _("материалы")
        ordering: ClassVar[list[str]] = ["kind", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # Материал без файла и без ссылки — пустая строка в интерфейсе.
            models.CheckConstraint(
                condition=~models.Q(file="") | ~models.Q(url=""),
                name="material_has_file_or_url",
            )
        ]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.seminar_id}"

    @property
    def href(self) -> str:
        """Куда ведёт материал.

        Свой файл отдаётся напрямую, чужая ссылка — через шлюз внешних ссылок:
        прямых внешних адресов в разметке сайта нет.
        """
        if self.file:
            return self.file.url
        return reverse("seminars:material_link", kwargs={"pk": self.pk})
