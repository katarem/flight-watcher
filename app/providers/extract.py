"""Utilidades para obtener pares (fecha, precio) de una página de aerolínea.

Dos vías, ambas independientes de la estructura exacta de cada web:

1. Respuestas JSON (XHR/fetch) que la propia web pide al abrir el calendario de tarifas.
   Se recorren de forma recursiva buscando registros con una fecha y un precio.
2. Celdas del calendario en el DOM (atributos data-date / aria-label + texto con «€»).
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

MESES = {
    m: i
    for i, m in enumerate(
        ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"], 1)
}

MIN_PRICE, MAX_PRICE = 1.0, 5000.0

_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_TXT_DATE = re.compile(r"(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)\s+(?:de\s+)?(\d{4})", re.I)
_PRICE = re.compile(
    r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:€|eur)|(?:€|eur)\s*(\d{1,4}(?:[.,]\d{1,2})?)", re.I
)

PRIORITY_KEYS = (
    "price", "lowestprice", "minprice", "minimumprice", "totalprice",
    "fareprice", "amount", "total",
)
LOOSE_PRICE_HINTS = ("price", "fare", "precio", "tarifa", "importe")
DATE_HINTS = ("date", "day", "fecha", "departure", "outbound")


# ---------------------------------------------------------------- texto / DOM
def parse_day(text: str | None) -> date | None:
    if not text:
        return None
    m = _ISO.search(text)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = _TXT_DATE.search(text.lower())
    if m and m[2] in MESES:
        try:
            return date(int(m[3]), MESES[m[2]], int(m[1]))
        except ValueError:
            return None
    return None


def parse_price(text: str | None) -> float | None:
    if not text:
        return None
    m = _PRICE.search(text)
    if not m:
        return None
    value = float((m[1] or m[2]).replace(",", "."))
    return value if MIN_PRICE <= value <= MAX_PRICE else None


def read_calendar_cells(page, selectors: list[str]) -> dict[date, float]:
    """Lee las celdas de día visibles en el calendario abierto."""
    out: dict[date, float] = {}
    for sel in selectors:
        for cell in page.query_selector_all(sel):
            try:
                attrs = " ".join(
                    filter(None, [cell.get_attribute("data-date"),
                                  cell.get_attribute("aria-label"),
                                  cell.get_attribute("title")])
                )
                text = cell.inner_text()
            except Exception:  # noqa: BLE001 - la celda pudo desaparecer del DOM
                continue
            day = parse_day(attrs) or parse_day(text)
            price = parse_price(text) or parse_price(attrs)
            if day and price:
                out[day] = min(price, out.get(day, price))
        if out:
            break
    return out


# ------------------------------------------------------------------------ JSON
def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = float(value)
    elif isinstance(value, str):
        try:
            n = float(value.replace("€", "").replace("EUR", "").strip().replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    return n if MIN_PRICE <= n <= MAX_PRICE else None


def _find_price(node, depth: int = 0) -> float | None:
    if depth > 3:
        return None
    if isinstance(node, list):
        for item in node:
            n = _find_price(item, depth + 1)
            if n is not None:
                return n
        return None
    if not isinstance(node, dict):
        return None
    lowered = {str(k).lower(): v for k, v in node.items()}
    for name in PRIORITY_KEYS:  # claves «limpias» primero, para no coger tasas
        if name in lowered:
            v = lowered[name]
            n = _num(v) if not isinstance(v, (dict, list)) else _find_price(v, depth + 1)
            if n is not None:
                return n
    for k, v in lowered.items():
        if any(h in k for h in LOOSE_PRICE_HINTS) and "tax" not in k:
            n = _num(v) if not isinstance(v, (dict, list)) else _find_price(v, depth + 1)
            if n is not None:
                return n
    return None


def _iso_date(value) -> date | None:
    if isinstance(value, str):
        m = _ISO.match(value)
        if m:
            try:
                return date(int(m[1]), int(m[2]), int(m[3]))
            except ValueError:
                return None
    return None


def _add(out: dict[date, float], day: date, price: float):
    out[day] = min(price, out.get(day, price))


def walk_json(node, out: dict[date, float]):
    """Recorre un JSON buscando (fecha, precio) en registros o en mapas indexados por fecha."""
    if isinstance(node, list):
        for item in node:
            walk_json(item, out)
        return
    if not isinstance(node, dict):
        return

    for k, v in node.items():  # {"2026-10-24": 45.0} o {"2026-10-24": {"price": 45}}
        day = _iso_date(k)
        if day:
            price = _find_price(v) if isinstance(v, (dict, list)) else _num(v)
            if price:
                _add(out, day, price)

    day = None
    for k, v in node.items():  # {"date": "2026-10-24", "price": 45}
        if any(h in str(k).lower() for h in DATE_HINTS):
            day = _iso_date(v)
            if day:
                break
    if day:
        price = _find_price(node)
        if price:
            _add(out, day, price)

    for v in node.values():
        if isinstance(v, (dict, list)):
            walk_json(v, out)


class JsonCollector:
    """Guarda las respuestas JSON XHR/fetch que recibe una página."""

    def __init__(self, page, url_hints: tuple[str, ...] = (), strict: bool = False):
        self.hints = tuple(h.lower() for h in url_hints)
        #: con strict, si ninguna URL encaja con las pistas no se recurre a «todas las respuestas»
        #: (evita coger precios de otra ruta, p. ej. las ofertas de la portada)
        self.strict = strict
        self.items: list[tuple[str, object]] = []
        page.on("response", self._on_response)

    def _on_response(self, resp):
        try:
            if resp.request.resource_type not in ("xhr", "fetch") or resp.status >= 400:
                return
            if "json" not in (resp.headers.get("content-type") or "").lower():
                return
            self.items.append((resp.url, resp.json()))
        except Exception:  # noqa: BLE001 - cuerpo no disponible, redirección, etc.
            return

    def prices(self) -> dict[date, float]:
        groups = []
        if self.hints:
            groups.append([d for u, d in self.items if any(h in u.lower() for h in self.hints)])
        if not (self.strict and self.hints):
            groups.append([d for _, d in self.items])
        for group in groups:
            out: dict[date, float] = {}
            for data in group:
                walk_json(data, out)
            if out:
                return out
        return {}

    def dump(self, directory: Path, prefix: str, limit: int = 40):
        directory.mkdir(parents=True, exist_ok=True)
        for i, (url, data) in enumerate(self.items[:limit]):
            payload = {"url": url, "data": data}
            text = json.dumps(payload, ensure_ascii=False)
            if len(text) < 3_000_000:
                (directory / f"{prefix}-json-{i:02d}.json").write_text(text, encoding="utf-8")
