from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.seminars.models import Seminar

from .factories import add_talk, make_seminar, make_topic

pytestmark = pytest.mark.django_db


# --- Публичные страницы -------------------------------------------------------


def test_home_shows_nearest_upcoming():
    topic = make_topic()
    make_seminar(
        timezone.localdate() + timedelta(days=30),
        topic=topic,
        suffix="far",
        title_ru="Далёкое заседание",
    )
    make_seminar(
        timezone.localdate() + timedelta(days=3),
        topic=topic,
        suffix="near",
        title_ru="Ближайшее заседание",
    )

    content = get(reverse("seminars:home"))

    assert "Ближайшее заседание" in content
    assert "Далёкое заседание" not in content


def test_home_survives_empty_database(client):
    """Свежая установка без единого заседания не должна падать."""
    response = client.get(reverse("seminars:home"))

    assert response.status_code == 200
    assert "уточняется" in response.content.decode()


def test_home_lists_recent_archive():
    topic = make_topic()
    make_seminar(
        timezone.localdate() - timedelta(days=5),
        topic=topic,
        suffix="p",
        title_ru="Прошедшее заседание",
    )

    assert "Прошедшее заседание" in get(reverse("seminars:home"))


# --- Афиша --------------------------------------------------------------------


def test_poster_is_shown_on_seminar_page():
    seminar = make_seminar(timezone.localdate() + timedelta(days=3), poster=png("afisha.png"))

    content = get(seminar.get_absolute_url())

    assert seminar.poster.url in content
    assert "Афиша" in content


def test_poster_is_shown_on_home_page():
    seminar = make_seminar(timezone.localdate() + timedelta(days=3), poster=png("afisha.png"))

    assert seminar.poster.url in get(reverse("seminars:home"))


def test_page_without_poster_has_no_broken_image():
    seminar = make_seminar(timezone.localdate() + timedelta(days=3))

    assert 'class="poster"' not in get(seminar.get_absolute_url())


# --- Доступ -------------------------------------------------------------------


@pytest.mark.parametrize("status", [Seminar.Status.DRAFT, Seminar.Status.HIDDEN])
def test_unpublished_seminar_is_404_for_anonymous(client, status):
    seminar = make_seminar(timezone.localdate(), status=status)

    assert client.get(seminar.get_absolute_url()).status_code == 404


@pytest.mark.parametrize("status", [Seminar.Status.DRAFT, Seminar.Status.HIDDEN])
def test_staff_can_preview_unpublished(client, django_user_model, status):
    django_user_model.objects.create_user(username="sec", password="pw", is_staff=True)
    client.login(username="sec", password="pw")
    seminar = make_seminar(timezone.localdate(), status=status)

    response = client.get(seminar.get_absolute_url())

    assert response.status_code == 200
    assert "Предпросмотр" in response.content.decode()


# --- Архив: поиск и фильтры ---------------------------------------------------


def test_search_matches_russian_word_forms():
    """Ради этого и взят полнотекстовый поиск PostgreSQL: icontains так не умеет.

    Слово ищется в другой словоформе и встречается только в названии доклада —
    значит, проверяются сразу морфология и попадание докладов в поисковый текст.
    """
    seminar = make_seminar(timezone.localdate() - timedelta(days=1), title_ru="Заседание про ветер")
    add_talk(seminar, "Турбулентность солнечного ветра", [("Смирнов А. П.", "ИКИ РАН")])

    content = get(reverse("seminars:archive") + "?q=турбулентности")

    assert "Заседание про ветер" in content


def test_search_finds_by_speaker_name():
    seminar = make_seminar(timezone.localdate() - timedelta(days=1), title_ru="Про нейтрино")
    add_talk(seminar, "Нейтрино высоких энергий", [("Ковалев Юрий Юрьевич", "MPIfR")])

    assert "Про нейтрино" in get(reverse("seminars:archive") + "?q=Ковалев")


def test_search_without_matches_shows_empty_state():
    make_seminar(timezone.localdate() - timedelta(days=1))

    content = get(reverse("seminars:archive") + "?q=цыганочкасвыходом")

    assert "Ничего не найдено" in content


def test_year_filter():
    topic = make_topic()
    make_seminar(
        timezone.localdate().replace(year=2024, month=3, day=1),
        topic=topic,
        suffix="a",
        title_ru="Заседание две тысячи двадцать четвёртого",
    )
    make_seminar(
        timezone.localdate() - timedelta(days=1),
        topic=topic,
        suffix="b",
        title_ru="Недавнее заседание",
    )

    content = get(reverse("seminars:archive") + "?year=2024")

    assert "Заседание две тысячи двадцать четвёртого" in content
    assert "Недавнее заседание" not in content


def test_topic_filter():
    plasma = make_topic("plasma")
    astro = make_topic("hea", name_ru="Астрофизика", short_ru="Астро")
    make_seminar(
        timezone.localdate() - timedelta(days=1),
        topic=plasma,
        suffix="p",
        title_ru="Плазменное заседание",
    )
    make_seminar(
        timezone.localdate() - timedelta(days=2),
        topic=astro,
        suffix="a",
        title_ru="Астрофизическое заседание",
    )

    content = get(reverse("seminars:archive") + "?topic=plasma")

    assert "Плазменное заседание" in content
    assert "Астрофизическое заседание" not in content


