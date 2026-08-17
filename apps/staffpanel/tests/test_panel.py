"""Проверки панели управления."""

from datetime import datetime, time, timedelta
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.registrations.models import Registration
from apps.seminars.models import Seminar, Speaker, Topic
from apps.seminars.tests.factories import add_talk, make_seminar, make_topic
from apps.staffpanel.forms import PHOTO_PREFIX

pytestmark = pytest.mark.django_db


def image_upload(name: str = "photo.png") -> SimpleUploadedFile:
    """Настоящий PNG: ImageField проверяет содержимое, а не расширение."""
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


@pytest.fixture
def groups():
    call_command("setup_groups")


@pytest.fixture
def secretary(django_user_model, groups):
    from django.contrib.auth.models import Group

    user = django_user_model.objects.create_user(username="sec", password="pw", is_staff=True)
    user.groups.add(Group.objects.get(name="Секретарь семинара"))
    return user


@pytest.fixture
def chair(django_user_model, groups):
    from django.contrib.auth.models import Group

    user = django_user_model.objects.create_user(username="chair", password="pw", is_staff=True)
    user.groups.add(Group.objects.get(name="Руководитель семинара"))
    return user


@pytest.fixture
def as_secretary(client, secretary):
    client.force_login(secretary)
    return client


def make_registration(seminar, **kwargs) -> Registration:
    data = {
        "seminar": seminar,
        "full_name": "Иванов Иван Иванович",
        "organization": "МГУ",
        "position": "аспирант",
        "email": "ivanov@msu.ru",
        "consent_pd": True,
        "consent_at": timezone.now(),
    }
    return Registration.objects.create(**(data | kwargs))


# --- Доступ -------------------------------------------------------------------


PANEL_URLS = [
    ("staffpanel:seminar_list", {}),
    ("staffpanel:registrations", {}),
    ("staffpanel:settings", {}),
]


@pytest.mark.parametrize(("name", "kwargs"), PANEL_URLS)
def test_anonymous_is_sent_to_login(client, name, kwargs):
    response = client.get(reverse(name, kwargs=kwargs))

    assert response.status_code == 302
    assert reverse("staffpanel:login") in response["Location"]


@pytest.mark.parametrize(("name", "kwargs"), PANEL_URLS)
def test_plain_user_gets_403(client, django_user_model, name, kwargs):
    django_user_model.objects.create_user(username="guest", password="pw")
    client.force_login(django_user_model.objects.get(username="guest"))

    assert client.get(reverse(name, kwargs=kwargs)).status_code == 403


def test_secretary_cannot_edit_site_settings(as_secretary):
    """Формулировку согласия на ПД меняет руководитель, а не любой сотрудник."""
    assert as_secretary.get(reverse("staffpanel:settings")).status_code == 403


def test_chair_can_edit_site_settings(client, chair):
    client.force_login(chair)

    assert client.get(reverse("staffpanel:settings")).status_code == 200


def test_secretary_can_manage_seminars(as_secretary):
    assert as_secretary.get(reverse("staffpanel:seminar_create")).status_code == 200
    assert as_secretary.get(reverse("staffpanel:registrations")).status_code == 200


# --- Список -------------------------------------------------------------------


def test_list_shows_all_statuses_including_drafts(as_secretary):
    topic = make_topic()
    make_seminar(
        timezone.localdate(),
        topic=topic,
        suffix="d",
        status=Seminar.Status.DRAFT,
        title_ru="Черновик заседания",
    )
    make_seminar(
        timezone.localdate(),
        topic=topic,
        suffix="h",
        status=Seminar.Status.HIDDEN,
        title_ru="Скрытое заседание",
    )

    content = as_secretary.get(reverse("staffpanel:seminar_list")).content.decode()

    assert "Черновик заседания" in content
    assert "Скрытое заседание" in content


def test_list_counts_registrations(as_secretary):
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    make_registration(seminar, email="a@example.org")
    make_registration(seminar, email="b@example.org")

    content = as_secretary.get(reverse("staffpanel:seminar_list")).content.decode()

    assert f'?seminar={seminar.pk}">2</a>' in content


