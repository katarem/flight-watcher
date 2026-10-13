"""Calendario resumen en PNG para los avisos (se adjunta en Discord y en Telegram).

Pinta los meses en los que hay chollos con el precio más bajo de cada día, del más barato (verde) al más caro (rojo)
con el mismo criterio que el calendario del panel (cuartiles del precio del día, `frontend/src/lib/calendar.ts`), y
marca los días de los que avisa el mensaje. Se dibuja con Pillow; si no está instalado o no hay precios, no hay
imagen y el aviso sale igual sin ella.
"""
from __future__ import annotations

import io
import logging
from calendar import monthrange
from datetime import date
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("images")

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
WEEKDAYS = ["L", "M", "X", "J", "V", "S", "D"]
#: Como mucho estos meses por imagen (los primeros con chollos).
MAX_MONTHS = 3

# Colores del tema claro del panel (src/index.css), mezclados sobre blanco como en el calendario.
BG, FG, MUTED, LINE = (255, 255, 255), (17, 24, 39), (90, 100, 120), (226, 230, 239)
DEAL = (3, 107, 72)
LEVELS = {0: (246, 247, 250), 1: (205, 225, 218), 2: (232, 242, 238), 3: (244, 238, 230), 4: (245, 227, 226)}

CELL_W, CELL_H, GAP, PAD = 66, 52, 4, 28
MONTH_W = 7 * CELL_W + 6 * GAP

#: Fuentes que se buscan (en la imagen Docker vienen las DejaVu); si no hay ninguna, la de Pillow.
FONT_DIRS = ("/usr/share/fonts", "/usr/local/share/fonts", "/Library/Fonts", "/System/Library/Fonts",
             "C:/Windows/Fonts")
FONT_NAMES = {False: ("DejaVuSans.ttf", "LiberationSans-Regular.ttf", "FreeSans.ttf", "Arial.ttf", "arial.ttf"),
              True: ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "FreeSansBold.ttf", "Arial Bold.ttf",
                     "arialbd.ttf")}


@lru_cache(maxsize=1)
def _font_files() -> dict[bool, Path | None]:
    found: dict[bool, Path | None] = {False: None, True: None}
    for bold, names in FONT_NAMES.items():
        for name in names:
            for base in FONT_DIRS:
                hits = sorted(Path(base).rglob(name)) if Path(base).is_dir() else []
                if hits:
                    found[bold] = hits[0]
                    break
            if found[bold]:
                break
    return found


@lru_cache(maxsize=16)
def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    path = _font_files()[bold] or _font_files()[False]
    try:
        return ImageFont.truetype(str(path), size) if path else ImageFont.load_default(size)
    except OSError:
        return ImageFont.load_default(size)


def levels(prices: dict[date, float]) -> dict[date, int]:
    """Nivel 1 (de los más baratos) a 4 (de los más caros) de cada día: cuartil de su precio."""
    values = sorted(prices.values())
    if not values:
        return {}
    cuts = [values[min(len(values) - 1, int(len(values) * q))] for q in (0.25, 0.5, 0.75)]
    return {d: 1 + sum(p > c for c in cuts) for d, p in prices.items()}


def months_to_show(prices: dict[date, float], marked: set[date], limit: int = MAX_MONTHS) -> list[tuple[int, int]]:
    """Los primeros meses con días marcados (o, si no hay, con precio)."""
    source = sorted(marked & set(prices)) or sorted(prices)
    out: list[tuple[int, int]] = []
    for d in source:
        if (d.year, d.month) not in out:
            out.append((d.year, d.month))
        if len(out) == limit:
            break
    return out


def _price_text(p: float) -> str:
    return f"{round(p)} €"


def calendar_png(prices: dict[date, float], marked: set[date], title: str, subtitle: str = "",
                 limit: int = MAX_MONTHS) -> bytes | None:
    """PNG con los meses de los días marcados (como mucho `limit`) o None si no se puede dibujar."""
    if not prices:
        return None
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # sin Pillow, los avisos salen sin imagen
        return None
    months = months_to_show(prices, marked, limit)
    lvl = levels({d: p for d, p in prices.items() if (d.year, d.month) in months})
    cols = min(len(months), 3)
    grid_h = 22 + 22 + 6 * (CELL_H + GAP)  # nombre del mes, días de la semana y hasta 6 semanas
    head_h = 34 + (24 if subtitle else 0)
    width = PAD * 2 + cols * MONTH_W + (cols - 1) * PAD
    height = PAD + head_h + grid_h + 40 + PAD
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    draw.text((PAD, PAD), title, font=_font(22, True), fill=FG)
    if subtitle:
        draw.text((PAD, PAD + 32), subtitle, font=_font(15), fill=MUTED)

    top = PAD + head_h
    for i, (y, m) in enumerate(months):
        left = PAD + i * (MONTH_W + PAD)
        draw.text((left, top), f"{MESES[m - 1].capitalize()} {y}", font=_font(17, True), fill=FG)
        for wd, letter in enumerate(WEEKDAYS):
            cx = left + wd * (CELL_W + GAP) + CELL_W // 2
            draw.text((cx, top + 32), letter, font=_font(13, True), fill=MUTED, anchor="mm")
        first = date(y, m, 1).weekday()
        for day in range(1, monthrange(y, m)[1] + 1):
            d = date(y, m, day)
            pos = first + day - 1
            x = left + (pos % 7) * (CELL_W + GAP)
            yy = top + 44 + (pos // 7) * (CELL_H + GAP)
            box = (x, yy, x + CELL_W, yy + CELL_H)
            price = prices.get(d)
            draw.rounded_rectangle(box, radius=8, fill=LEVELS[lvl.get(d, 0) if price is not None else 0])
            if d in marked and price is not None:
                draw.rounded_rectangle(box, radius=8, outline=DEAL, width=3)
            draw.text((x + 7, yy + 5), str(day), font=_font(12, d in marked), fill=FG if price is not None else MUTED)
            if price is not None:
                draw.text((x + CELL_W // 2, yy + CELL_H - 15), _price_text(price),
                          font=_font(15, d in marked), fill=DEAL if d in marked else FG, anchor="mm")

    legend_y = top + grid_h + 14
    x = PAD
    for color, outline, text in ((LEVELS[1], None, "más barato"), (LEVELS[4], None, "más caro"),
                                 (BG, DEAL, "del aviso")):
        draw.rounded_rectangle((x, legend_y, x + 18, legend_y + 18), radius=4, fill=color,
                               outline=outline or LINE, width=3 if outline else 1)
        draw.text((x + 26, legend_y + 9), text, font=_font(14), fill=MUTED, anchor="lm")
        x += 26 + int(draw.textlength(text, font=_font(14))) + 24

    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
