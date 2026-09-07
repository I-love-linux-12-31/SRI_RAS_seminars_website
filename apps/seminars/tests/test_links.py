"""Шлюз внешних ссылок.

Ссылка на видеоконференцию стала публичной, но в разметке страницы её нет:
краулер видит только локальный адрес шлюза, а сам адрес конференции шлюз
отдаёт после проверки посетителя.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core import captcha
from apps.core.models import SiteSettings
from apps.seminars.models import Material, Seminar

from .factories import add_talk, make_seminar

pytestmark = pytest.mark.django_db

CONFERENCE = "https://tconf.geosmis.ru/c/456987"


@pytest.fixture
def seminar():
    seminar = make_seminar(timezone.localdate() + timedelta(days=5), online_url=CONFERENCE)
    add_talk(seminar, "Турбулентность солнечного ветра", [("Смирнов А. П.", "ИКИ РАН")])
    return seminar


def gate(seminar) -> str:
    return reverse("seminars:online_link", kwargs={"slug": seminar.slug})


def solve(client) -> str:
    """Пройти проверку так же, как это делает человек: забрать картинку и ответить."""
    client.get(reverse("captcha_image"))
    return client.session[captcha.CODE_KEY]["code"]


def test_seminar_page_shows_the_link_but_not_the_address(client, seminar):
    content = client.get(seminar.get_absolute_url()).content.decode()

    assert gate(seminar) in content, "ссылка на трансляцию должна быть на странице"
    assert CONFERENCE not in content, "адрес конференции не должен попадать в разметку"


def test_archive_seminar_hides_the_link(client):
    """Заказчик просил убрать ссылку у прошедших заседаний: подключаться некуда."""
    past = make_seminar(timezone.localdate() - timedelta(days=30), online_url=CONFERENCE)
    add_talk(past, "Прошедший доклад", [("Иванов И. И.", "ИКИ РАН")])

    content = client.get(past.get_absolute_url()).content.decode()

    assert gate(past) not in content
    assert CONFERENCE not in content


def test_archive_seminar_gate_is_closed_too(client):
    """Убрать ссылку со страницы мало: адрес шлюза угадывается по slug."""
    past = make_seminar(timezone.localdate() - timedelta(days=30), online_url=CONFERENCE)
    add_talk(past, "Прошедший доклад", [("Иванов И. И.", "ИКИ РАН")])

    assert client.get(gate(past)).status_code == 404


def test_gate_asks_for_the_code_first(client, seminar):
    response = client.get(gate(seminar))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Код с картинки" in content
    assert CONFERENCE not in content


def test_correct_code_leads_to_the_conference(client, seminar):
    code = solve(client)

    response = client.post(gate(seminar), {"answer": code})

    assert response.status_code == 302
    assert response["Location"] == CONFERENCE
    assert response["X-Robots-Tag"] == "noindex, nofollow"


def test_lowercase_answer_is_accepted(client, seminar):
    code = solve(client)

    response = client.post(gate(seminar), {"answer": code.lower()})

    assert response["Location"] == CONFERENCE


def test_wrong_code_does_not_leak_the_address(client, seminar):
    solve(client)

    response = client.post(gate(seminar), {"answer": "ZZZZZ"})

    assert response.status_code == 422
    assert CONFERENCE not in response.content.decode()


def test_code_is_single_use(client, seminar):
    """Подобранный код не должен работать второй раз."""
    code = solve(client)
    client.post(gate(seminar), {"answer": "ZZZZZ"})

    response = client.post(gate(seminar), {"answer": code})

    assert response.status_code == 422


def test_passed_check_is_remembered(client, seminar):
    """Иначе участник разгадывал бы картинку на каждой ссылке."""
    client.post(gate(seminar), {"answer": solve(client)})

    response = client.get(gate(seminar))

    assert response.status_code == 302
    assert response["Location"] == CONFERENCE


def test_check_can_be_switched_off_in_settings(client, seminar):
    site = SiteSettings.load()
    site.online_link_captcha = False
    site.save()

    response = client.get(gate(seminar))

    assert response.status_code == 302
    assert response["Location"] == CONFERENCE


def test_seminar_without_a_link_has_no_gate(client, seminar):
    seminar.online_url = ""
    seminar.save()

    assert client.get(gate(seminar)).status_code == 404


def test_unpublished_seminar_link_is_not_reachable(client, seminar):
    seminar.status = Seminar.Status.HIDDEN
    seminar.save()

    assert client.get(gate(seminar)).status_code == 404


# --- Материалы ----------------------------------------------------------------


def test_material_link_goes_through_the_gate_without_a_check(client, seminar):
    """Капча перед архивным PDF мешала бы без всякой пользы."""
    material = Material.objects.create(
        talk=seminar.lead_talk, kind=Material.Kind.VIDEO, url="https://example.org/video"
    )

    content = client.get(seminar.get_absolute_url()).content.decode()
    assert "https://example.org/video" not in content

    response = client.get(reverse("seminars:material_link", kwargs={"pk": material.pk}))
    assert response.status_code == 302
    assert response["Location"] == "https://example.org/video"


def test_material_with_a_file_is_served_directly(client, seminar):
    """Свой файл — не внешняя ссылка, гонять его через шлюз незачем."""
    from django.core.files.base import ContentFile

    material = Material(talk=seminar.lead_talk, kind=Material.Kind.ABSTRACT)
    material.file.save("annotation.pdf", ContentFile(b"%PDF-1.4"), save=True)

    assert material.href == material.file.url


def test_robots_keeps_crawlers_out_of_the_gate(client):
    content = client.get("/robots.txt").content.decode()

    assert "Disallow: /link/" in content
