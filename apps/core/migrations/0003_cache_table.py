"""Таблица кеша для DatabaseCache.

`migrate` её не создаёт: обычно это отдельный шаг `createcachetable`.
Делаем его частью миграций, чтобы развёртывание оставалось одной командой
и ничего не пришлось помнить руками.
"""

from django.core.management import call_command
from django.db import migrations

TABLE = "django_cache"


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", TABLE, database=schema_editor.connection.alias)


def drop_cache_table(apps, schema_editor):
    schema_editor.execute(f'DROP TABLE IF EXISTS "{TABLE}"')


class Migration(migrations.Migration):
    dependencies = [("core", "0002_sitesettings_privacy_policy_text_and_more")]

    operations = [migrations.RunPython(create_cache_table, drop_cache_table)]
