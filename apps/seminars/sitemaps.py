from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Seminar


class SeminarSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.7

    def items(self):
        return Seminar.objects.published().order_by("-date")

    def lastmod(self, obj: Seminar):
        return obj.updated_at


class StaticSitemap(Sitemap):
    changefreq = "weekly"
    priority = 1.0

    def items(self):
        return ["seminars:home", "seminars:about", "seminars:archive"]

    def location(self, item):
        return reverse(item)


sitemaps = {"seminars": SeminarSitemap, "static": StaticSitemap}
