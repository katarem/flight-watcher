"""Tipos de transporte y de proveedor: lo que hasta la 1.8 daba por hecho que todo eran vuelos.

Cada vigilancia es de un **transporte** (`watches.kind`) y cada proveedor de un **tipo** (`provider_scripts.kind`):
una vigilancia (un tramo de un viaje) de vuelos solo usa proveedores de vuelos y sus lugares son aeropuertos (o
ciudades, países y grupos con aeropuertos). Desde la 2.0 todo vive en los viajes del panel (`/trips`): el
transporte de un viaje es el de su tramo de ida.

Los transportes comparten el contrato de los scripts (`fetch_route`, ver `providers/scripted.py`) y el modelo de
precios; el alojamiento (`hotel`, 2.1) tendrá el suyo. Un tipo «disponible» se puede elegir en el panel; el resto
está declarado para que el modelo de datos ya lo admita, pero llega en su versión (barcos 3.0, trenes 3.1, buses 3.2,
alojamiento 2.1). Añadir un transporte = una entrada en `KINDS` y sus lugares (`places.NODE_FILES`).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Kind:
    key: str
    label: str        # «Vuelos»
    noun: str         # «vuelo»
    plural: str       # «vuelos»
    node: str         # tipo de lugar donde empieza y acaba (places.Place.kind); "" = no es un transporte
    node_label: str   # «aeropuerto»
    contract: str     # función principal del script
    available: bool   # se puede elegir ya (vigilancias y proveedores)
    since: str = ""   # versión prevista si aún no está disponible
    transport: bool = True


KINDS: dict[str, Kind] = {
    "flight": Kind("flight", "Vuelos", "vuelo", "vuelos", "airport", "aeropuerto", "fetch_route", True),
    "ship": Kind("ship", "Barcos", "barco", "barcos", "port", "puerto", "fetch_route", False, "3.0"),
    "train": Kind("train", "Trenes", "tren", "trenes", "station", "estación", "fetch_route", False, "3.1"),
    "bus": Kind("bus", "Buses", "bus", "buses", "stop", "parada", "fetch_route", False, "3.2"),
    "hotel": Kind("hotel", "Alojamiento", "estancia", "estancias", "", "", "fetch_stay", False, "2.1",
                  transport=False),
}
DEFAULT = "flight"
#: Longitud máxima de la clave (columnas `kind`).
KEY_MAX = 10


def get(key: str | None) -> Kind:
    """El tipo de la clave (el de vuelos si está vacía: datos anteriores a la 1.9)."""
    return KINDS[key or DEFAULT]


def transports(available_only: bool = True) -> list[Kind]:
    return [k for k in KINDS.values() if k.transport and (k.available or not available_only)]


def provider_kinds() -> list[str]:
    """Tipos que puede tener un proveedor: los transportes (todos comparten contrato, así que se puede ir escribiendo
    uno de trenes antes de que haya vigilancias de trenes). El alojamiento, cuando tenga su contrato (2.1)."""
    return [k.key for k in KINDS.values() if k.transport]


def view(k: Kind) -> dict:
    return {"key": k.key, "label": k.label, "noun": k.noun, "plural": k.plural, "node": k.node,
            "node_label": k.node_label, "available": k.available, "since": k.since,
            "transport": k.transport}
