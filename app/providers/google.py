"""Google Flights.

Cobertura «universal»: Google Flights busca cualquier ruta (directa o con escalas) entre todas las
aerolíneas, así que no hay red que consultar; lo que limita es el número de pares por vigilancia.

Precios: la llamada interna `GetCalendarGraph` que pinta el calendario de precios de
google.com/travel/flights (el precio más bajo de cada día de un tramo de fechas), sin navegador y con
nuestro User-Agent honesto. Es una API sin documentar: **sin verificar contra Google desde este
repositorio** (compruébalo en Proveedores → «Probar»). Si cambia el formato, la ronda falla con un
error claro en lugar de guardar datos malos. Acepta el filtro de escalas de la vigilancia.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from .base import ApiProvider, DayPrice, ProviderError

API_URL = ("https://www.google.com/_/FlightsFrontendUi/data/travel.frontend.flights.FlightsFrontendService/"
           "GetCalendarGraph")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: Días por petición (el calendario de Google no admite tramos muy largos).
WINDOW_DAYS = 60
#: Escalas de la vigilancia → filtro de Google (0 = cualquiera, 1 = directo, 2 = ≤ 1 escala, 3 = ≤ 2).
_STOPS = {None: 0, 0: 1, 1: 2, 2: 3}


def request_body(origin: str, destination: str, start: date, end: date, max_stops: int | None) -> str:
    """`f.req` de un viaje de solo ida, 1 adulto, turista, entre dos aeropuertos."""
    segment = [[[[origin, 0]]], [[[destination, 0]]], None, _STOPS.get(max_stops, 0), None, None,
               start.isoformat(), None, None, None, None, None, None, None, 3]
    query = [None, [None, None, 2, None, [], 1, [1, 0, 0, 0], None, None, None, None, None, None, [segment],
                    None, None, None, 1], [start.isoformat(), end.isoformat()]]
    return json.dumps([None, json.dumps(query, separators=(",", ":"))], separators=(",", ":"))


def _price(node) -> float | None:
    """Primer `[null, número]` dentro de un nodo (así viene el precio de cada día)."""
    if isinstance(node, list):
        if len(node) >= 2 and node[0] is None and isinstance(node[1], (int, float)) and not isinstance(node[1], bool):
            return float(node[1])
        for item in node:
            p = _price(item)
            if p is not None:
                return p
    return None


def _walk(node, out: dict[date, float]):
    if not isinstance(node, list):
        return
    if node and isinstance(node[0], str) and _ISO.match(node[0]):
        p = _price(node[1:])
        if p is not None and 1 <= p <= 20000:
            d = date.fromisoformat(node[0])
            out[d] = min(p, out.get(d, p))
            return
    for item in node:
        _walk(item, out)


def parse_response(text: str) -> dict[date, float]:
    """Precios por día de la respuesta (`)]}'` + trozos JSON con [["wrb.fr", …, "<json>"]])."""
    out: dict[date, float] = {}
    found = False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            chunk = json.loads(line)
        except ValueError:
            continue
        for item in chunk if isinstance(chunk, list) else []:
            if isinstance(item, list) and len(item) > 2 and item[0] == "wrb.fr" and isinstance(item[2], str):
                found = True
                try:
                    _walk(json.loads(item[2]), out)
                except ValueError:
                    continue
    if not found:
        raise ProviderError("Google Flights: respuesta con un formato inesperado (¿ha cambiado la API?)")
    return out


class GoogleFlightsProvider(ApiProvider):
    key = "google"
    label = "Google Flights"
    color = "#1a73e8"
    coverage = "universal"
    max_routes = 12
    stops_filter = True
    min_interval = 3.0
    jitter = 2.0
    health_route = ("SVQ", "TFN")
    notes = ("Busca en todas las aerolíneas (también con escalas). API interna del calendario, sin documentar; "
             "como mucho 12 pares de aeropuertos por vigilancia.")

    default_link_template = (
        "https://www.google.com/travel/flights?hl=es&gl=ES&curr=EUR"
        "&q=Vuelos%20de%20{origin}%20a%20{destination}%20el%20{date}%20solo%20ida"
    )

    def fetch_route(self, session, origin, destination, start, max_months, debug_dir, max_stops=None):
        end = start + timedelta(days=max_months * 30)
        out: dict[date, DayPrice] = {}
        lo = start
        while lo < end:
            hi = min(end, lo + timedelta(days=WINDOW_DAYS - 1))
            r = self.request(
                session, "POST", API_URL, debug_dir, f"google-{origin}-{destination}-{lo:%Y-%m-%d}",
                params={"hl": "es", "gl": "ES", "curr": "EUR", "rt": "c"},
                data={"f.req": request_body(origin, destination, lo, hi, max_stops)},
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "Accept": "*/*"},
            )
            if r is None:
                raise ProviderError("Google Flights: la API del calendario ya no existe (HTTP 404)")
            for d, p in parse_response(r.text).items():
                if lo <= d <= hi:
                    # El calendario no dice cuántas escalas tiene el más barato, solo que cumple el filtro.
                    out[d] = DayPrice(d, p, currency="EUR", stops=0 if max_stops == 0 else None)
            lo = hi + timedelta(days=1)
        return out
