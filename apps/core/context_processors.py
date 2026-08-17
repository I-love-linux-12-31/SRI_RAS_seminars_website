from .models import SiteSettings


def site_settings(request):
    return {"site": SiteSettings.load()}
