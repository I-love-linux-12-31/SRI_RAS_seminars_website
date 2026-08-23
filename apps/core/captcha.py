"""Самописная капча: код с картинки.

Внешние сервисы (reCAPTCHA и подобные) не годятся: сайт института не должен
гонять посетителя на чужой домен и отдавать туда его адрес ради ссылки на
собственный семинар. Задача здесь скромная — отсечь массовый обход страниц
скриптом, а не остановить целенаправленный разбор картинки.

Код живёт в сессии, а не в скрытом поле формы: иначе ответ уехал бы к клиенту
вместе с вопросом. Пройденная проверка помнится два часа, чтобы участник
не разгадывал картинку на каждой ссылке.
"""

import random
import time
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

# Ни нуля с буквой O, ни единицы с I: на картинке с шумом их не различить.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LENGTH = 5

CODE_KEY = "captcha_code"
PASSED_KEY = "captcha_passed_until"

PASS_TTL = 2 * 60 * 60
CODE_TTL = 10 * 60

WIDTH, HEIGHT = 190, 60
BACKGROUND = (245, 243, 237)
INK = (26, 26, 26)


def new_code(session) -> str:
    code = "".join(random.choices(ALPHABET, k=LENGTH))
    session[CODE_KEY] = {"code": code, "born": time.time()}
    return code


def render_png(code: str) -> bytes:
    """Картинка с кодом: каждый знак под своим углом, поверх — шум."""
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=38)

    step = WIDTH // (LENGTH + 1)
    for index, char in enumerate(code):
        # Каждый знак рисуется отдельной картинкой и поворачивается: цельная
        # строка одним шрифтом читается распознавателем почти без ошибок.
        glyph = Image.new("RGBA", (step + 12, HEIGHT), (0, 0, 0, 0))
        ImageDraw.Draw(glyph).text((6, 6), char, font=font, fill=INK)
        glyph = glyph.rotate(random.uniform(-28, 28), resample=Image.BICUBIC)
        image.paste(glyph, (index * step + 10, random.randint(-6, 6)), glyph)

    for _ in range(4):
        draw.line(
            [(random.randint(0, WIDTH), random.randint(0, HEIGHT)) for _ in range(2)],
            fill=INK,
            width=1,
        )
    for _ in range(400):
        draw.point((random.randint(0, WIDTH), random.randint(0, HEIGHT)), fill=INK)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def check(session, answer: str) -> bool:
    """Сверить ответ. Код одноразовый: и верный, и неверный гасят его."""
    issued = session.pop(CODE_KEY, None)
    if not issued or time.time() - issued.get("born", 0) > CODE_TTL:
        return False
    if (answer or "").strip().upper() != issued["code"]:
        return False
    session[PASSED_KEY] = time.time() + PASS_TTL
    return True


def is_verified(session) -> bool:
    return float(session.get(PASSED_KEY) or 0) > time.time()
