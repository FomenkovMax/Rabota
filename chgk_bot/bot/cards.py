"""Визуал: карточки с волчком «Что? Где? Когда?», рисуются через Pillow.
Запуск: python -m bot.cards  -> создаёт PNG в assets/"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
W, H = 1280, 640
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
]

THEMES = {
    "question": {"bg": (10, 20, 50), "accent": (240, 190, 60), "title": "ВОПРОС", "sub": "60 секунд на размышление"},
    "correct": {"bg": (8, 50, 38), "accent": (110, 230, 150), "title": "ВЕРНО!", "sub": "знатоки ведут в счёте"},
    "close": {"bg": (58, 44, 8), "accent": (250, 210, 70), "title": "ПОЧТИ", "sub": "версия была рядом"},
    "wrong": {"bg": (58, 14, 20), "accent": (240, 100, 100), "title": "МИМО", "sub": "счёт в пользу телезрителей"},
    "welcome": {"bg": (10, 20, 50), "accent": (240, 190, 60), "title": "ЧТО? ГДЕ? КОГДА?", "sub": "тренировка знатоков"},
}


def _font(size: int):
    for p in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wheel(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, accent) -> None:
    """Игровой стол: 13 секторов и стрелка."""
    n = 13
    for i in range(n):
        a0, a1 = 360 / n * i - 90, 360 / n * (i + 1) - 90
        shade = 0.35 if i % 2 else 0.18
        col = tuple(int(c * shade + 12) for c in accent)
        d.pieslice([cx - r, cy - r, cx + r, cy + r], a0, a1, fill=col, outline=accent, width=2)
    d.ellipse([cx - r // 4, cy - r // 4, cx + r // 4, cy + r // 4], fill=(10, 14, 30), outline=accent, width=4)
    ang = math.radians(-90 + 360 / n * 3.5)
    d.line([cx, cy, cx + math.cos(ang) * r * 0.95, cy + math.sin(ang) * r * 0.95], fill=(255, 255, 255), width=8)
    d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=accent)


def render(kind: str, out: Path) -> None:
    t = THEMES[kind]
    img = Image.new("RGB", (W, H), t["bg"])
    d = ImageDraw.Draw(img)
    for y in range(H):  # мягкий вертикальный градиент
        k = y / H * 0.5
        d.line([0, y, W, y], fill=tuple(int(c * (1 - k) + 5 * k) for c in t["bg"]))
    _wheel(d, 1000, 320, 250, t["accent"])
    d.text((70, 170), t["title"], font=_font(96 if len(t["title"]) < 12 else 56), fill=t["accent"])
    d.text((74, 350), t["sub"], font=_font(34), fill=(220, 225, 240))
    d.rectangle([74, 316, 420, 322], fill=t["accent"])
    img.save(out, optimize=True)


def build_all() -> None:
    ASSETS.mkdir(exist_ok=True)
    for kind in THEMES:
        render(kind, ASSETS / f"{kind}.png")


if __name__ == "__main__":
    build_all()
    print("Готово:", ", ".join(sorted(p.name for p in ASSETS.glob("*.png"))))