# --- Создание и правка --------------------------------------------------------


def seminar_payload(topic: Topic | str, **overrides) -> dict:
    data = {
        "date": (timezone.localdate() + timedelta(days=20)).isoformat(),
        "start_time": "11:00",
        # Тематика вводится названием, а не выбирается из списка, поэтому
        # годится и название несуществующей — её заведёт сама форма.
        "topic": topic if isinstance(topic, str) else topic.name_ru,
        "title_ru": "Новое заседание про плазму",
        "title_en": "",
        "abstract_ru": "",
        "abstract_en": "",
        "place_ru": "ИКИ РАН",
        "place_en": "",
        "seminar_format": Seminar.Format.HYBRID,
        "online_url": "",
        "status": Seminar.Status.DRAFT,
        "registration_closes_at": "",
        "talks-TOTAL_FORMS": "1",
        "talks-INITIAL_FORMS": "0",
        "talks-MIN_NUM_FORMS": "0",
        "talks-MAX_NUM_FORMS": "1000",
        "talks-0-title_ru": "Турбулентность солнечного ветра",
        "talks-0-title_en": "",
        "talks-0-abstract_ru": "",
        "talks-0-speakers_raw": "Смирнов Андрей Петрович — д. ф.-м. н., ИКИ РАН",
        "materials-TOTAL_FORMS": "0",
        "materials-INITIAL_FORMS": "0",
        "materials-MIN_NUM_FORMS": "0",
        "materials-MAX_NUM_FORMS": "1000",
    }
    return data | overrides


def test_create_seminar_with_talk_and_speaker(as_secretary):
    topic = make_topic()

    response = as_secretary.post(reverse("staffpanel:seminar_create"), seminar_payload(topic))

    assert response.status_code == 302
    seminar = Seminar.objects.get()
    assert seminar.slug, "slug должен проставляться автоматически"
    talk = seminar.talks.get()
    assert [s.full_name_ru for s in talk.ordered_speakers] == ["Смирнов Андрей Петрович"]
    assert Speaker.objects.get().affiliation_ru == "д. ф.-м. н., ИКИ РАН"


def test_speakers_are_reused_not_duplicated(as_secretary):
    """Один и тот же докладчик выступает годами — справочник плодиться не должен."""
    topic = make_topic()
    as_secretary.post(reverse("staffpanel:seminar_create"), seminar_payload(topic))
    as_secretary.post(
        reverse("staffpanel:seminar_create"),
        seminar_payload(topic, title_ru="Второе заседание"),
    )

    assert Speaker.objects.count() == 1
    assert Seminar.objects.count() == 2


def test_speaker_order_is_kept_from_input(as_secretary):
    topic = make_topic()
    payload = seminar_payload(
        topic,
        **{"talks-0-speakers_raw": "Чернецов Никита Севирович\nКавокин Кирилл Витальевич"},
    )

    as_secretary.post(reverse("staffpanel:seminar_create"), payload)

    talk = Seminar.objects.get().talks.get()
    assert [s.full_name_ru for s in talk.ordered_speakers] == [
        "Чернецов Никита Севирович",
        "Кавокин Кирилл Витальевич",
    ]


def test_new_seminar_feeds_search_index(as_secretary):
    """Доклад сохраняется после заседания — поисковый текст надо пересобрать."""
    topic = make_topic()

    as_secretary.post(reverse("staffpanel:seminar_create"), seminar_payload(topic))

    seminar = Seminar.objects.get()
    assert "Турбулентность солнечного ветра" in seminar.search_text
    assert "Смирнов Андрей Петрович" in seminar.search_text


def test_online_seminar_rejects_pass_requirement(as_secretary):
    topic = make_topic()
    payload = seminar_payload(topic, seminar_format=Seminar.Format.ONLINE, pass_required="on")

    response = as_secretary.post(reverse("staffpanel:seminar_create"), payload)

    assert response.status_code == 422
    assert Seminar.objects.count() == 0
    assert "пропуск не нужен" in response.content.decode()


