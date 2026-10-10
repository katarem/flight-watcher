"""Vueling.

Precios: API JSON pública que usa la propia web para pintar el calendario
(`apiw.vueling.com/api/v1/availability`). Devuelve el precio más bajo de cada día de
~1 año en una sola petición y no necesita navegador. Verificado el 2026-09-30: responde
también a un cliente que no es navegador; 404 = Vueling no opera esa ruta.

Cobertura («probe»): se pregunta a esa misma API por cada ruta; un 404 significa que Vueling no la opera.

Enlace: formato oficial de deeplink de Vueling (o, d, dd obligatorios).
Residentes en islas/Ceuta pueden añadir `&dt=1` a la plantilla desde Ajustes.
"""
from __future__ import annotations

from datetime import date

from .base import ApiProvider, add_months

API_URL = "https://apiw.vueling.com/api/v1/availability"


class VuelingProvider(ApiProvider):
    key = "vueling"
    label = "Vueling"
    color = "#e8a800"
    coverage = "probe"
    health_route = ("SVQ", "TFN")
    verified = "2026-09-30"
    notes = ("Calendario de ~1 año en una petición. Bloquea las IP de centros de datos: ejecutar desde una IP "
             "residencial.")

    default_link_template = (
        "https://tickets.vueling.com/booking?o={origin}&d={destination}&dd={date}"
        "&adt=1&chd=0&inf=0&c=es-ES&cur=EUR"
    )

    def _availability(self, session, origin, destination, debug_dir=None):
        return self.get_json(
            session, API_URL, debug_dir, f"vueling-{origin}-{destination}",
            originCode=origin, destinationCode=destination, providerName="DmpsRetrieveAvailabilityProvider",
            currencyCode="EUR", lowPriceClassificationPercentage=25,
        )

    def probe(self, session, origin, destination):
        return self._availability(session, origin, destination) is not None

    def fetch_route(self, session, origin, destination, start, max_months, debug_dir):
        data = self._availability(session, origin, destination, debug_dir)
        if data is None:
            return {}
        end = add_months(start, max_months)
        out: dict[date, float] = {}
        for row in (data.get("availability") or {}).get("value") or []:
            if row.get("isInvalidPrice") or not row.get("price"):
                continue
            day = date.fromisoformat(row["departureDate"][:10])
            if start <= day < end:
                out[day] = min(float(row["price"]), out.get(day, float(row["price"])))
        return out
