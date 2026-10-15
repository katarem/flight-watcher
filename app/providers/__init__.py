"""Registro de proveedores.

Todos son scripts guardados en la BD (`scripted.py`): `scripted.reload()` los carga en `PROVIDERS` al arrancar y
cada vez que se crean, importan, editan o borran desde el panel. El orden del registro es el de todo el panel.
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

from .. import places
from .base import (
    COVERAGE_LABELS, ApiProvider, CalendarProvider, DayPrice, Provider, ProviderBlocked, ProviderError, ProviderTimeout,
)

PROVIDERS: dict[str, Provider] = {}

airports = places.airports
routes = places.routes


def ordered(keys) -> list[str]:
    """Claves conocidas en el orden del registro."""
    keys = set(keys)
    return [k for k in PROVIDERS if k in keys]


def link_for(provider_key: str, origin: str, destination: str, day: date) -> str:
    """Enlace de compra/búsqueda para un día concreto, con la plantilla del proveedor ("" si no está cargado)."""
    prov = PROVIDERS.get(provider_key)
    return prov.build_link(prov.default_link_template, origin, destination, day) if prov else ""


def stay_link_for(provider_key: str, destination: str, checkin: date, nights: int, guests, rooms: int = 1) -> str:
    """Enlace de búsqueda de una estancia (destino en texto, entrada, noches y viajeros), con la plantilla del
    proveedor: {destination} {date} (entrada) {checkout} {nights} {adults} {children} {rooms}…"""
    prov = PROVIDERS.get(provider_key)
    if not prov:
        return ""
    return prov.build_link(prov.default_link_template, "", quote(destination), checkin,
                           checkout=(checkin + timedelta(days=nights)).isoformat(), nights=nights,
                           adults=guests.adults, children=len(guests.child_ages), rooms=rooms)


__all__ = ["COVERAGE_LABELS", "PROVIDERS", "ApiProvider", "CalendarProvider", "DayPrice", "Provider",
           "ProviderBlocked", "ProviderError", "ProviderTimeout", "airports", "link_for", "ordered", "routes",
           "stay_link_for"]