def test_invalid_form_does_not_create_anything(as_secretary):
    topic = make_topic()

    response = as_secretary.post(
        reverse("staffpanel:seminar_create"), seminar_payload(topic, title_ru="")
    )

    assert response.status_code == 422
    assert Seminar.objects.count() == 0
    assert Speaker.objects.count() == 0, "докладчики не должны создаваться при откате"


def test_edit_form_prefills_date_and_time(as_secretary):
    """Русская локаль печатает «17.08.2026», а <input type="date"> ждёт ISO.

    Без явного формата поле при правке открывалось пустым, и заседание
    сохранялось без даты — точнее, не сохранялось вовсе.
    """
    seminar = make_seminar(
        timezone.localdate() + timedelta(days=20),
        start_time=time(15, 30),
        registration_closes_at=timezone.make_aware(
            datetime.combine(timezone.localdate() + timedelta(days=18), time(18, 0))
        ),
    )

    content = as_secretary.get(
        reverse("staffpanel:seminar_edit", kwargs={"pk": seminar.pk})
    ).content.decode()

    assert f'value="{seminar.date:%Y-%m-%d}"' in content
    assert 'value="15:30"' in content
    assert f'value="{seminar.date - timedelta(days=2):%Y-%m-%d}T18:00"' in content


# --- Сводка ошибок --------------------------------------------------------------


def test_invalid_form_lists_problems_above_the_form(as_secretary):
    topic = make_topic()

    response = as_secretary.post(
        reverse("staffpanel:seminar_create"), seminar_payload(topic, title_ru="", date="")
    )

    content = response.content.decode()
    assert "Не сохранено" in content
    assert "Дата: Обязательное поле." in response.context["errors"]
    assert "Тема заседания: Обязательное поле." in response.context["errors"]


def test_summary_collects_errors_from_talks_and_materials(as_secretary):
    """Ошибка во вложенной форме иначе видна только при прокрутке до неё."""
    topic = make_topic()
    payload = seminar_payload(
        topic,
        **{
            "talks-0-speakers_raw": "АБ",
            "materials-TOTAL_FORMS": "1",
            "materials-0-kind": "slides",
            "materials-0-title_ru": "Презентация",
            "materials-0-url": "",
        },
    )

    errors = as_secretary.post(reverse("staffpanel:seminar_create"), payload).context["errors"]

    assert "Докладчики: Слишком короткое имя докладчика: «АБ»" in errors
    assert "Приложите файл или укажите ссылку." in errors


def test_saved_form_has_no_summary(as_secretary):
    content = as_secretary.get(reverse("staffpanel:seminar_create")).content.decode()

    assert "formsummary" not in content


# --- Тематика -------------------------------------------------------------------


def test_topic_field_suggests_existing_topics(as_secretary):
    make_topic()

    content = as_secretary.get(reverse("staffpanel:seminar_create")).content.decode()

    assert '<datalist id="topic-options">' in content
    assert '<option value="Физика космической плазмы"></option>' in content


def test_known_topic_is_matched_by_name(as_secretary):
    topic = make_topic()

    as_secretary.post(
        reverse("staffpanel:seminar_create"),
        seminar_payload("  физика КОСМИЧЕСКОЙ плазмы "),
    )

    assert Topic.objects.count() == 1, "регистр и лишние пробелы не должны плодить рубрики"
    assert Seminar.objects.get().topic == topic


def test_unknown_topic_is_created_from_free_input(as_secretary):
    topic = make_topic()

    response = as_secretary.post(
        reverse("staffpanel:seminar_create"), seminar_payload("Космическая погода")
    )

    assert response.status_code == 302
    created = Topic.objects.get(name_ru="Космическая погода")
    assert created.slug == "kosmicheskaya-pogoda", "адрес нужен латиницей: slugify её не делает"
    assert created.short_ru == "Космическая погода"
    assert created.order > topic.order, "новая рубрика встаёт в конец списка"
    assert Seminar.objects.get().topic == created


def test_new_topic_is_not_created_when_form_is_invalid(as_secretary):
    """Опечатка в соседнем поле не должна оставлять рубрику в справочнике."""
    make_topic()

    as_secretary.post(
        reverse("staffpanel:seminar_create"),
        seminar_payload("Космическая погода", title_ru=""),
    )

    assert Topic.objects.count() == 1


