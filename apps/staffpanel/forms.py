"""Формы панели управления.

Главное требование ТЗ к этому разделу — удобство с телефона. Отсюда решения:
нативные типы полей (date/time/datetime-local вызывают системные пикеры),
никаких мультиселектов и виджетов-автодополнений, докладчики вводятся
построчно текстом.
"""

from typing import ClassVar

from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.forms import BaseFormSet, inlineformset_factory
from django.utils.html import format_html, format_html_join
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.models import SiteSettings
from apps.seminars.models import Material, Seminar, Speaker, Talk, TalkSpeaker, Topic

SPEAKER_SEPARATOR = "—"
PHOTO_PREFIX = "photo_"


class IsoValueMixin:
    """Печатать значение по ISO, как того требуют браузерные пикеры.

    По умолчанию Django форматирует его по русской локали («17.08.2026»),
    а <input type="date"> принимает только «2026-08-17» и на всё остальное
    молча показывает пустое поле — при правке заседания даты пропадали.

    Формат задаётся аргументом конструктора, а не полем класса: базовый
    DateTimeBaseInput.__init__ безусловно присваивает self.format, и атрибут
    класса до вывода не доживает.

    Разбор ввода от этого не страдает: ISO есть в *_INPUT_FORMATS обеих локалей.
    """

    iso_format = ""

    def __init__(self, attrs=None, format=None):
        super().__init__(attrs, format or self.iso_format)


class DateInput(IsoValueMixin, forms.DateInput):
    input_type = "date"
    iso_format = "%Y-%m-%d"


class TimeInput(IsoValueMixin, forms.TimeInput):
    input_type = "time"
    # Без обрезки до минут браузер не принимает значение с секундами.
    iso_format = "%H:%M"


class DateTimeLocalInput(IsoValueMixin, forms.DateTimeInput):
    input_type = "datetime-local"
    iso_format = "%Y-%m-%dT%H:%M"


class DatalistInput(forms.TextInput):
    """Свободный ввод с подсказкой уже заведённых значений.

    Нативный <datalist> вместо скрипта-автодополнения: браузер сам фильтрует
    подсказки по набранному, это работает с телефонной клавиатуры и без
    JavaScript, а новое значение вводится тем же полем.
    """

    def __init__(self, list_id: str, attrs=None):
        # autocomplete off — иначе поверх подсказок браузер покажет ещё и
        # собственную историю ввода, и список задваивается.
        super().__init__({"list": list_id, "autocomplete": "off"} | (attrs or {}))
        self.list_id = list_id
        self.options: list[str] = []

    def render(self, name, value, attrs=None, renderer=None):
        return format_html(
            '{}<datalist id="{}">{}</datalist>',
            super().render(name, value, attrs, renderer),
            self.list_id,
            format_html_join("", '<option value="{}"></option>', ((o,) for o in self.options)),
        )


def error_summary(*parts: forms.BaseForm | BaseFormSet) -> list[str]:
    """Ошибки формы и вложенных формсетов одним списком — для сводки сверху.

    Форма заседания длинная, и на телефоне подсвеченное поле где-то в её
    середине остаётся незамеченным: человек видит только то, что страница
    перезагрузилась и ничего не сохранилось.
    """
    found: list[str] = []
    for part in parts:
        inner = [part]
        if isinstance(part, BaseFormSet):
            found += [str(error) for error in part.non_form_errors()]
            inner = part.forms
        for form in inner:
            for name, errors in form.errors.items():
                field = form.fields.get(name)
                label = str(field.label) if field and field.label else ""
                prefix = f"{label[:1].upper()}{label[1:]}: " if label else ""
                found += [f"{prefix}{error}" for error in errors]
    # Одинаковые ошибки в соседних докладах в сводке ни к чему: какие именно
    # строки не заполнены, видно по подсветке полей.
    return list(dict.fromkeys(found))