def test_archive_hides_upcoming():
    make_seminar(timezone.localdate() + timedelta(days=5), title_ru="Будущее заседание")

    assert "Будущее заседание" not in get(reverse("seminars:archive"))


# --- Производительность -------------------------------------------------------


def test_archive_does_not_scale_queries_with_rows(client, django_assert_max_num_queries):
    """Защита от N+1: 15 заседаний должны стоить столько же запросов, сколько 3."""
    topic = make_topic()
    for i in range(15):
        seminar = make_seminar(
            timezone.localdate() - timedelta(days=i + 1), topic=topic, suffix=str(i)
        )
        add_talk(seminar, f"Доклад {i}", [(f"Докладчик {i}", "ИКИ РАН")])

    # Прогрев: первый запрос наполняет кеш настроек сайта. Меряем
    # установившийся режим, иначе предел пришлось бы задирать и он
    # перестал бы ловить N+1.
    client.get(reverse("seminars:archive"))

    with django_assert_max_num_queries(13):
        client.get(reverse("seminars:archive"))


def test_home_does_not_load_materials(client, django_assert_max_num_queries):
    """Главная материалы не показывает, поэтому и грузить их не должна."""
    topic = make_topic()
    upcoming = make_seminar(timezone.localdate() + timedelta(days=3), topic=topic, suffix="up")
    add_talk(upcoming, "Ближайший доклад", [("Смирнов А. П.", "ИКИ РАН")])
    for i in range(5):
        past = make_seminar(
            timezone.localdate() - timedelta(days=i + 1), topic=topic, suffix=f"p{i}"
        )
        add_talk(past, f"Доклад {i}", [(f"Докладчик {i}", "ИКИ РАН")])

    client.get(reverse("seminars:home"))

    with django_assert_max_num_queries(12):
        client.get(reverse("seminars:home"))


# --- Служебное ----------------------------------------------------------------


def test_sitemap_lists_only_published(client):
    published = make_seminar(timezone.localdate() - timedelta(days=1), suffix="pub")
    hidden = make_seminar(
        timezone.localdate() - timedelta(days=2), suffix="hid", status=Seminar.Status.HIDDEN
    )

    content = client.get("/sitemap.xml").content.decode()

    assert published.slug in content
    assert hidden.slug not in content


def test_robots_blocks_admin_and_points_to_sitemap(client):
    content = client.get("/robots.txt").content.decode()

    assert "Disallow: /manage/" in content
    assert "sitemap.xml" in content


def test_english_page_falls_back_to_russian_content(client):
    """Без английского варианта содержимого показываем русский, а не пустоту."""
    make_seminar(timezone.localdate() + timedelta(days=3), title_ru="Только по-русски")

    content = client.get("/en/").content.decode()

    assert "Только по-русски" in content
    assert '<html lang="en">' in content


def test_english_uses_translation_when_present(client):
    make_seminar(
        timezone.localdate() + timedelta(days=3),
        title_ru="Русское название",
        title_en="English title",
    )

    content = client.get("/en/").content.decode()

    assert "English title" in content
    assert "Русское название" not in content


def test_english_page_translates_interface(client):
    """Обвязка страницы переводится, а не остаётся русской.

    Ловит пропавший каталог: без locale/en/LC_MESSAGES/django.mo gettext молча
    отдаёт msgid, то есть русский, и английская версия выглядит наполовину
    непереведённой.
    """
    content = client.get("/en/").content.decode()

    # Шапка: строка над заголовком, сам заголовок, навигация.
    assert "Space Research Institute of the Russian Academy of Sciences" in content
    assert "IKI RAS Scientific Seminar" in content
    assert "Институт космических исследований" not in content
    assert "Научный семинар ИКИ РАН" not in content

    # Подвал.
    assert "seminar chair" in content
    assert "seminar secretary" in content
    assert "Personal data processing" in content
    assert "руководитель семинара" not in content


def test_english_page_shows_english_site_settings(client):
    """Контакты в шапке и подвале берутся из *_en, а не жёстко из *_ru."""
    from apps.core.models import SiteSettings

    site = SiteSettings.load()
    site.chair_ru, site.chair_en = "Иванов И. И.", "I. I. Ivanov"
    site.secretary_ru, site.secretary_en = "Петрова А. А.", "A. A. Petrova"
    site.address_ru, site.address_en = "Москва, Профсоюзная 84/32", "84/32 Profsoyuznaya, Moscow"
    site.save()

    content = client.get("/en/").content.decode()

    assert "I. I. Ivanov" in content
    assert "A. A. Petrova" in content
    assert "84/32 Profsoyuznaya, Moscow" in content
    assert "Иванов И. И." not in content


def test_english_page_falls_back_to_russian_site_settings(client):
    """Незаполненный *_en не должен оставлять в подвале пустоту."""
    from apps.core.models import SiteSettings

    site = SiteSettings.load()
    site.chair_ru, site.chair_en = "Иванов И. И.", ""
    site.save()

    content = client.get("/en/").content.decode()

    assert "Иванов И. И." in content


# --- Вспомогательное ----------------------------------------------------------


def get(url: str) -> str:
    from django.test import Client

    return Client().get(url).content.decode()


def png(name: str) -> SimpleUploadedFile:
    """Настоящий PNG: ImageField проверяет содержимое, а не расширение."""
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")