def test_topic_left_without_seminars_is_dropped(as_secretary):
    """Иначе опечатку в названии нечем убрать: справочника рубрик в панели нет."""
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    mistyped = seminar.topic

    as_secretary.post(
        reverse("staffpanel:seminar_edit", kwargs={"pk": seminar.pk}),
        seminar_payload("Астробиология"),
    )

    assert not Topic.objects.filter(pk=mistyped.pk).exists()
    assert Seminar.objects.get(pk=seminar.pk).topic.name_ru == "Астробиология"


def test_topic_with_other_seminars_survives(as_secretary):
    topic = make_topic()
    seminar = make_seminar(timezone.localdate() + timedelta(days=5), topic=topic, suffix="a")
    make_seminar(timezone.localdate() + timedelta(days=9), topic=topic, suffix="b")

    as_secretary.post(
        reverse("staffpanel:seminar_edit", kwargs={"pk": seminar.pk}),
        seminar_payload("Астробиология"),
    )

    assert Topic.objects.filter(pk=topic.pk).exists()


# --- Фотографии докладчиков -----------------------------------------------------


def talk_payload(talk, speaker, **extra) -> dict:
    """Правка заседания с одним уже сохранённым докладом."""
    return {
        "talks-INITIAL_FORMS": "1",
        "talks-0-id": talk.pk,
        "talks-0-title_ru": talk.title_ru,
        "talks-0-speakers_raw": f"{speaker.full_name_ru} — {speaker.affiliation_ru}",
    } | extra


def test_photo_fields_appear_only_for_saved_speakers(as_secretary):
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    talk = add_talk(seminar, "Доклад", [("Иванов Иван Иванович", "ИКИ РАН")])
    speaker = talk.ordered_speakers[0]

    edit = as_secretary.get(
        reverse("staffpanel:seminar_edit", kwargs={"pk": seminar.pk})
    ).content.decode()
    create = as_secretary.get(reverse("staffpanel:seminar_create")).content.decode()

    assert f'name="talks-0-{PHOTO_PREFIX}{speaker.pk}"' in edit
    assert "Фото: Иванов Иван Иванович" in edit
    assert PHOTO_PREFIX not in create, "докладчика ещё нет — привязывать фото не к чему"


def test_speaker_photo_is_uploaded(as_secretary):
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    talk = add_talk(seminar, "Доклад", [("Иванов Иван Иванович", "ИКИ РАН")])
    speaker = talk.ordered_speakers[0]
    payload = seminar_payload(
        seminar.topic,
        **talk_payload(talk, speaker, **{f"talks-0-{PHOTO_PREFIX}{speaker.pk}": image_upload()}),
    )

    response = as_secretary.post(
        reverse("staffpanel:seminar_edit", kwargs={"pk": seminar.pk}), payload
    )

    assert response.status_code == 302
    speaker.refresh_from_db()
    assert speaker.photo.name.startswith("speakers/")


def test_speaker_photo_survives_untouched_form(as_secretary):
    """Сохранение заседания без нового файла не должно стирать прежнее фото."""
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    talk = add_talk(seminar, "Доклад", [("Иванов Иван Иванович", "ИКИ РАН")])
    speaker = talk.ordered_speakers[0]
    speaker.photo = image_upload()
    speaker.save()
    was = speaker.photo.name

    as_secretary.post(
        reverse("staffpanel:seminar_edit", kwargs={"pk": seminar.pk}),
        seminar_payload(seminar.topic, **talk_payload(talk, speaker)),
    )

    speaker.refresh_from_db()
    assert speaker.photo.name == was
    assert speaker.photo.storage.exists(was), "файл не должен исчезнуть с диска"


