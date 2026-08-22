from datetime import date, time

from apps.seminars.models import Seminar, Speaker, Talk, TalkSpeaker


def make_seminar(when: date, **kwargs) -> Seminar:
    defaults = {
        "slug": f"s-{when:%Y%m%d}-{kwargs.pop('suffix', '')}".rstrip("-"),
        "date": when,
        "start_time": time(11, 0),
        "place_ru": "ИКИ РАН",
        "status": Seminar.Status.PUBLISHED,
    }
    return Seminar.objects.create(**(defaults | kwargs))


def add_talk(seminar: Seminar, title: str, speakers: list[tuple[str, str]], **extra) -> Talk:
    talk = Talk.objects.create(
        seminar=seminar, title_ru=title, order=seminar.talks.count(), **extra
    )
    for order, (name, affiliation) in enumerate(speakers):
        speaker, _ = Speaker.objects.get_or_create(
            full_name_ru=name, defaults={"affiliation_ru": affiliation}
        )
        TalkSpeaker.objects.create(talk=talk, speaker=speaker, order=order)
    return talk
