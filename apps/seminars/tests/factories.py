from datetime import date, time

from apps.seminars.models import Seminar, Speaker, Talk, TalkSpeaker, Topic


def make_topic(slug: str = "plasma", **kwargs) -> Topic:
    defaults = {
        "name_ru": "Физика космической плазмы",
        "name_en": "Space plasma physics",
        "short_ru": "Плазма",
        "short_en": "Plasma",
    }
    return Topic.objects.create(slug=slug, **(defaults | kwargs))


def make_seminar(when: date, *, topic: Topic | None = None, **kwargs) -> Seminar:
    defaults = {
        "slug": f"s-{when:%Y%m%d}-{kwargs.pop('suffix', '')}".rstrip("-"),
        "date": when,
        "start_time": time(11, 0),
        "topic": topic or make_topic(slug=f"t{when:%Y%m%d}"),
        "title_ru": "Тестовое заседание",
        "place_ru": "ИКИ РАН",
        "status": Seminar.Status.PUBLISHED,
    }
    return Seminar.objects.create(**(defaults | kwargs))


def add_talk(seminar: Seminar, title: str, speakers: list[tuple[str, str]]) -> Talk:
    talk = Talk.objects.create(seminar=seminar, title_ru=title, order=seminar.talks.count())
    for order, (name, affiliation) in enumerate(speakers):
        speaker, _ = Speaker.objects.get_or_create(
            full_name_ru=name, defaults={"affiliation_ru": affiliation}
        )
        TalkSpeaker.objects.create(talk=talk, speaker=speaker, order=order)
    return talk
