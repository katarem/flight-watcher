"""Abstracción de proveedores.

Para añadir una aerolínea nueva:
  1. Crea `app/providers/<nombre>.py` con una clase que herede de `ApiProvider` si la web
     expone un endpoint JSON accesible sin navegador (preferible: más rápido y estable) o de
     `CalendarProvider` si hay que recorrer la web con Playwright.
  2. Regístrala en `app/providers/__init__.py`.
El panel, el histórico, las gráficas y las notificaciones la reconocen automáticamente.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from .extract import JsonCollector, read_calendar_cells

#: User-Agent honesto para las APIs: no nos hacemos pasar por un navegador.
USER_AGENT = "flight-watcher/1.0 (+alertas de precio personales)"


def add_months(day: date, months: int) -> date:
    """Día 1 del mes que cae `months` meses después del mes de `day`."""
    y, m = divmod(day.month - 1 + months, 12)
    return date(day.year + y, m + 1, 1)


class ProviderError(RuntimeError):
    pass


@dataclass
class DayPrice:
    day: date
    price: float
    currency: str = "EUR"
    #: Aeropuertos reales del precio (útil con códigos de ciudad como TCI = TFN + TFS).
    origin: str = ""
    destination: str = ""


class Provider(ABC):
    key: str = ""
    label: str = ""
    color: str = "#888888"
    #: False si el proveedor consulta una API y no necesita Playwright (page llega como None).
    needs_browser: bool = True
    #: Plantilla de enlace. Marcadores: {origin} {destination} {date} (AAAA-MM-DD)
    #: {date_dmy} (DD/MM/AAAA) {year} {month} {day}
    default_link_template: str = ""

    @abstractmethod
    def fetch_prices(
        self, page, origin: str, destination: str, max_months: int, debug_dir: Path | None = None
    ) -> list[DayPrice]:
        """Devuelve el precio más bajo de cada día que tenga precio publicado."""

    def build_link(self, template: str, origin: str, destination: str, day: date) -> str:
        tpl = (template or "").strip() or self.default_link_template
        values = {
            "origin": origin, "destination": destination,
            "date": day.isoformat(), "date_dmy": day.strftime("%d/%m/%Y"),
            "year": day.year, "month": f"{day.month:02d}", "day": f"{day.day:02d}",
        }
        try:
            return tpl.format(**values)
        except (KeyError, IndexError, ValueError):
            return tpl


def find(page, selectors: list[str], timeout: int = 8000):
    """Primer elemento visible entre varios selectores alternativos (o None)."""
    deadline = time.monotonic() + timeout / 1000
    while True:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:  # noqa: BLE001
                continue
        if time.monotonic() > deadline:
            return None
        page.wait_for_timeout(250)


class CalendarProvider(Provider):
    """Flujo genérico: abrir web → solo ida → origen/destino → abrir calendario → leer precios.

    Lee los precios por dos vías (respuestas JSON del calendario y celdas del DOM) y
    se queda con el mínimo de cada día. Cada lista de selectores es una lista de
    alternativas: se usa la primera que exista en la página.
    """

    home_url: str = ""
    #: Fragmentos de URL de las respuestas JSON con precios. Admiten {origin} y {destination}.
    url_hints: tuple[str, ...] = ()
    #: Si True, solo se usan respuestas cuya URL encaje con url_hints (sin recurrir a las demás).
    strict_url_hints: bool = False
    settle_ms: int = 2000

    sel_cookies: list[str] = ["#onetrust-accept-btn-handler", "button:has-text('Aceptar todas')"]
    sel_oneway: list[str] = ["text=/^\\s*solo ida\\s*$/i", "label:has-text('Solo ida')"]
    sel_origin: list[str] = ["input[placeholder*='rigen' i]", "input[aria-label*='rigen' i]"]
    sel_destination: list[str] = ["input[placeholder*='estino' i]", "input[aria-label*='estino' i]"]
    sel_option: list[str] = [
        "[data-iata='{code}']", "[data-value='{code}']",
        "[role=option]:has-text('{code}')", "li:has-text('({code})')", "li:has-text('{code}')",
    ]
    sel_date: list[str] = ["input[placeholder*='ida' i]", "[aria-label*='fecha de ida' i]"]
    sel_day: list[str] = ["[data-date]", "td[aria-label]", "[role=gridcell]"]
    sel_next: list[str] = ["button[aria-label*='iguiente' i]", "button[aria-label*='next' i]"]
    sel_flexible: list[str] = []

    # ---- pasos (sobrescribibles por cada proveedor) -------------------------------
    def dismiss_cookies(self, page):
        btn = find(page, self.sel_cookies, timeout=5000)
        if btn:
            btn.click()

    def choose_one_way(self, page):
        el = find(page, self.sel_oneway, timeout=6000)
        if el:
            el.click()

    def pick_station(self, page, selectors: list[str], code: str, what: str):
        field = find(page, selectors)
        if not field:
            raise ProviderError(f"No encuentro el campo de {what} (revisa sel_{what} en {self.key}.py)")
        field.click()
        try:
            field.fill("")
        except Exception:  # noqa: BLE001
            pass
        page.keyboard.type(code, delay=90)
        page.wait_for_timeout(700)
        opt = find(page, [s.format(code=code) for s in self.sel_option], timeout=4000)
        if opt:
            opt.click()
        else:
            page.keyboard.press("Enter")

    def open_calendar(self, page):
        field = find(page, self.sel_date)
        if not field:
            raise ProviderError(f"No encuentro el campo de fecha (revisa sel_date en {self.key}.py)")
        field.click()
        page.wait_for_timeout(self.settle_ms)

    def read_months(self, page, max_months: int, debug_dir: Path | None, tag: str) -> dict[date, float]:
        found: dict[date, float] = {}
        for i in range(max_months):
            if debug_dir:
                debug_dir.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(debug_dir / f"{tag}-mes-{i:02d}.png"))
            for d, p in read_calendar_cells(page, self.sel_day).items():
                found[d] = min(p, found.get(d, p))
            nxt = find(page, self.sel_next, timeout=1500)
            if not nxt or not nxt.is_enabled():
                break
            nxt.click()
            page.wait_for_timeout(600)
        return found

    # ---- orquestación --------------------------------------------------------------
    def fetch_prices(self, page, origin, destination, max_months, debug_dir=None):
        tag = f"{self.key}-{origin}-{destination}"
        hints = tuple(h.format(origin=origin, destination=destination) for h in self.url_hints)
        collector = JsonCollector(page, hints, strict=self.strict_url_hints)
        dom: dict[date, float] = {}
        try:
            resp = page.goto(self.home_url, wait_until="domcontentloaded")
            if resp is not None and resp.status in (403, 429):
                raise ProviderError(
                    f"{self.label} bloquea el navegador automatizado (HTTP {resp.status}, anti-bot)"
                )
            self.dismiss_cookies(page)
            self.choose_one_way(page)
            self.pick_station(page, self.sel_origin, origin, "origin")
            self.pick_station(page, self.sel_destination, destination, "destination")
            self.open_calendar(page)
            dom = self.read_months(page, max_months, debug_dir, tag)
            if not dom and not collector.prices() and self.sel_flexible:
                flex = find(page, self.sel_flexible, timeout=2000)
                if flex:
                    flex.click()
                    page.wait_for_timeout(self.settle_ms)
                    dom = self.read_months(page, max_months, debug_dir, tag + "-flex")
        finally:
            if debug_dir:
                try:
                    (debug_dir / f"{tag}.html").write_text(page.content(), encoding="utf-8")
                except Exception:  # noqa: BLE001
                    pass
                collector.dump(debug_dir, tag)

        merged = dict(collector.prices())
        for d, p in dom.items():
            merged[d] = min(p, merged.get(d, p))
        return [DayPrice(d, p, origin=origin, destination=destination) for d, p in sorted(merged.items())]


class ApiProvider(Provider):
    """Proveedor que lee los precios de un endpoint JSON público, sin navegador.

    Implementa `fetch_route(session, origin, destination, start, max_months, debug_dir)` y devuelve
    {fecha: precio}. Si la aerolínea no opera la ruta, devuelve {} (no es un error).
    """

    needs_browser = False
    timeout: int = 30

    @abstractmethod
    def fetch_route(self, session: requests.Session, origin: str, destination: str,
                    start: date, max_months: int, debug_dir: Path | None) -> dict[date, float]: ...

    def get_json(self, session: requests.Session, url: str, debug_dir: Path | None, tag: str, **params):
        """GET con errores legibles; devuelve None si la API responde 404 (ruta no operada)."""
        try:
            r = session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"{self.label}: sin conexión con la API ({type(exc).__name__})") from exc
        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / f"{tag}.json").write_text(
                json.dumps({"url": r.url, "status": r.status_code, "body": r.text[:3_000_000]}, ensure_ascii=False),
                encoding="utf-8",
            )
        if r.status_code == 404:
            return None
        if r.status_code in (403, 429):
            raise ProviderError(f"{self.label} rechaza la consulta (HTTP {r.status_code}, límite o anti-bot)")
        if not r.ok:
            raise ProviderError(f"{self.label}: la API respondió HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as exc:
            raise ProviderError(f"{self.label}: la API no devolvió JSON (¿ha cambiado?)") from exc

    def fetch_prices(self, page, origin, destination, max_months, debug_dir=None):
        with requests.Session() as session:
            session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
            found = self.fetch_route(session, origin, destination, date.today(), max_months, debug_dir)
        return [DayPrice(d, p, origin=origin, destination=destination) for d, p in sorted(found.items())]
