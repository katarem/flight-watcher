"""Registro de proveedores. Para añadir uno: importa la clase y añádela a la tupla."""
from __future__ import annotations

from datetime import date

from .. import places
from .base import (
    COVERAGE_LABELS, ApiProvider, CalendarProvider, DayPrice, Provider, ProviderBlocked, ProviderError,
)
from .google import GoogleFlightsProvider
from .ryanair import RyanairProvider
from .vueling import VuelingProvider
from .wizzair import WizzAirProvider

PROVIDERS: dict[str, Provider] = {
    p.key: p for p in (VuelingProvider(), RyanairProvider(), WizzAirProvider(), GoogleFlightsProvider())
}

airports = places.airports
routes = places.routes


def ordered(keys) -> list[str]:
    """Claves conocidas en el orden del registro."""
    keys = set(keys)
    return [k for k in PROVIDERS if k in keys]


def link_for(settings: dict, provider_key: str, origin: str, destination: str, day: date) -> str:
    """Enlace de compra/búsqueda para un día concreto, con la plantilla editable de Ajustes."""
    prov = PROVIDERS[provider_key]
    return prov.build_link(settings.get(f"link_{provider_key}", ""), origin, destination, day)


__all__ = ["COVERAGE_LABELS", "PROVIDERS", "ApiProvider", "CalendarProvider", "DayPrice", "Provider",
           "ProviderBlocked", "ProviderError", "airports", "link_for", "ordered", "routes"]
