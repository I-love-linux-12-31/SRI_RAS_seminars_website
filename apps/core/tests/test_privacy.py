"""Согласие на обработку ПД отдаётся документом.

Заказчик утверждает формулировку на бумаге, поэтому на сайте лежит ровно тот
файл, который утверждён: ни текстового поля, ни ссылки на чужой ресурс.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.core.models import SiteSettings

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def upload(name: str = "soglasie.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, PDF, content_type="application/pdf")


def test_page_shows_a_placeholder_while_no_document_is_uploaded(client):
    response = client.get(reverse("seminars:privacy"))

    assert response.status_code == 200
    assert "не утверждён" in response.content.decode()


def test_uploaded_document_is_served_inline(client):
    site = SiteSettings.load()
    site.privacy_policy_file = upload()
    site.save()

    response = client.get(reverse("seminars:privacy"))

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    # inline, а не attachment: документ открывается по ссылке, а не скачивается.
    assert "attachment" not in response.get("Content-Disposition", "")
    assert b"".join(response.streaming_content).startswith(b"%PDF")
