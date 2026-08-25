"""Узел старого сайта разбирается на заседания по докладам.

Раньше узел был равен заседанию, поэтому `node_id` и был уникальным. Теперь
узел с двумя докладами даёт два заседания, и связь помнит, каким по счёту
докладом каждое из них было.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("legacy_import", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="legacyseminarlink",
            name="talk_index",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text=(
                    "Узел старого сайта с двумя докладами разбирается на два заседания, "
                    "и каждое помнит, каким по счёту докладом оно было."
                ),
                verbose_name="номер доклада в узле",
            ),
        ),
        migrations.AlterField(
            model_name="legacyseminarlink",
            name="node_id",
            field=models.CharField(max_length=20, verbose_name="узел старого сайта"),
        ),
        migrations.AlterModelOptions(
            name="legacyseminarlink",
            options={
                "ordering": ["node_id", "talk_index"],
                "verbose_name": "связь со старым сайтом",
                "verbose_name_plural": "связи со старым сайтом",
            },
        ),
        migrations.AddConstraint(
            model_name="legacyseminarlink",
            constraint=models.UniqueConstraint(
                fields=("node_id", "talk_index"), name="unique_legacy_node_talk"
            ),
        ),
    ]