def test_speaker_photo_can_be_cleared(as_secretary):
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    talk = add_talk(seminar, "Доклад", [("Иванов Иван Иванович", "ИКИ РАН")])
    speaker = talk.ordered_speakers[0]
    speaker.photo = image_upload()
    speaker.save()
    payload = seminar_payload(
        seminar.topic,
        **talk_payload(talk, speaker, **{f"talks-0-{PHOTO_PREFIX}{speaker.pk}-clear": "on"}),
    )

    as_secretary.post(reverse("staffpanel:seminar_edit", kwargs={"pk": seminar.pk}), payload)

    speaker.refresh_from_db()
    assert not speaker.photo


# --- Клонирование -------------------------------------------------------------


def test_clone_copies_talks_but_not_registrations(as_secretary):
    source = make_seminar(
        timezone.localdate() - timedelta(days=30), status=Seminar.Status.PUBLISHED
    )
    add_talk(source, "Прошлый доклад", [("Иванов И. И.", "ИКИ РАН")])
    make_registration(source)

    response = as_secretary.post(reverse("staffpanel:seminar_clone", kwargs={"pk": source.pk}))

    assert response.status_code == 302
    clone = Seminar.objects.exclude(pk=source.pk).get()
    assert clone.status == Seminar.Status.DRAFT, "копия не должна сразу уходить в публикацию"
    assert clone.talks.count() == 1
    assert clone.registrations.count() == 0, "чужие заявки копировать нельзя"
    assert Registration.objects.count() == 1


def test_clone_keeps_original_intact(as_secretary):
    source = make_seminar(timezone.localdate() - timedelta(days=30))
    add_talk(source, "Прошлый доклад", [("Иванов И. И.", "ИКИ РАН")])

    as_secretary.post(reverse("staffpanel:seminar_clone", kwargs={"pk": source.pk}))

    source.refresh_from_db()
    assert source.talks.count() == 1
    assert source.status == Seminar.Status.PUBLISHED


def test_clone_gets_unique_slug(as_secretary):
    source = make_seminar(timezone.localdate() - timedelta(days=30))

    as_secretary.post(reverse("staffpanel:seminar_clone", kwargs={"pk": source.pk}))

    slugs = list(Seminar.objects.values_list("slug", flat=True))
    assert len(slugs) == len(set(slugs))


# --- Показать/скрыть ----------------------------------------------------------


def test_toggle_hides_published_seminar(as_secretary):
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))

    as_secretary.post(reverse("staffpanel:seminar_toggle", kwargs={"pk": seminar.pk}))

    seminar.refresh_from_db()
    assert seminar.status == Seminar.Status.HIDDEN


def test_toggle_publishes_draft(as_secretary):
    seminar = make_seminar(timezone.localdate() + timedelta(days=5), status=Seminar.Status.DRAFT)

    as_secretary.post(reverse("staffpanel:seminar_toggle", kwargs={"pk": seminar.pk}))

    seminar.refresh_from_db()
    assert seminar.status == Seminar.Status.PUBLISHED


def test_toggle_ignores_foreign_referer(as_secretary):
    """Referer — не место для цели редиректа: иначе это открытый редирект."""
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))

    response = as_secretary.post(
        reverse("staffpanel:seminar_toggle", kwargs={"pk": seminar.pk}),
        HTTP_REFERER="https://evil.example/phish",
    )

    assert response["Location"] == reverse("staffpanel:seminar_list")


# --- Регистрации --------------------------------------------------------------


def test_registrations_filtered_by_seminar(as_secretary):
    topic = make_topic()
    first = make_seminar(timezone.localdate() + timedelta(days=5), topic=topic, suffix="a")
    second = make_seminar(timezone.localdate() + timedelta(days=9), topic=topic, suffix="b")
    make_registration(first, full_name="Первый Участник", email="one@example.org")
    make_registration(second, full_name="Второй Участник", email="two@example.org")

    content = as_secretary.get(
        reverse("staffpanel:registrations") + f"?seminar={first.pk}"
    ).content.decode()

    assert "Первый Участник" in content
    assert "Второй Участник" not in content


def test_registrations_search(as_secretary):
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    make_registration(seminar, full_name="Петрова Мария", email="petrova@izmiran.ru")
    make_registration(seminar, full_name="Сидоров Пётр", email="sidorov@cosmos.ru")

    content = as_secretary.get(
        reverse("staffpanel:registrations") + f"?seminar={seminar.pk}&q=izmiran"
    ).content.decode()

    assert "Петрова Мария" in content
    assert "Сидоров Пётр" not in content


