"""Vueling.

Precios: API JSON pública que usa la propia web para pintar el calendario
(`apiw.vueling.com/api/v1/availability`). Devuelve el precio más bajo de cada día de
~1 año en una sola petición y no necesita navegador. Verificado el 2026-09-30: responde
también a un cliente que no es navegador; 404 = Vueling no opera esa ruta.

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

    default_link_template = (
        "https://tickets.vueling.com/booking?o={origin}&d={destination}&dd={date}"
        "&adt=1&chd=0&inf=0&c=es-ES&cur=EUR"
    )

    def fetch_route(self, session, origin, destination, start, max_months, debug_dir):
        data = self.get_json(
            session, API_URL, debug_dir, f"vueling-{origin}-{destination}",
            originCode=origin, destinationCode=destination, providerName="DmpsRetrieveAvailabilityProvider",
            currencyCode="EUR", lowPriceClassificationPercentage=25,
        )
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
