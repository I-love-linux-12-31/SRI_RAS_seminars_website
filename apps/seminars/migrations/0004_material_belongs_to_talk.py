"""Материал переезжает с заседания на доклад.

Заказчик уточнил: файл и ссылка прикладываются к докладу, а у заседания из
внешнего остаётся только ссылка на видеоконференцию. Материалы, висевшие на
заседании целиком, переносятся на его первый доклад — других кандидатов нет.
"""

import django.db.models.deletion
from django.db import migrations, models


def move_to_first_talk(apps, schema_editor):
    Material = apps.get_model("seminars", "Material")
    Talk = apps.get_model("seminars", "Talk")

    orphans = Material.objects.filter(talk__isnull=True).select_related("seminar")
    for material in orphans:
        talk = Talk.objects.filter(seminar=material.seminar).order_by("order", "id").first()
        if talk is None:
            # Заседание без докладов: материалу не к чему прицепиться, а
            # показывать его больше негде.
            material.delete()
            continue
        material.talk = talk
        material.save(update_fields=["talk"])


class Migration(migrations.Migration):
    dependencies = [
        ("seminars", "0003_remove_topic_title_poster_photo"),
    ]

    operations = [
        migrations.RunPython(move_to_first_talk, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="material",
            name="talk",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="materials",
                to="seminars.talk",
                verbose_name="доклад",
            ),
        ),
        migrations.RemoveField(model_name="material", name="seminar"),
    ]
