from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.seminars.models import Seminar

from .factories import add_talk, make_seminar

pytestmark = pytest.mark.django_db


# --- Публичные страницы -------------------------------------------------------


def test_home_shows_nearest_upcoming():
    far = make_seminar(timezone.localdate() + timedelta(days=30), suffix="far")
    add_talk(far, "Далёкий доклад", [("Иванов И. И.", "ИКИ РАН")])
    near = make_seminar(timezone.localdate() + timedelta(days=3), suffix="near")
    add_talk(near, "Ближайший доклад", [("Петров П. П.", "ИКИ РАН")])

    content = get(reverse("seminars:home"))

    assert "Ближайший доклад" in content
    assert "Далёкий доклад" not in content


def test_home_survives_empty_database(client):
    """Свежая установка без единого заседания не должна падать."""
    response = client.get(reverse("seminars:home"))

    assert response.status_code == 200
    assert "уточняется" in response.content.decode()


def test_home_lists_recent_archive():
    past = make_seminar(timezone.localdate() - timedelta(days=5), suffix="p")
    add_talk(past, "Прошедший доклад", [("Иванов И. И.", "ИКИ РАН")])

    assert "Прошедший доклад" in get(reverse("seminars:home"))


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
    seminar = make_seminar(timezone.localdate() - timedelta(days=1))
    add_talk(seminar, "Турбулентность солнечного ветра", [("Смирнов А. П.", "ИКИ РАН")])

    content = get(reverse("seminars:archive") + "?q=турбулентности")

    assert "Турбулентность солнечного ветра" in content


def test_search_finds_by_speaker_name():
    seminar = make_seminar(timezone.localdate() - timedelta(days=1))
    add_talk(seminar, "Нейтрино высоких энергий", [("Ковалев Юрий Юрьевич", "MPIfR")])

    assert "Нейтрино высоких энергий" in get(reverse("seminars:archive") + "?q=Ковалев")


def test_search_without_matches_shows_empty_state():
    make_seminar(timezone.localdate() - timedelta(days=1))

    content = get(reverse("seminars:archive") + "?q=цыганочкасвыходом")

    assert "Ничего не найдено" in content


def test_year_filter():
    old = make_seminar(timezone.localdate().replace(year=2024, month=3, day=1), suffix="a")
    add_talk(old, "Доклад две тысячи двадцать четвёртого", [("Иванов И. И.", "ИКИ РАН")])
    recent = make_seminar(timezone.localdate() - timedelta(days=1), suffix="b")
    add_talk(recent, "Недавний доклад", [("Петров П. П.", "ИКИ РАН")])

    content = get(reverse("seminars:archive") + "?year=2024")

    assert "Доклад две тысячи двадцать четвёртого" in content
    assert "Недавний доклад" not in content


def test_two_talks_on_one_day_get_a_block_each():
    """Общей темы у заседания нет: доклады не должны склеиваться в одну строку."""
    seminar = make_seminar(timezone.localdate() - timedelta(days=1))
    add_talk(seminar, "Корональная сейсмология", [("Рудерман Михаил", "ИКИ РАН")])
    add_talk(seminar, "Плазменно-пылевая система", [("Резниченко Юлия", "ИКИ РАН")])

    content = get(reverse("seminars:archive"))

    assert content.count('class="row"') == 2
    assert "Корональная сейсмология" in content
    assert "Плазменно-пылевая система" in content
    # Докладчик стоит при своём докладе, а не в общем списке на двоих.
    first = content.index("Корональная сейсмология")
    second = content.index("Плазменно-пылевая система")
    assert first < content.index("Рудерман Михаил") < second
    assert second < content.index("Резниченко Юлия")


def test_home_shows_the_upcoming_seminar_like_its_own_page():
    """Заказчику вид страницы заседания понравился больше — блок общий."""
    upcoming = make_seminar(timezone.localdate() + timedelta(days=3))
    add_talk(upcoming, "Ближайший доклад", [("Смирнов Андрей", "ИКИ РАН")])

    home = get(reverse("seminars:home"))
    page = get(upcoming.get_absolute_url())

    for marker in ('class="detail"', 'class="talk"', "Когда и где", "Ближайший доклад"):
        assert marker in home, marker
        assert marker in page, marker


def test_home_does_not_link_the_upcoming_seminar():
    """Заказчик просил убрать ссылку: по ней уходили и думали, что попали в архив."""
    upcoming = make_seminar(timezone.localdate() + timedelta(days=3))
    add_talk(upcoming, "Ближайший доклад", [("Смирнов Андрей", "ИКИ РАН")])

    content = get(reverse("seminars:home"))
    heading = content[content.index('class="page-title"') : content.index("</h2>")]

    assert upcoming.get_absolute_url() not in heading


def test_other_seminars_go_under_the_page_full_width():
    """Узкой колонки сбоку больше нет: архив добавляется снизу, как на главной."""
    past = make_seminar(timezone.localdate() - timedelta(days=30), suffix="past")
    add_talk(past, "Прошедший доклад", [("Иванов И. И.", "ИКИ РАН")])
    current = make_seminar(timezone.localdate() + timedelta(days=3), suffix="cur")
    add_talk(current, "Ближайший доклад", [("Петров П. П.", "ИКИ РАН")])

    content = get(current.get_absolute_url())

    assert "Другие заседания" in content
    assert "Прошедший доклад" in content
    # Блок идёт после карточки заседания, а не внутри её боковой колонки.
    assert content.index("</aside>") < content.index("Другие заседания")


