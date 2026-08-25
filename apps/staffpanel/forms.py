"""Формы панели управления.

Главное требование ТЗ к этому разделу — удобство с телефона. Отсюда решения:
нативные типы полей (date/time/datetime-local вызывают системные пикеры),
никаких мультиселектов и виджетов-автодополнений, докладчики вводятся
построчно текстом.
"""

from typing import ClassVar

from django import forms
from django.forms import BaseFormSet, inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.core.models import SiteSettings
from apps.seminars.models import Material, Seminar, Speaker, Talk, TalkSpeaker, slugify_ru

SPEAKER_SEPARATOR = "—"


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
    class Meta:
        model = Seminar
        fields: ClassVar[list[str]] = [
            "date",
            "start_time",
            "abstract_ru",
            "abstract_en",
            "place_ru",
            "place_en",
            "seminar_format",
            "online_url",
            "pass_required",
            "registration_closes_at",
            "status",
        ]
        widgets: ClassVar[dict] = {
            "date": DateInput(),
            "start_time": TimeInput(),
            "registration_closes_at": DateTimeLocalInput(),
            "abstract_ru": forms.Textarea(attrs={"rows": 5}),
            "abstract_en": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["place_ru"].required = False

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                continue
            field.widget.attrs.setdefault("class", "field")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("seminar_format") == Seminar.Format.ONLINE and cleaned.get("pass_required"):
            # Пропуск в институт для чисто онлайнового заседания бессмыслен
            # и вводит участников в заблуждение.
            self.add_error("pass_required", _("Для онлайн-заседания пропуск не нужен."))
        return cleaned

    def save(self, commit=True):
        seminar = super().save(commit=False)
        if not seminar.slug:
            seminar.slug = self._build_slug(seminar)
        if commit:
            seminar.save()
        return seminar

    @staticmethod
    def _build_slug(seminar: Seminar, label: str = "") -> str:
        """Адрес заседания: дата и тема первого доклада.

        Собственной темы у заседания нет, поэтому `label` — это тема доклада.
        Русское название транслитерируется: без этого slugify() выбросил бы
        кириллицу целиком и от адреса осталась бы одна дата.

        Форма сохраняет заседание раньше докладов, поэтому в момент вызова из
        `save()` темы ещё нет — адрес там получается по дате, а представление
        пересобирает его сразу после сохранения докладов.
        """
        base = f"{seminar.date:%Y-%m-%d}"
        if label:
            base = f"{base}-{slugify_ru(label)[:120]}".rstrip("-")
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


class MaterialForm(forms.ModelForm):
    """Материал доклада: файлом, ссылкой или и тем и другим.

    Материалы висят на докладе, а не на заседании: у заседания из внешнего
    только ссылка на видеоконференцию.
    """

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

MaterialFormSet = inlineformset_factory(Talk, Material, form=MaterialForm, extra=1, can_delete=True)


def material_prefix(talk: Talk) -> str:
    """Свой префикс на доклад: формсеты материалов идут отдельными группами.

    Вкладывать их внутрь формы доклада нельзя — скрипт добавления строк ищет
    management_form в ближайшем fieldset и на вложенной группе брал бы чужой.
    """
    return f"materials-{talk.pk}"


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
