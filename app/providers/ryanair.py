"""Ryanair.

Precios: API JSON pública de tarifas (`/api/farfnd/v4/oneWayFares/.../cheapestPerDay`), la
misma que pinta el calendario de ryanair.com. Una petición por mes, sin navegador.
Verificado el 2026-09-30. No entiende códigos de ciudad (TCI): el checker los expande.

Cobertura («network»): la red de rutas que usa el buscador de la web
(`/api/views/locate/searchWidget/routes/es/airport/{origen}`): los destinos directos desde un aeropuerto.

Ryanair vuela Sevilla ↔ Tenerife Sur (TFS), no Tenerife Norte, y la ruta es estacional
(en invierno no hay precios). Si la ruta no existe, la API de tarifas devuelve todos los días sin
precio: se trata como «sin precios», no como error de la web.
"""
from __future__ import annotations

from datetime import date

from .base import ApiProvider, DayPrice, ProviderError, add_months

API_URL = "https://www.ryanair.com/api/farfnd/v4/oneWayFares/{origin}/{destination}/cheapestPerDay"
ROUTES_URL = "https://www.ryanair.com/api/views/locate/searchWidget/routes/es/airport/{origin}"


class RyanairProvider(ApiProvider):
    key = "ryanair"
    label = "Ryanair"
    color = "#073590"
    coverage = "network"
    health_route = ("SVQ", "BCN")
    verified = "2026-09-30"
    notes = "Tarifas por mes de la API del calendario; red de rutas del buscador de la web. Solo vuelos directos."

    default_link_template = (
        "https://www.ryanair.com/es/es/trip/flights/select?adults=1&teens=0&children=0&infants=0"
        "&dateOut={date}&isReturn=false&originIata={origin}&destinationIata={destination}"
    )

    def network(self, session, origin):
        data = self.get_json(session, ROUTES_URL.format(origin=origin), None, "")
        if data is None:
            return set()
        if not isinstance(data, list):
            raise ProviderError("Ryanair: la red de rutas tiene un formato inesperado (¿ha cambiado?)")
        return {(r.get("arrivalAirport") or {}).get("code") for r in data
                if isinstance(r, dict) and not r.get("connectingAirport")} - {None}

    def fetch_route(self, session, origin, destination, start, max_months, debug_dir):
        out: dict[date, DayPrice] = {}
        url = API_URL.format(origin=origin, destination=destination)
        for i in range(max_months):
            month = add_months(start, i)
            data = self.get_json(session, url, debug_dir, f"ryanair-{origin}-{destination}-{month:%Y-%m}",
                                 outboundMonthOfDate=month.isoformat(), currency="EUR")
            if data is None:
                break
            for fare in (data.get("outbound") or {}).get("fares") or []:
                price = fare.get("price") or {}
                value = price.get("value")
                if not value or fare.get("unavailable") or fare.get("soldOut"):
                    continue
                day = date.fromisoformat(fare["day"])
                if day >= start and (day not in out or float(value) < out[day].price):
                    out[day] = DayPrice(day, float(value), currency=(price.get("currencyCode") or "EUR").upper())
        return out
