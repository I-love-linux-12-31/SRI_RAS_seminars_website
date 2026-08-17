from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Seminar, Talk, TalkSpeaker


def _refresh(seminar: Seminar | None) -> None:
    if seminar is not None:
        seminar.rebuild_search_text()


@receiver([post_save, post_delete], sender=Talk)
def refresh_on_talk_change(sender, instance: Talk, **kwargs):
    """Доклады входят в поисковый текст заседания — держим его актуальным."""
    _refresh(instance.seminar)


@receiver([post_save, post_delete], sender=TalkSpeaker)
def refresh_on_speaker_link_change(sender, instance: TalkSpeaker, **kwargs):
    _refresh(instance.talk.seminar)
