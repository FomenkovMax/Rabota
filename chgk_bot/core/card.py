"""Карточка-итог для отправки в чат: PNG 1080×1350, рисуется Pillow (шрифт DejaVu из образа)."""
import io

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
BG, SURF, GOLD, GOLD2, TEXT, DIM, OK = (11, 18, 38), (23, 34, 74), (242, 184, 75), (255, 217, 130), (241, 244, 255), (154, 166, 209), (62, 207, 142)
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"]


def _font(size: int):
    for p in FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _center(d, y, text, font, fill):
    w = d.textlength(text, font=font)
    d.text(((W - w) / 2, y), text, font=font, fill=fill)


def render_card(title: str, subtitle: str, st: dict) -> bytes:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for y in range(0, 420):      # мягкий золотистый градиент сверху вниз
        k = (1 - y / 420) ** 2 * 0.16
        d.line((0, y, W, y), fill=tuple(int(BG[c] + (GOLD[c] - BG[c]) * k) for c in range(3)))
    _center(d, 90, "ЧТО? ГДЕ? КОГДА?", _font(54), GOLD2)
    _center(d, 165, title, _font(40), TEXT)
    _center(d, 225, subtitle, _font(30), DIM)

    # три плитки: вопросов / взято / точность
    tiles = [(str(st["played"]), "вопросов"), (str(st["correct"]), "взято"), (f"{round(st['accuracy'] * 100)}%", "точность")]
    for i, (big, small) in enumerate(tiles):
        x0 = 60 + i * 335
        d.rounded_rectangle((x0, 310, x0 + 310, 530), 28, fill=SURF)
        w = d.textlength(big, font=_font(84))
        d.text((x0 + (310 - w) / 2, 340), big, font=_font(84), fill=GOLD2)
        w = d.textlength(small, font=_font(30))
        d.text((x0 + (310 - w) / 2, 460), small, font=_font(30), fill=DIM)

    # график по дням
    d.rounded_rectangle((60, 570, W - 60, 1010), 28, fill=SURF)
    d.text((100, 595), "Последние дни", font=_font(32), fill=TEXT)
    daily = st["daily"]
    mx = max([x["played"] for x in daily] + [1])
    bw = (W - 200) / len(daily)
    for i, x in enumerate(daily):
        bx = 100 + i * bw
        h_all = 300 * x["played"] / mx
        h_ok = 300 * x["correct"] / mx
        base = 960
        if x["played"]:
            d.rounded_rectangle((bx + 6, base - h_all, bx + bw - 6, base), 8, fill=(60, 78, 140))
            if x["correct"]:
                d.rounded_rectangle((bx + 6, base - h_ok, bx + bw - 6, base), 8, fill=OK)
        d.line((bx + 6, base + 4, bx + bw - 6, base + 4), fill=(60, 78, 140), width=3)

    streak = f"🔥 лучшая серия: {st['best_streak']}"
    streak = f"лучшая серия: {st['best_streak']}"       # эмодзи DejaVu не рисует
    d.text((100, 1050), streak, font=_font(36), fill=TEXT)
    t = st.get("avg_time_ms")
    d.text((100, 1110), f"среднее время ответа: {round(t / 1000)} с" if t else "среднее время: —", font=_font(36), fill=TEXT)
    d.text((100, 1170), f"очков: {st['points']:g}", font=_font(36), fill=TEXT)
    _center(d, 1270, "зелёное — взято, синее — сыграно", _font(26), DIM)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
