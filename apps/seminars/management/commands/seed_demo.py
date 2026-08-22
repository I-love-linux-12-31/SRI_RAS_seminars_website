"""Демонстрационные данные из прототипа дизайна.

Нужны, чтобы поднятый с нуля сайт сразу можно было посмотреть. Настоящий
архив приезжает командой импорта со старого сайта (этап 4).
"""

from datetime import date, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.core.models import SiteSettings
from apps.seminars.models import Material, Seminar, Speaker, Talk, TalkSpeaker

# (дата, [(доклад, [(ФИО, аффилиация)])])
SEMINARS = [
    (
        date(2026, 2, 18),
        [
            (
                "Происхождение и перенос воды во Вселенной",
                [("Кирсанова Мария Сергеевна", "д. ф.-м. н., Институт астрономии РАН")],
            )
        ],
    ),
    (
        date(2026, 1, 14),
        [
            (
                "Механизм магниторецепции у перелётных птиц: что мы знаем",
                [
                    (
                        "Чернецов Никита Севирович",
                        "чл.-корр. РАН, директор Зоологического института РАН",
                    ),
                    (
                        "Кавокин Кирилл Витальевич",
                        "д. ф.-м. н., лаборатория оптики спина им. И. Н. Уральцева СПбГУ",
                    ),
                ],
            )
        ],
    ),
    (
        date(2025, 11, 19),
        [
            (
                "Математическое моделирование иммунной системы и инфекционных заболеваний",
                [
                    (
                        "Бочаров Геннадий Алексеевич",
                        "д. ф.-м. н., в. н. с., Институт вычислительной математики "
                        "им. Г. И. Марчука РАН",
                    )
                ],
            )
        ],
    ),
    (
        date(2025, 4, 16),
        [
            (
                "Статистика высоких интенсивностей света, распространяющегося в турбулентной среде",
                [
                    (
                        "Лебедев Владимир Валентинович",
                        "чл.-корр. РАН, д. ф.-м. н., Институт теоретической физики "
                        "им. Л. Д. Ландау РАН",
                    )
                ],
            )
        ],
    ),
    (
        date(2025, 1, 29),
        [
            (
                "Корональная сейсмология",
                [
                    (
                        "Рудерман Михаил Соломонович",
                        "д. ф.-м. н., University of Sheffield, Великобритания; ИКИ РАН",
                    )
                ],
            ),
            (
                "Плазменно-пылевая система в атмосфере Марса",
                [
                    (
                        "Резниченко Юлия Сергеевна",
                        "лучшая работа молодых учёных 2023/2024, ИКИ РАН",
                    )
                ],
            ),
        ],
    ),
    (
        date(2024, 11, 20),
        [
            (
                "Астрофизические источники нейтрино высоких энергий",
                [
                    (
                        "Ковалев Юрий Юрьевич",
                        "чл.-корр. РАН, д. ф.-м. н., Max Planck Institute for Radio Astronomy",
                    )
                ],
            )
        ],
    ),
    (
        date(2024, 4, 17),
        [
            (
                "50 лет исследований ионосферы",
                [("Пулинец Сергей Александрович", "д. ф.-м. н., ИКИ РАН")],
            )
        ],
    ),
]

UPCOMING = {
    "title_ru": (
        "Турбулентность солнечного ветра на кинетических масштабах: "
        "результаты Solar Orbiter и Parker Solar Probe"
    ),
    "title_en": (
        "Solar wind turbulence at kinetic scales: results from Solar Orbiter and Parker Solar Probe"
    ),
    "abstract_ru": (
        "В докладе обсуждаются измерения магнитного поля и плазмы на масштабах ионного "
        "гирорадиуса, полученные в первых сближениях Solar Orbiter и Parker Solar Probe "
        "с Солнцем. Особое внимание — переходу от инерционного интервала к кинетическому "
        "и роли этого перехода в нагреве солнечного ветра."
    ),
    "abstract_en": (
        "The talk reviews magnetic-field and plasma measurements at ion-gyroradius scales "
        "obtained during the first close approaches of Solar Orbiter and Parker Solar Probe, "
        "focusing on the transition from the inertial to the kinetic range and its role in "
        "solar wind heating."
    ),
    "speaker": (
        "Смирнов Андрей Петрович",
        "д. ф.-м. н., отдел физики космической плазмы, ИКИ РАН",
        "Andrey P. Smirnov",
        "Dr. Sc., Space Plasma Physics Department, IKI RAS",
    ),
}