def test_menu_collapses_into_a_burger_but_keeps_the_links():
    """На телефоне пункты уезжают в бургер, но остаются в разметке.

    Прячет их скрипт (класс .nav--js), поэтому без JavaScript меню никуда
    не девается — иначе на узком экране сайт остался бы без навигации.
    """
    content = get(reverse("seminars:home"))

    assert "data-nav-toggle" in content
    assert 'aria-controls="nav-links"' in content
    assert 'id="nav-links"' in content
    for item in ("Главная", "О семинаре", "Архив"):
        assert item in content, item


def test_talk_abstract_falls_back_to_russian_without_a_translation():
    seminar = make_seminar(timezone.localdate() + timedelta(days=3))
    add_talk(
        seminar,
        "Доклад",
        [("Иванов И. И.", "ИКИ РАН")],
        abstract_ru="Аннотация по-русски.",
    )

    assert "Аннотация по-русски." in get("/en" + seminar.get_absolute_url())


def test_english_page_shows_the_english_talk_abstract():
    seminar = make_seminar(timezone.localdate() + timedelta(days=3))
    add_talk(
        seminar,
        "Доклад",
        [("Иванов И. И.", "ИКИ РАН")],
        abstract_ru="Аннотация по-русски.",
        abstract_en="Abstract in English.",
    )

    content = get("/en" + seminar.get_absolute_url())

    assert "Abstract in English." in content
    assert "Аннотация по-русски." not in content


def test_talk_abstract_opens_in_a_full_width_sheet():
    """Заказчик просил прятать аннотацию доклада за кнопкой «Показать аннотацию».

    Прячет её скрипт: разметка отдаёт текст целиком, иначе без JavaScript
    аннотация пропала бы совсем. Проверяем зацепки, по которым он работает.
    """
    seminar = make_seminar(timezone.localdate() + timedelta(days=3))
    add_talk(
        seminar,
        "Турбулентность солнечного ветра",
        [("Смирнов Андрей", "ИКИ РАН")],
        abstract_ru="Очень длинная аннотация. " * 60,
    )

    content = get(seminar.get_absolute_url())

    assert "Очень длинная аннотация." in content, "без JavaScript текст должен остаться"
    assert "data-longtext-hide" in content, "аннотацию доклада прячем целиком"
    assert 'data-longtext-title="Турбулентность солнечного ветра"' in content
    assert "Показать аннотацию" in content
    assert 'id="longtext-sheet"' in content, "всплывающему блоку нужен контейнер в base.html"


def test_long_abstract_is_rendered_whole():
    """Без JavaScript аннотация видна целиком; подрезает её только скрипт."""
    text = "Очень длинная аннотация. " * 60
    seminar = make_seminar(timezone.localdate() + timedelta(days=3), abstract_ru=text)
    add_talk(seminar, "Доклад", [("Иванов И. И.", "ИКИ РАН")])

    content = get(seminar.get_absolute_url())

    assert text.strip() in content
    assert "data-longtext" in content, "скрипту нужна зацепка, чтобы повесить кнопку"


def test_archive_hides_upcoming():
    future = make_seminar(timezone.localdate() + timedelta(days=5))
    add_talk(future, "Будущий доклад", [("Иванов И. И.", "ИКИ РАН")])

    assert "Будущий доклад" not in get(reverse("seminars:archive"))


# --- Производительность -------------------------------------------------------


def test_archive_does_not_scale_queries_with_rows(client, django_assert_max_num_queries):
    """Защита от N+1: 15 заседаний должны стоить столько же запросов, сколько 3."""
    for i in range(15):
        seminar = make_seminar(timezone.localdate() - timedelta(days=i + 1), suffix=str(i))
        add_talk(seminar, f"Доклад {i}", [(f"Докладчик {i}", "ИКИ РАН")])

    # Прогрев: первый запрос наполняет кеш настроек сайта. Меряем
    # установившийся режим, иначе предел пришлось бы задирать и он
    # перестал бы ловить N+1.
    client.get(reverse("seminars:archive"))

    with django_assert_max_num_queries(13):
        client.get(reverse("seminars:archive"))


def test_home_does_not_scale_queries_with_talks(client, django_assert_max_num_queries):
    """Главная показывает ближайшее заседание целиком — с докладами и материалами.

    Значит, и грузить их надо разом: иначе каждый доклад и каждый материал
    стоил бы отдельного запроса.
    """
    from apps.seminars.models import Material

    upcoming = make_seminar(timezone.localdate() + timedelta(days=3), suffix="up")
    for i in range(4):
        talk = add_talk(upcoming, f"Ближайший доклад {i}", [(f"Смирнов {i}", "ИКИ РАН")])
        Material.objects.create(talk=talk, kind=Material.Kind.VIDEO, url=f"https://e.org/{i}")
    for i in range(5):
        past = make_seminar(timezone.localdate() - timedelta(days=i + 1), suffix=f"p{i}")
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
    seminar = make_seminar(timezone.localdate() + timedelta(days=3))
    add_talk(seminar, "Только по-русски", [("Иванов И. И.", "ИКИ РАН")])

    content = client.get("/en/").content.decode()

    assert "Только по-русски" in content
    assert '<html lang="en">' in content


def test_english_uses_translation_when_present(client):
    seminar = make_seminar(timezone.localdate() + timedelta(days=3))
    add_talk(
        seminar,
        "Русское название",
        [("Иванов И. И.", "ИКИ РАН")],
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
