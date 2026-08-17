"""Формы панели управления.

Главное требование ТЗ к этому разделу — удобство с телефона. Отсюда решения:
нативные типы полей (date/time/datetime-local вызывают системные пикеры),
никаких мультиселектов и виджетов-автодополнений, докладчики вводятся
построчно текстом.
"""

from typing import ClassVar

from django import forms
from django.forms import inlineformset_factory
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.models import SiteSettings
from apps.seminars.models import Material, Seminar, Speaker, Talk, TalkSpeaker

SPEAKER_SEPARATOR = "—"


class DateInput(forms.DateInput):
    input_type = "date"


class TimeInput(forms.TimeInput):
    input_type = "time"


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"
    # Без обрезки до минут браузер не принимает значение с секундами.
    format = "%Y-%m-%dT%H:%M"


class SeminarForm(forms.ModelForm):
    class Meta:
        model = Seminar
        fields: ClassVar[list[str]] = [
            "date",
            "start_time",
            "topic",
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
        # Иначе Django подставляет свою англоязычную заглушку: строка новая
        # и в его русский перевод ещё не попала.
        self.fields["topic"].empty_label = _("— выберите тематику —")
        # Topic.__str__ всегда отдаёт name_ru, и на английской панели список
        # тематик оставался русским под уже переведённой заглушкой.
        self.fields["topic"].label_from_instance = lambda topic: topic.tr("name")
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
