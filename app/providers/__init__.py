"""Registro de proveedores. Para añadir uno: importa la clase y añádela a la tupla."""
from __future__ import annotations

from datetime import date
from itertools import product

from .base import ApiProvider, CalendarProvider, DayPrice, Provider, ProviderError
from .ryanair import RyanairProvider
from .vueling import VuelingProvider

PROVIDERS: dict[str, Provider] = {p.key: p for p in (VuelingProvider(), RyanairProvider())}

#: Códigos IATA de ciudad → aeropuertos que se consultan por separado.
METRO_AREAS: dict[str, tuple[str, ...]] = {
    "TCI": ("TFN", "TFS"),  # Tenerife: Norte y Sur
}


def airports(code: str) -> tuple[str, ...]:
    return METRO_AREAS.get(code, (code,))


def routes(origin: str, destination: str) -> list[tuple[str, str]]:
    """Pares (origen, destino) de aeropuertos reales que cubre una vigilancia."""
    return [(o, d) for o, d in product(airports(origin), airports(destination)) if o != d]


def link_for(settings: dict, provider_key: str, origin: str, destination: str, day: date) -> str:
    """Enlace de compra/búsqueda para un día concreto, con la plantilla editable de Ajustes."""
    prov = PROVIDERS[provider_key]
    return prov.build_link(settings.get(f"link_{provider_key}", ""), origin, destination, day)


__all__ = ["METRO_AREAS", "PROVIDERS", "ApiProvider", "CalendarProvider", "DayPrice", "Provider",
           "ProviderError", "airports", "link_for", "routes"]
