"""Registro de proveedores.

Todos son scripts guardados en la BD (`scripted.py`): `scripted.reload()` los carga en `PROVIDERS` al arrancar y
cada vez que se crean, importan, editan o borran desde el panel. El orden del registro es el de todo el panel.
"""
from __future__ import annotations

from datetime import date

from .. import places
from .base import (
    COVERAGE_LABELS, ApiProvider, CalendarProvider, DayPrice, Provider, ProviderBlocked, ProviderError,
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


__all__ = ["COVERAGE_LABELS", "PROVIDERS", "ApiProvider", "CalendarProvider", "DayPrice", "Provider",
           "ProviderBlocked", "ProviderError", "airports", "link_for", "ordered", "routes"]
