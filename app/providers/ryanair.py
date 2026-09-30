"""Ryanair.

Precios: API JSON pública de tarifas (`/api/farfnd/v4/oneWayFares/.../cheapestPerDay`), la
misma que pinta el calendario de ryanair.com. Una petición por mes, sin navegador.
Verificado el 2026-09-30. No entiende códigos de ciudad (TCI): el checker los expande.

Ryanair vuela Sevilla ↔ Tenerife Sur (TFS), no Tenerife Norte, y la ruta es estacional
(en invierno no hay precios). Si la ruta no existe, la API devuelve todos los días sin
precio: se trata como «sin precios», no como error de la web.
"""
from __future__ import annotations

from datetime import date

from .base import ApiProvider, add_months

API_URL = "https://www.ryanair.com/api/farfnd/v4/oneWayFares/{origin}/{destination}/cheapestPerDay"


class RyanairProvider(ApiProvider):
    key = "ryanair"
    label = "Ryanair"
    color = "#073590"

    default_link_template = (
        "https://www.ryanair.com/es/es/trip/flights/select?adults=1&teens=0&children=0&infants=0"
        "&dateOut={date}&isReturn=false&originIata={origin}&destinationIata={destination}"
    )

    def fetch_route(self, session, origin, destination, start, max_months, debug_dir):
        out: dict[date, float] = {}
        url = API_URL.format(origin=origin, destination=destination)
        for i in range(max_months):
            month = add_months(start, i)
            data = self.get_json(session, url, debug_dir, f"ryanair-{origin}-{destination}-{month:%Y-%m}",
                                 outboundMonthOfDate=month.isoformat(), currency="EUR")
            if data is None:
                break
            for fare in (data.get("outbound") or {}).get("fares") or []:
                price = (fare.get("price") or {}).get("value")
                if not price or fare.get("unavailable") or fare.get("soldOut"):
                    continue
                day = date.fromisoformat(fare["day"])
                if day >= start:
                    out[day] = min(float(price), out.get(day, float(price)))
        return out
