"""Роли панели управления.

Две роли, как в жизни семинара: секретарь ведёт заседания и заявки,
руководитель дополнительно правит тексты сайта и удаляет записи.
Обе требуют is_staff — панель проверяет его отдельно.
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

SECRETARY = "Секретарь семинара"
CHAIR = "Руководитель семинара"

# (приложение, модель, действия)
SECRETARY_PERMS = [
    ("seminars", "seminar", ["add", "change", "view"]),
    ("seminars", "talk", ["add", "change", "delete", "view"]),
    ("seminars", "talkspeaker", ["add", "change", "delete", "view"]),
    ("seminars", "speaker", ["add", "change", "view"]),
    ("seminars", "material", ["add", "change", "delete", "view"]),
    ("registrations", "registration", ["change", "view"]),
]

# Руководитель — всё то же плюс удаление и настройки сайта.
CHAIR_EXTRA = [
    ("seminars", "seminar", ["delete"]),
    ("seminars", "speaker", ["delete"]),
    ("registrations", "registration", ["delete"]),
    ("core", "sitesettings", ["change", "view"]),
]


def collect(spec) -> list[Permission]:
    found = []
    for app_label, model, actions in spec:
        for action in actions:
            codename = f"{action}_{model}"
            permission = Permission.objects.filter(
                content_type__app_label=app_label, codename=codename
            ).first()
            if permission is not None:
                found.append(permission)
    return found


class Command(BaseCommand):
    help = "Создать группы «Секретарь семинара» и «Руководитель семинара»."

    def handle(self, *args, **options):
        secretary_perms = collect(SECRETARY_PERMS)
        chair_perms = secretary_perms + collect(CHAIR_EXTRA)

        for name, perms in ((SECRETARY, secretary_perms), (CHAIR, chair_perms)):
            group, created = Group.objects.get_or_create(name=name)
            group.permissions.set(perms)
            verb = "создана" if created else "обновлена"
            self.stdout.write(self.style.SUCCESS(f"Группа «{name}» {verb}: прав {len(perms)}"))

        self.stdout.write(
            "Не забудьте отметить у пользователей «сотрудник» (is_staff) — "
            "без него панель недоступна."
        )