def test_pass_status_can_be_updated(as_secretary):
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    registration = make_registration(seminar)

    as_secretary.post(
        reverse("staffpanel:pass_status", kwargs={"pk": registration.pk}),
        {"pass_status": Registration.PassStatus.ISSUED},
    )

    registration.refresh_from_db()
    assert registration.pass_status == Registration.PassStatus.ISSUED


def test_bogus_pass_status_is_ignored(as_secretary):
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    registration = make_registration(seminar, pass_status=Registration.PassStatus.PENDING)

    as_secretary.post(
        reverse("staffpanel:pass_status", kwargs={"pk": registration.pk}),
        {"pass_status": "уже оформлен, честное слово"},
    )

    registration.refresh_from_db()
    assert registration.pass_status == Registration.PassStatus.PENDING


# --- Выгрузка -----------------------------------------------------------------


def test_csv_opens_in_excel_without_mojibake(as_secretary):
    """BOM и точка с запятой — иначе Excel в русской локали ломает файл."""
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    make_registration(seminar, full_name="Петрова Мария Сергеевна", organization="ИЗМИРАН")

    response = as_secretary.get(
        reverse("staffpanel:registrations_export", kwargs={"fmt": "csv"}) + f"?seminar={seminar.pk}"
    )

    assert response.status_code == 200
    body = response.content
    assert body.startswith(b"\xef\xbb\xbf"), "нет BOM — Excel прочитает UTF-8 как cp1251"
    text = body.decode("utf-8-sig")
    assert ";" in text.splitlines()[0]
    assert "Петрова Мария Сергеевна" in text
    assert "ИЗМИРАН" in text


def test_csv_respects_active_filters(as_secretary):
    topic = make_topic()
    first = make_seminar(timezone.localdate() + timedelta(days=5), topic=topic, suffix="a")
    second = make_seminar(timezone.localdate() + timedelta(days=9), topic=topic, suffix="b")
    make_registration(first, full_name="Нужный Участник", email="one@example.org")
    make_registration(second, full_name="Лишний Участник", email="two@example.org")

    text = as_secretary.get(
        reverse("staffpanel:registrations_export", kwargs={"fmt": "csv"}) + f"?seminar={first.pk}"
    ).content.decode("utf-8-sig")

    assert "Нужный Участник" in text
    assert "Лишний Участник" not in text


def test_xlsx_export_is_a_real_workbook(as_secretary):
    from io import BytesIO

    from openpyxl import load_workbook

    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    make_registration(seminar, full_name="Петрова Мария Сергеевна")

    response = as_secretary.get(
        reverse("staffpanel:registrations_export", kwargs={"fmt": "xlsx"})
        + f"?seminar={seminar.pk}"
    )

    assert response.status_code == 200
    sheet = load_workbook(BytesIO(response.content)).active
    assert sheet.cell(row=1, column=1).value == "ФИО"
    assert sheet.cell(row=2, column=1).value == "Петрова Мария Сергеевна"


def test_export_filename_mentions_seminar_date(as_secretary):
    seminar = make_seminar(timezone.localdate() + timedelta(days=5))
    make_registration(seminar)

    response = as_secretary.get(
        reverse("staffpanel:registrations_export", kwargs={"fmt": "csv"}) + f"?seminar={seminar.pk}"
    )

    assert f"{seminar.date:%Y-%m-%d}" in response["Content-Disposition"]


def test_unknown_export_format_is_404(as_secretary):
    response = as_secretary.get(reverse("staffpanel:registrations_export", kwargs={"fmt": "pdf"}))

    assert response.status_code == 404


def test_export_is_closed_to_outsiders(client, django_user_model):
    django_user_model.objects.create_user(username="guest", password="pw")
    client.force_login(django_user_model.objects.get(username="guest"))

    response = client.get(reverse("staffpanel:registrations_export", kwargs={"fmt": "csv"}))

    assert response.status_code == 403
