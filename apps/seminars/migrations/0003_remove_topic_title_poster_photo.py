"""Заказчик убрал тему и тематику заседания, постер и фото докладчика.

Заседание больше не несёт собственного заголовка: оно состоит из докладов,
и в заголовке идёт тема первого. Поэтому перед удалением колонки тема
заседания переезжает в доклад — у заведённых руками заседаний без докладов
она была единственным содержанием.
"""

from django.db import migrations


def title_becomes_a_talk(apps, schema_editor):
    Seminar = apps.get_model("seminars", "Seminar")
    Talk = apps.get_model("seminars", "Talk")

    for seminar in Seminar.objects.filter(talks__isnull=True).exclude(title_ru=""):
        Talk.objects.create(
            seminar=seminar,
            order=0,
            title_ru=seminar.title_ru,
            title_en=seminar.title_en,
        )


def rebuild_search_text(apps, schema_editor):
    """Пересобрать поисковый текст без темы заседания и тематики.

    Повторяет Seminar.rebuild_search_text(), но на исторических моделях:
    свойств и методов у них нет, а стоявший в колонке текст всё ещё нашёлся
    бы поиском по удалённой теме.
    """
    Seminar = apps.get_model("seminars", "Seminar")

    updated = []
    for seminar in Seminar.objects.prefetch_related("talks__speakers"):
        parts = [seminar.abstract_ru, seminar.abstract_en]
        for talk in seminar.talks.all():
            parts += [talk.title_ru, talk.title_en]
            for speaker in talk.speakers.all():
                parts += [speaker.full_name_ru, speaker.full_name_en, speaker.affiliation_ru]
        seminar.search_text = " ".join(p for p in parts if p)
        updated.append(seminar)
    Seminar.objects.bulk_update(updated, ["search_text"], batch_size=200)


class Migration(migrations.Migration):
    dependencies = [
        ("seminars", "0002_alter_material_url_alter_seminar_online_url"),
    ]

    operations = [
        migrations.RunPython(title_becomes_a_talk, migrations.RunPython.noop),
        migrations.RemoveField(model_name="seminar", name="topic"),
        migrations.RemoveField(model_name="seminar", name="poster"),
        migrations.RemoveField(model_name="seminar", name="title_en"),
        migrations.RemoveField(model_name="seminar", name="title_ru"),
        migrations.RemoveField(model_name="speaker", name="photo"),
        migrations.DeleteModel(name="Topic"),
        migrations.RunPython(rebuild_search_text, migrations.RunPython.noop),
    ]
