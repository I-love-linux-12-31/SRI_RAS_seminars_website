"""Демонстрационные данные из прототипа дизайна.

Нужны, чтобы поднятый с нуля сайт сразу можно было посмотреть. Настоящий
архив приезжает командой импорта со старого сайта (этап 4).
"""

from datetime import date, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.core.models import SiteSettings
from apps.seminars.models import Material, Seminar, Speaker, Talk, TalkSpeaker, Topic

TOPICS = [
    ("plasma", "Физика космической плазмы", "Space plasma physics", "Плазма", "Plasma"),
    (
        "hea",
        "Астрофизика высоких энергий",
        "High-energy astrophysics",
        "Астрофизика",
        "Astrophysics",
    ),
    ("sun", "Солнце и Солнечная система", "Sun and Solar System", "Солнце", "Sun"),
    ("planets", "Физика планет и атмосфер", "Planetary physics", "Планеты", "Planets"),
    ("dust", "Малые тела и космическая пыль", "Small bodies and dust", "Пыль", "Dust"),
    ("astrobio", "Астробиология", "Astrobiology", "Астробиология", "Astrobiology"),
    ("inter", "Междисциплинарные исследования", "Interdisciplinary", "Междисц.", "Interdisc."),
    ("society", "Наука и общество", "Science and society", "Общество", "Society"),
]

# (дата, тематика, тема заседания, [(доклад, [(ФИО, аффилиация)])])
SEMINARS = [
    (
        date(2026, 2, 18),
        "astrobio",
        "Происхождение и перенос воды во Вселенной",
        [
            (
                "Происхождение и перенос воды во Вселенной",
                [("Кирсанова Мария Сергеевна", "д. ф.-м. н., Институт астрономии РАН")],
            )
        ],
    ),
    (
        date(2026, 1, 14),
        "astrobio",
        "Механизм магниторецепции у перелётных птиц: что мы знаем",
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
        "inter",
        "Математическое моделирование иммунной системы и инфекционных заболеваний",
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
        "plasma",
        "Статистика высоких интенсивностей света в турбулентной среде",
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
        "sun",
        "Корональная сейсмология. Плазменно-пылевая система в атмосфере Марса",
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
        "hea",
        "Астрофизические источники нейтрино высоких энергий",
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
        "plasma",
        "50 лет исследований ионосферы",
        [
            (
                "50 лет исследований ионосферы",
                [("Пулинец Сергей Александрович", "д. ф.-м. н., ИКИ РАН")],
            )
        ],
    ),
]

UPCOMING = {
    "topic": "plasma",
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
        topics = self._topics()
        created = self._archive(topics)
        created += self._upcoming(topics)

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

    def _topics(self) -> dict[str, Topic]:
        topics = {}
        for order, (slug, ru, en, short_ru, short_en) in enumerate(TOPICS):
            topics[slug], _ = Topic.objects.update_or_create(
                slug=slug,
                defaults={
                    "name_ru": ru,
                    "name_en": en,
                    "short_ru": short_ru,
                    "short_en": short_en,
                    "order": order,
                },
            )
        return topics

    def _speaker(self, name_ru: str, aff_ru: str) -> Speaker:
        speaker, _ = Speaker.objects.get_or_create(
            full_name_ru=name_ru, defaults={"affiliation_ru": aff_ru}
        )
        return speaker

    def _slug(self, when: date, title: str) -> str:
        return f"{when:%Y-%m-%d}-{slugify(title, allow_unicode=False)[:120] or 'seminar'}"

    def _archive(self, topics) -> int:
        count = 0
        for when, topic_slug, title, talks in SEMINARS:
            seminar, created = Seminar.objects.get_or_create(
                slug=self._slug(when, title),
                defaults={
                    "date": when,
                    "start_time": time(11, 0),
                    "topic": topics[topic_slug],
                    "title_ru": title,
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
            Material.objects.create(
                seminar=seminar,
                kind=Material.Kind.ABSTRACT,
                url=f"https://seminar.cosmos.ru/abstracts/{seminar.slug}.pdf",
            )
            seminar.rebuild_search_text()
        return count

    def _upcoming(self, topics) -> int:
        # Дата считается от «сегодня», чтобы демо не устаревало.
        when = timezone.localdate() + timedelta(days=21)
        slug = self._slug(when, UPCOMING["title_ru"])
        if Seminar.objects.filter(slug=slug).exists():
            return 0

        seminar = Seminar.objects.create(
            slug=slug,
            date=when,
            start_time=time(11, 0),
            topic=topics[UPCOMING["topic"]],
            title_ru=UPCOMING["title_ru"],
            title_en=UPCOMING["title_en"],
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
