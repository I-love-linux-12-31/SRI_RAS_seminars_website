"""Разбор страниц старого сайта seminar.cosmos.ru.

Старый сайт — Drupal 11 с Layout Builder. JSON:API на нём закрыт, sitemap.xml
нет, поэтому единственный вход — разметка. Она, к счастью, регулярная: у каждого
поля есть устойчивый класс `field--name-field-<машинное-имя>`, и цепляться нужно
именно за него, а не за вложенность блоков — вёрстка обёрток у Layout Builder
меняется от версии к версии, машинные имена полей не меняются.

Здесь только чистые функции: ни сети, ни ORM. Поэтому разбор проверяется тестами
на сохранённых страницах, без запросов наружу.

Поля старого сайта, которые нас интересуют:

    field-data-i-vremya-provedeniya   дата и время
    field-doklad (paragraph)          доклад, их бывает несколько
    field-tema-vystupleniya           тема доклада
    field-dokladchik                  докладчики строкой
    field-annotaciya                  PDF с аннотацией
    field-mesto-provedeniya           место
    field-instrukcii-po-onlayn-podkl  как подключиться онлайн

Поля `field-fio`, `field-dolzhnost`, `field-mesto-raboty-ucheby`,
`field-zayavka-na-propusk`, `field-soglasie-na-obrabotku-pd` — это форма заказа
пропуска, вшитая в страницу ближайшего заседания. Мы их не читаем: это разметка
формы, а не содержимое заседания.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, time
from urllib.parse import unquote

# --- Разбор даты и времени ---------------------------------------------------
#
# Здесь у старого сайта расходятся показания, и это главная ловушка импорта.
#
# Drupal отдаёт `<time datetime="..." >текст</time>`, где атрибут обязан быть в
# UTC, а текст отрисован в часовом поясе сайта. На seminar.cosmos.ru атрибут
# заполнен непоследовательно:
#
#     2026-05-13T09:00:00Z → «13 мая (среда), 12:00»   атрибут в UTC  (+3)
#     2023-02-01T15:00:00Z → «1 февраля (среда), 15:00» атрибут в МСК (+0)
#
# То есть у части узлов в поле UTC лежит московское время с припиской «Z».
# Разобрать это программно нельзя: 15:00Z — одинаково правдоподобно и как
# настоящий UTC, и как подделка.
#
# Поэтому время берём из человекочитаемого текста: именно его видит секретарь
# семинара, и именно оно считается правдой. Из атрибута берём только год,
# месяц и число — они совпадают в обоих вариантах (расхождение возможно лишь
# для заседаний, начинающихся до 3 часов ночи, чего не бывает; сверка дня
# недели ниже поймает и такой случай).

MONTHS_RU = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

# «13 мая (среда), 12:00» — скобка с днём недели и само время необязательны:
# на старых узлах встречается и голое «13 мая».
DATE_TEXT_RE = re.compile(
    r"(?P<day>\d{1,2})\s+(?P<month>[а-яё]+)"
    r"(?:\s*\((?P<weekday>[а-яё]+)\))?"
    r"(?:\s*,\s*(?P<hour>\d{1,2}):(?P<minute>\d{2}))?",
    re.IGNORECASE,
)

ISO_DATE_RE = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})")
ISO_TIME_RE = re.compile(r"T(?P<hour>\d{2}):(?P<minute>\d{2})")

# ФИО в формате «Фамилия И.О.» — с точками, но последняя точка не обязательна
# («Ким А.А»). Нужно, чтобы отличить второго докладчика от начала организации
# в строке вида «Томилина Т.М., Ким А.А, Институт машиноведения…».
INITIALS_NAME_RE = re.compile(r"^[А-ЯЁA-Z][а-яёa-z\-']+\s+[А-ЯЁA-Z]\.\s*[А-ЯЁA-Z]\.?$")

PLACEHOLDER = "***"


class ParseError(Exception):
    """Страница не похожа на заседание — разбирать нечего."""


@dataclass(frozen=True)
class LegacySpeaker:
    full_name: str
    affiliation: str = ""


@dataclass(frozen=True)
class LegacyMaterial:
    url: str
    """Ссылка на файл, как она стоит в разметке (может быть относительной)."""
    filename: str
    """Исходное имя файла из атрибута title — человекочитаемое, с кириллицей."""
    label: str
    """Подпись ссылки, обычно «Аннотация»."""


@dataclass
class LegacyTalk:
    title: str
    speakers: list[LegacySpeaker] = field(default_factory=list)
    materials: list[LegacyMaterial] = field(default_factory=list)


@dataclass
class LegacySeminar:
    node_id: str
    slug: str
    url: str
    date: date
    start_time: time
    talks: list[LegacyTalk] = field(default_factory=list)
    place: str = ""
    online_url: str = ""
    online_note: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        """Заголовок заседания — тема первого доклада.

        Так же устроен и шаблон архива: заголовком идёт первая тема, а второй
        доклад выводится отдельной строкой «+ ещё доклад». Заголовок узла на
        старом сайте («1.02.2023: Иванов Б.А., Дьячкова М.В.») для этого не
        годится — это дата и фамилии, а не тема.
        """
        return self.talks[0].title if self.talks else ""


def _soup(html: str):
    """Разбор с lxml. Импорт внутри функции — bs4 нет в проде."""
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError as exc:  # pragma: no cover — зависит от окружения
        raise RuntimeError(
            "Не установлены зависимости импорта. Поставьте их: uv sync --group legacy-import"
        ) from exc
    return BeautifulSoup(html, "lxml")


def _text(node) -> str:
    """Текст узла со схлопнутыми пробелами и убранными неразрывными."""
    if node is None:
        return ""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True).replace("\xa0", " ")).strip()


def _field(scope, name: str):
    """Первый элемент поля Drupal по машинному имени."""
    return scope.select_one(f".field--name-{name}")


def _fields(scope, name: str) -> list:
    return scope.select(f".field--name-{name}")


# --- Список архива -----------------------------------------------------------


def parse_archive_page(html: str) -> list[str]:
    """Ссылки на заседания с одной страницы архива.

    Пустой список означает, что страницы кончились — по нему и останавливается
    обход пагинации: у Drupal-пейджера нет надёжного признака «последняя».
    """
    soup = _soup(html)
    links: list[str] = []
    for article in soup.select("article.node--type-zasedanie-seminara"):
        anchor = article.select_one("h2.node__title a[href]")
        if anchor is None:
            continue
        href = anchor["href"].strip()
        if href not in links:
            links.append(href)
    return links


# --- Докладчики --------------------------------------------------------------


def _lines_with_bold(node) -> list[tuple[str, str]]:
    """Разбить поле докладчиков на строки, отдельно вернув жирный кусок.

    Несколько докладчиков в одном поле разделены `<br>`, а ФИО у новых записей
    выделено `<strong>`. Возвращает пары (весь текст строки, жирный текст).
    """
    lines: list[tuple[list[str], list[str]]] = [([], [])]
    for element in node.descendants:
        name = getattr(element, "name", None)
        if name == "br":
            lines.append(([], []))
            continue
        if name is not None:
            continue  # тег — интересен только его текст, он придёт отдельно
        text = str(element).replace("\xa0", " ")
        if not text.strip():
            continue
        lines[-1][0].append(text)
        if element.find_parent(["strong", "b"]) is not None:
            lines[-1][1].append(text)

    result = []
    for whole, bold in lines:
        full = re.sub(r"\s+", " ", "".join(whole)).strip()
        strong = re.sub(r"\s+", " ", "".join(bold)).strip()
        if full:
            result.append((full, strong))
    return result


def parse_speakers(node) -> list[LegacySpeaker]:
    """Разобрать поле «докладчик» в список людей.

    Поле заполняется от руки, и за три года сложилось три манеры записи:

        <strong>Нестик Тимофей Александрович</strong>, профессор РАН, …
        Иванов Б.А., д.ф.-м.н., в.н.с., Институт динамики геосфер РАН
        Томилина Т.М., Ким А.А, Институт машиноведения им. А.А. Благонравова РАН

    Первая разбирается по жирному, вторая — по первой запятой. Третья — два
    человека с общей организацией; её ловит проверка на «Фамилия И.О.»,
    иначе «Ким А.А» молча уехал бы в должность первого докладчика.
    """
    speakers: list[LegacySpeaker] = []
    for full, strong in _lines_with_bold(node):
        if full.strip(" *") == "":
            continue  # строка-заглушка «***»

        name = strong.strip().strip(",").strip()
        if len(name) > 1:
            # Жирным помечено ФИО, остальное — должность и организация.
            rest = full[len(strong) :] if full.startswith(strong) else full.replace(strong, "", 1)
            speakers.append(LegacySpeaker(name, rest.strip().lstrip(",").strip()))
            continue

        parts = [p.strip() for p in full.split(",")]
        names = []
        while parts and INITIALS_NAME_RE.match(parts[0]):
            names.append(parts.pop(0))
        if names:
            affiliation = ", ".join(parts).strip()
            speakers.extend(LegacySpeaker(n, affiliation) for n in names)
            continue

        # Ни жирного, ни инициалов: «Ушаков Игорь Борисович, академик РАН, …»
        # или «Dr. Masahiro Takagi, Kyoto Sangyo University». Имя — до первой
        # запятой; для этих двух форм это верно.
        head, _, tail = full.partition(",")
        if head.strip():
            speakers.append(LegacySpeaker(head.strip(), tail.strip()))
    return speakers


# --- Детальная страница ------------------------------------------------------


def _parse_datetime(node, warnings: list[str]) -> tuple[date, time]:
    """Дата — из атрибута, время — из текста. Почему так, см. шапку модуля."""
    tag = node.select_one("time") if node is not None else None
    if tag is None:
        raise ParseError("на странице нет даты заседания")

    iso = tag.get("datetime", "")
    match = ISO_DATE_RE.search(iso)
    if match is None:
        raise ParseError(f"не разобрать дату {iso!r}")
    day = date(int(match["year"]), int(match["month"]), int(match["day"]))

    shown = _text(tag)
    text_match = DATE_TEXT_RE.search(shown)

    if text_match is None or text_match["hour"] is None:
        # Текста нет или он без времени — берём время из атрибута и честно
        # предупреждаем: оно может оказаться московским, а может UTC.
        time_match = ISO_TIME_RE.search(iso)
        moment = (
            time(int(time_match["hour"]), int(time_match["minute"])) if time_match else time(11)
        )
        warnings.append(
            f"время взято из атрибута {iso!r} — в тексте «{shown}» его нет, проверьте вручную"
        )
        return day, moment

    moment = time(int(text_match["hour"]), int(text_match["minute"]))

    # Сверка текста с атрибутом: расхождение означает, что разметка не та,
    # какую мы разбираем, и молча импортировать такое нельзя.
    month = MONTHS_RU.get(text_match["month"].lower())
    if month is not None and (int(text_match["day"]), month) != (day.day, day.month):
        warnings.append(f"дата в тексте «{shown}» расходится с атрибутом {iso!r}, взят атрибут")
    weekday = text_match["weekday"]
    if weekday and weekday.lower() != WEEKDAYS_RU[day.weekday()]:
        warnings.append(
            f"день недели в тексте «{shown}» не совпадает с датой {day:%d.%m.%Y} "
            f"({WEEKDAYS_RU[day.weekday()]})"
        )
    return day, moment


def _parse_place(node) -> str:
    """Место проведения. Ссылку «Как проехать» выбрасываем — это навигация."""
    if node is None:
        return ""
    copy = node.__copy__()
    for anchor in copy.select("a"):
        if "проехать" in anchor.get_text().lower():
            anchor.decompose()
    for br in copy.select("br"):
        br.replace_with(", ")
    return re.sub(r"\s*,(\s*,)*\s*", ", ", _text(copy)).strip(" ,")


def _parse_materials(scope) -> list[LegacyMaterial]:
    """Ссылки на аннотации.

    Имя файла обычно лежит в атрибуте `title`, а текстом ссылки стоит слово
    «Аннотация». Но у части узлов атрибута нет и текстом ссылки идёт само имя
    файла — тогда имя достаём из адреса, а подпись ставим общую.
    """
    materials = []
    for holder in _fields(scope, "field-annotaciya"):
        for anchor in holder.select("a[href]"):
            href = anchor["href"].strip()
            label = _text(anchor)
            filename = (anchor.get("title") or "").strip()
            if not filename:
                filename = unquote(href.rsplit("/", 1)[-1])
            if label.lower().endswith(".pdf") or not label:
                label = "Аннотация"
            materials.append(LegacyMaterial(url=href, filename=filename, label=label))
    return materials


def parse_seminar_page(html: str, url: str) -> LegacySeminar:
    """Разобрать страницу заседания.

    Бросает ParseError, если страница не заседание или в ней нет ни одного
    непустого доклада: на старом сайте есть узлы-заготовки, у которых и тема,
    и докладчик стоят как «***».
    """
    soup = _soup(html)
    article = soup.select_one("article.node--type-zasedanie-seminara")
    if article is None:
        raise ParseError("страница не похожа на заседание семинара")

    warnings: list[str] = []
    day, moment = _parse_datetime(_field(article, "field-data-i-vremya-provedeniya"), warnings)

    talks: list[LegacyTalk] = []
    for block in article.select(".paragraph--type--doklad"):
        title = _text(_field(block, "field-tema-vystupleniya"))
        speakers = parse_speakers(_field(block, "field-dokladchik") or block)
        if title.strip(" *") == "" and not speakers:
            continue  # заготовка «***»
        talks.append(LegacyTalk(title=title, speakers=speakers, materials=_parse_materials(block)))

    if not talks:
        raise ParseError("заготовка без темы и докладчиков")

    online = _field(article, "field-instrukcii-po-onlayn-podkl")
    online_note = _text(online)
    link = re.search(r"https?://\S+", online_note) if online_note else None

    node_id = article.get("data-history-node-id", "")
    return LegacySeminar(
        node_id=str(node_id),
        slug=url.rstrip("/").rsplit("/", 1)[-1],
        url=url,
        date=day,
        start_time=moment,
        talks=talks,
        place=_parse_place(_field(article, "field-mesto-provedeniya")),
        online_url=link.group(0).rstrip(".,;") if link else "",
        online_note=online_note,
        warnings=warnings,
    )