class SeminarForm(forms.ModelForm):
    # Не в Meta.fields, а отдельным полем: в базе это связь, а в панели —
    # строка. Тематика подставляется в заседание уже в save(), когда форма
    # целиком прошла проверку, — иначе опечатка в соседнем поле оставляла бы
    # в справочнике только что заведённую рубрику.
    topic = forms.CharField(
        label=_("тематика"),
        max_length=Topic._meta.get_field("name_ru").max_length,
        help_text=_(
            "Выберите из списка или впишите новую — она будет заведена. "
            "Тематика, у которой не осталось заседаний, удаляется сама."
        ),
    )

    class Meta:
        model = Seminar
        fields: ClassVar[list[str]] = [
            "date",
            "start_time",
            "title_ru",
            "title_en",
            "abstract_ru",
            "abstract_en",
            "place_ru",
            "place_en",
            "seminar_format",
            "online_url",
            "pass_required",
            "registration_closes_at",
            "status",
            "poster",
        ]
        widgets: ClassVar[dict] = {
            "date": DateInput(),
            "start_time": TimeInput(),
            "registration_closes_at": DateTimeLocalInput(),
            "title_ru": forms.Textarea(attrs={"rows": 2}),
            "title_en": forms.Textarea(attrs={"rows": 2}),
            "abstract_ru": forms.Textarea(attrs={"rows": 5}),
            "abstract_en": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title_en"].required = False
        self.fields["place_ru"].required = False

        widget = DatalistInput("topic-options")
        # Подсказки на языке панели: Topic.__str__ всегда отдаёт name_ru, и на
        # английской панели список тематик оставался бы русским.
        widget.options = [topic.tr("name") for topic in Topic.objects.all()]
        self.fields["topic"].widget = widget
        if self.instance.topic_id:
            self.initial["topic"] = self.instance.topic.tr("name")

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                continue
            field.widget.attrs.setdefault("class", "field")

    def clean_topic(self) -> str:
        return " ".join(self.cleaned_data["topic"].split())

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("seminar_format") == Seminar.Format.ONLINE and cleaned.get("pass_required"):
            # Пропуск в институт для чисто онлайнового заседания бессмыслен
            # и вводит участников в заблуждение.
            self.add_error("pass_required", _("Для онлайн-заседания пропуск не нужен."))
        return cleaned

    def save(self, commit=True):
        seminar = super().save(commit=False)
        previous_topic_id = seminar.topic_id
        seminar.topic = Topic.by_name(self.cleaned_data["topic"]) or Topic.create_named(
            self.cleaned_data["topic"]
        )
        if not seminar.slug:
            seminar.slug = self._build_slug(seminar)
        if commit:
            seminar.save()
            if previous_topic_id and previous_topic_id != seminar.topic_id:
                self._forget_unused_topic(previous_topic_id)
        return seminar

    @staticmethod
    def _forget_unused_topic(topic_id: int) -> None:
        """Убрать тематику, у которой после правки не осталось заседаний.

        Справочника рубрик в панели нет, и опечатка в названии заводит новую
        тематику. Без уборки исправленный вариант остался бы в подсказках
        навсегда, а удалить его было бы нечем.
        """
        Topic.objects.filter(pk=topic_id, seminars__isnull=True).delete()

    @staticmethod
    def _build_slug(seminar: Seminar) -> str:
        base = f"{seminar.date:%Y-%m-%d}-{slugify(seminar.title_ru)[:120] or 'seminar'}"
        slug, n = base, 2
        while Seminar.objects.filter(slug=slug).exclude(pk=seminar.pk).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug


class TalkForm(forms.ModelForm):
    """Доклад вместе с докладчиками.

    Докладчики вводятся построчно («ФИО — организация»), а не выбираются
    из списка: на телефоне мультиселект по сотням людей неюзабелен, а
    секретарь всё равно печатает ФИО из письма. Совпадения по ФИО
    переиспользуют существующую запись, так что справочник не плодится.
    """

    speakers_raw = forms.CharField(
        label=_("Докладчики"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "field"}),
        help_text=_("По одному в строке: Фамилия Имя Отчество — должность, организация"),
    )

    class Meta:
        model = Talk
        fields: ClassVar[list[str]] = ["title_ru", "title_en", "abstract_ru"]
        widgets: ClassVar[dict] = {
            "title_ru": forms.Textarea(attrs={"rows": 2, "class": "field"}),
            "title_en": forms.Textarea(attrs={"rows": 2, "class": "field"}),
            "abstract_ru": forms.Textarea(attrs={"rows": 3, "class": "field"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title_en"].required = False
        if self.instance.pk:
            self.fields["speakers_raw"].initial = self._dump_speakers(self.instance)
            self._add_photo_fields()

    def _add_photo_fields(self) -> None:
        """По полю на каждого уже сохранённого докладчика.

        Привязать фотографию к строке текста нельзя: пока доклад не сохранён,
        докладчика ещё нет. Поэтому поля появляются после сохранения — по
        одному на имя, чтобы не гадать, чьё это фото.
        """
        for speaker in self.instance.ordered_speakers:
            self.fields[f"{PHOTO_PREFIX}{speaker.pk}"] = forms.ImageField(
                label=_("Фото: %s") % speaker.full_name_ru,
                required=False,
                initial=speaker.photo,
                help_text=_("Хранится у докладчика — появится на всех его заседаниях."),
            )

    @property
    def photo_fields(self) -> list[forms.BoundField]:
        return [self[name] for name in self.fields if name.startswith(PHOTO_PREFIX)]

    @staticmethod
    def _dump_speakers(talk: Talk) -> str:
        lines = []
        for speaker in talk.ordered_speakers:
            if speaker.affiliation_ru:
                lines.append(f"{speaker.full_name_ru} {SPEAKER_SEPARATOR} {speaker.affiliation_ru}")
            else:
                lines.append(speaker.full_name_ru)
        return "\n".join(lines)

    def clean_speakers_raw(self) -> list[tuple[str, str]]:
        parsed: list[tuple[str, str]] = []
        for line in self.cleaned_data["speakers_raw"].splitlines():
            line = line.strip()
            if not line:
                continue
            # Принимаем и длинное тире, и дефис: с телефона удобнее второе.
            for sep in (SPEAKER_SEPARATOR, " - "):
                if sep in line:
                    name, affiliation = line.split(sep, 1)
                    break
            else:
                name, affiliation = line, ""
            name = " ".join(name.split())
            if len(name) < 3:
                raise forms.ValidationError(_("Слишком короткое имя докладчика: «%s»") % line)
            parsed.append((name, " ".join(affiliation.split())))
        return parsed

    def save(self, commit=True):
        talk = super().save(commit=commit)
        if commit:
            self.sync_speakers(talk)
        return talk

    def sync_speakers(self, talk: Talk) -> None:
        parsed = self.cleaned_data.get("speakers_raw") or []
        talk.speaker_links.all().delete()
        for order, (name, affiliation) in enumerate(parsed):
            speaker, created = Speaker.objects.get_or_create(
                full_name_ru=name, defaults={"affiliation_ru": affiliation}
            )
            # Существующему докладчику аффилиацию не перетираем: у него
            # она может быть полнее. Заполняем, только если пусто.
            if not created and affiliation and not speaker.affiliation_ru:
                speaker.affiliation_ru = affiliation
                speaker.save(update_fields=["affiliation_ru"])
            TalkSpeaker.objects.create(talk=talk, speaker=speaker, order=order)

    def save_photos(self) -> None:
        """Разложить загруженные фотографии по докладчикам.

        Нетронутое поле отдаёт прежний файл, и переписывать его нельзя —
        снимок с диска исчез бы. Значение False ставит галочка «очистить».
        """
        for name, value in self.cleaned_data.items():
            if not name.startswith(PHOTO_PREFIX):
                continue
            if value is not False and not isinstance(value, UploadedFile):
                continue
            speaker = Speaker.objects.filter(pk=name.removeprefix(PHOTO_PREFIX)).first()
            if speaker is None:
                continue
            # Прежний файл иначе остаётся в media/ навсегда: имя в базе
            # сменится, а сам снимок никто не удалит.
            speaker.photo.delete(save=False)
            speaker.photo = value or ""
            speaker.save(update_fields=["photo"])


class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields: ClassVar[list[str]] = ["kind", "title_ru", "file", "url"]
        widgets: ClassVar[dict] = {
            "title_ru": forms.TextInput(attrs={"class": "field"}),
            "url": forms.URLInput(attrs={"class": "field"}),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("file") and not cleaned.get("url"):
            raise forms.ValidationError(_("Приложите файл или укажите ссылку."))
        return cleaned


TalkFormSet = inlineformset_factory(
    Seminar, Talk, form=TalkForm, extra=1, can_delete=True, min_num=0, validate_min=False
)

MaterialFormSet = inlineformset_factory(
    Seminar, Material, form=MaterialForm, extra=1, can_delete=True, fk_name="seminar"
)


class SiteSettingsForm(forms.ModelForm):
    """Тексты сайта, включая согласие на обработку ПД.

    Согласие обязано редактироваться без правки кода: его формулировку
    утверждает заказчик, а не разработчик.
    """

    class Meta:
        model = SiteSettings
        exclude: ClassVar[list[str]] = []
        widgets: ClassVar[dict] = {
            "privacy_policy_text": forms.Textarea(attrs={"rows": 10, "class": "field"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "field")
