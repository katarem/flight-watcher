"""Wizz Air.

Sin navegador, con las APIs JSON que usa wizzair.com (sin verificar contra la web real desde este
repositorio: compruébalo en Proveedores → «Probar» desde la IP donde corre el panel):

- Versión de la API: `https://wizzair.com/buildnumber` devuelve «SSR https://be.wizzair.com/X.Y.Z».
- Cobertura («network»): `{api}/Api/asset/map?languageCode=es-es` lista las ciudades con sus conexiones.
- Precios: `POST {api}/Api/search/timetable` con un tramo de fechas (un mes por petición). Devuelve el
  precio más bajo por día en la moneda del aeropuerto de salida (HUF, PLN, EUR…): se convierte a euros.

Wizz Air es conocido por cortar a los clientes que no son un navegador (403/429): si pasa, la prueba de
acceso lo muestra como «bloqueado». No se usan técnicas de sigilo para evitarlo.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import date, timedelta

from .base import ApiProvider, DayPrice, ProviderError, add_months

BUILD_URL = "https://wizzair.com/buildnumber"
_API = re.compile(r"https://be\.wizzair\.com/[\d.]+")


class WizzAirProvider(ApiProvider):
    key = "wizzair"
    label = "Wizz Air"
    color = "#c6007e"
    coverage = "network"
    health_route = ("BCN", "BUD")
    notes = "Mapa de rutas y calendario por mes de la API de la web. Precios en la moneda de salida (se pasan a €)."

    default_link_template = "https://wizzair.com/es-es/booking/select-flight/{origin}/{destination}/{date}/null/1/0/0/null"

    _cache_lock = threading.Lock()
    _api: tuple[float, str] | None = None
    _map: tuple[float, dict[str, set[str]]] | None = None

    def api_base(self, session) -> str:
        """URL de la API versionada (se guarda 6 horas)."""
        with self._cache_lock:
            if self._api and time.monotonic() - self._api[0] < 6 * 3600:
                return self._api[1]
        r = self.request(session, "GET", BUILD_URL, headers={"Accept": "text/plain, */*"})
        m = _API.search(r.text if r is not None else "")
        if not m:
            raise ProviderError("Wizz Air: no encuentro la versión de su API en /buildnumber (¿ha cambiado?)")
        with self._cache_lock:
            type(self)._api = (time.monotonic(), m[0])
        return m[0]

    def routes_map(self, session) -> dict[str, set[str]]:
        with self._cache_lock:
            if self._map and time.monotonic() - self._map[0] < 3600:
                return self._map[1]
        data = self.get_json(session, f"{self.api_base(session)}/Api/asset/map", None, "", languageCode="es-es")
        if not isinstance(data, dict) or not isinstance(data.get("cities"), list):
            raise ProviderError("Wizz Air: el mapa de rutas tiene un formato inesperado (¿ha cambiado?)")
        out = {c["iata"]: {x.get("iata") for x in c.get("connections") or []} - {None}
               for c in data["cities"] if isinstance(c, dict) and c.get("iata")}
        with self._cache_lock:
            type(self)._map = (time.monotonic(), out)
        return out

    def network(self, session, origin):
        return self.routes_map(session).get(origin, set())

    def fetch_route(self, session, origin, destination, start, max_months, debug_dir):
        api = self.api_base(session)
        out: dict[date, DayPrice] = {}
        for i in range(max_months):
            lo = max(start, add_months(start, i))
            hi = add_months(start, i + 1) - timedelta(days=1)
            body = {
                "flightList": [{"departureStation": origin, "arrivalStation": destination,
                                "from": lo.isoformat(), "to": hi.isoformat()}],
                "priceType": "regular", "adultCount": 1, "childCount": 0, "infantCount": 0,
            }
            data = self.post_json(session, f"{api}/Api/search/timetable", body, debug_dir,
                                  f"wizzair-{origin}-{destination}-{lo:%Y-%m}")
            if data is None:
                break
            for f in data.get("outboundFlights") or []:
                price = f.get("price") or {}
                amount = price.get("amount")
                if f.get("priceType") != "price" or not amount:
                    continue
                day = date.fromisoformat(str(f.get("departureDate", ""))[:10])
                if day >= start and (day not in out or float(amount) < out[day].price):
                    out[day] = DayPrice(day, float(amount), currency=(price.get("currencyCode") or "EUR").upper())
        return out