PLACE_RU = "ИКИ РАН, конференц-зал, корпус А, 2 этаж"
PLACE_EN = "IKI RAS, conference hall, building A, floor 2"


class Command(BaseCommand):
    help = "Заполнить базу демонстрационными данными из прототипа."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush", action="store_true", help="удалить существующие заседания перед загрузкой"
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["flush"]:
            Seminar.objects.all().delete()
            Speaker.objects.all().delete()

        self._site_settings()
        created = self._archive()
        created += self._upcoming()

        self.stdout.write(self.style.SUCCESS(f"Создано заседаний: {created}"))

    def _site_settings(self):
        site = SiteSettings.load()
        site.chair_ru = "Лев Матвеевич Зеленый"
        site.chair_title_ru = "академик РАН"
        site.secretary_ru = "Дарья Геннадьевна Евдокимова"
        site.secretary_title_ru = "к. ф.-м. н."
        site.email = "seminar@cosmos.ru"
        site.address_ru = "Москва, ул. Профсоюзная, 84/32"
        site.address_en = "84/32 Profsoyuznaya St., Moscow"
        site.save()

    def _speaker(self, name_ru: str, aff_ru: str) -> Speaker:
        speaker, _ = Speaker.objects.get_or_create(
            full_name_ru=name_ru, defaults={"affiliation_ru": aff_ru}
        )
        return speaker

    def _slug(self, when: date) -> str:
        return f"{when:%Y-%m-%d}"

    def _archive(self) -> int:
        count = 0
        for when, talks in SEMINARS:
            seminar, created = Seminar.objects.get_or_create(
                slug=self._slug(when),
                defaults={
                    "date": when,
                    "start_time": time(11, 0),
                    "place_ru": PLACE_RU,
                    "place_en": PLACE_EN,
                    "status": Seminar.Status.PUBLISHED,
                    "seminar_format": Seminar.Format.HYBRID,
                },
            )
            if not created:
                continue
            count += 1
            for order, (talk_title, speakers) in enumerate(talks):
                talk = Talk.objects.create(seminar=seminar, order=order, title_ru=talk_title)
                for s_order, (name, aff) in enumerate(speakers):
                    TalkSpeaker.objects.create(
                        talk=talk, speaker=self._speaker(name, aff), order=s_order
                    )
            # Материалы теперь только ссылками — например, на видеозапись.
            Material.objects.create(
                seminar=seminar,
                kind=Material.Kind.VIDEO,
                url=f"https://seminar.cosmos.ru/video/{seminar.slug}",
            )
            seminar.rebuild_search_text()
        return count

    def _upcoming(self) -> int:
        # Дата считается от «сегодня», чтобы демо не устаревало.
        when = timezone.localdate() + timedelta(days=21)
        slug = self._slug(when)
        if Seminar.objects.filter(slug=slug).exists():
            return 0

        seminar = Seminar.objects.create(
            slug=slug,
            date=when,
            start_time=time(11, 0),
            abstract_ru=UPCOMING["abstract_ru"],
            abstract_en=UPCOMING["abstract_en"],
            place_ru=PLACE_RU,
            place_en=PLACE_EN,
            status=Seminar.Status.PUBLISHED,
            seminar_format=Seminar.Format.HYBRID,
            pass_required=True,
        )
        name_ru, aff_ru, name_en, aff_en = UPCOMING["speaker"]
        speaker, _ = Speaker.objects.get_or_create(
            full_name_ru=name_ru,
            defaults={
                "affiliation_ru": aff_ru,
                "full_name_en": name_en,
                "affiliation_en": aff_en,
            },
        )
        talk = Talk.objects.create(
            seminar=seminar,
            order=0,
            title_ru=UPCOMING["title_ru"],
            title_en=UPCOMING["title_en"],
        )
        TalkSpeaker.objects.create(talk=talk, speaker=speaker, order=0)
        seminar.rebuild_search_text()
        return 1
