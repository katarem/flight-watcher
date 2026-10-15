"""Estancias (2.1): el alojamiento como un tramo más del viaje (`watches.role = "stay"`, transporte `hotel`).

Una estancia tiene un **destino en texto libre** («Puerto de la Cruz», «Costa Adeje»: lo resuelve el buscador de cada
web), sus webs y sus **filtros** (`StayFilters`, JSON en `watches.filters`): habitaciones, tipos de alojamiento,
alojamiento entero, puntuación y estrellas mínimas, régimen, cancelación gratuita y servicios. Los viajeros son los
del viaje (`app/party.py`).

El precio de una estancia depende de la fecha de entrada **y** de las noches, y en las webs de alojamiento cada
combinación suele ser una búsqueda. Para no disparar los bloqueos, cada ronda consulta como mucho `MAX_QUERIES`
combinaciones por web (`plan`): en un viaje con transporte, las fechas de ida con el transporte más barato; en uno de
solo estancia, las fechas de entrada de la ventana (o de los próximos `HORIZON_DAYS`). Primero las que nunca se han
consultado y después las más antiguas, así que en unas pocas rondas se cubre toda la ventana (los precios valen
`trips.STALE_DAYS` días).

Contrato de los scripts de alojamiento (ver `providers/scripted.py`): `fetch_stay(api, destination, checkin, nights,
guests, filters)` devuelve una lista de `StayOffer`. Los filtros se aplican en la búsqueda cuando la web lo permite;
el checker vuelve a filtrar con lo que diga cada oferta (un dato que falta, `None`, se da por bueno).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, timedelta

#: Longitud máxima del destino de una estancia (texto libre).
PLACE_MAX = 120
#: Combinaciones (fecha de entrada × noches) que se consultan como mucho por web y ronda.
MAX_QUERIES = 40
#: Fechas de ida (las del transporte más barato) entre las que se eligen las de la estancia en un viaje con transporte.
MAX_CANDIDATES = 200
#: Sin «Hasta», un viaje de solo estancia mira las entradas de los próximos días.
HORIZON_DAYS = 60
MAX_ROOMS = 9

TYPES = {
    "hotel": "Hotel", "aparthotel": "Aparthotel", "apartment": "Apartamento", "house": "Casa o chalé",
    "rural": "Casa rural", "guesthouse": "Pensión o B&B", "hostal": "Hostal", "hostel": "Albergue",
    "camping": "Camping",
}
BOARDS = {
    "room_only": "Solo alojamiento", "breakfast": "Desayuno", "half_board": "Media pensión",
    "full_board": "Pensión completa", "all_inclusive": "Todo incluido",
}
AMENITIES = {
    "pool": "Piscina", "parking": "Parking", "kitchen": "Cocina", "ac": "Aire acondicionado", "wifi": "Wifi",
    "pets": "Admite mascotas",
}


@dataclass
class StayOffer:
    """Un alojamiento disponible para la búsqueda (entrada, noches, viajeros y filtros), con su precio **total**.

    `rating` sobre 10 (una web que puntúa sobre 5 lo multiplica por 2), `type` y `board` con las claves de
    `TYPES` y `BOARDS` (otro valor se guarda tal cual y no cuenta para los filtros), `amenities` con las de
    `AMENITIES`. Lo que la web no diga se deja en None (pasa los filtros).
    """
    price: float                  # total de la estancia para todos los viajeros, en `currency`
    currency: str = "EUR"
    name: str = ""
    type: str = ""
    rating: float | None = None
    stars: int | None = None
    board: str = ""
    free_cancel: bool | None = None
    #: Alojamiento entero (True) o habitación (False).
    entire: bool | None = None
    amenities: list[str] | None = None
    url: str = ""
    # Lo rellena el checker:
    day: date | None = None
    nights: int = 0
    price_eur: float | None = None

    def details(self) -> dict:
        """Lo que se guarda de la oferta (`prices.offer`) para enseñarla en el panel y en los avisos."""
        out = {"name": self.name, "type": self.type, "rating": self.rating, "stars": self.stars, "board": self.board,
               "free_cancel": self.free_cancel, "entire": self.entire, "url": self.url}
        return {k: v for k, v in out.items() if v not in (None, "")}


@dataclass(frozen=True)
class StayFilters:
    rooms: int = 1
    #: Tipos aceptados (vacío = cualquiera).
    types: tuple[str, ...] = ()
    #: Solo alojamientos enteros (nada de habitaciones en una casa compartida).
    entire: bool = False
    min_rating: float | None = None
    min_stars: int | None = None
    #: Regímenes aceptados (vacío = cualquiera).
    boards: tuple[str, ...] = ()
    free_cancel: bool = False
    #: Servicios imprescindibles.
    amenities: tuple[str, ...] = field(default_factory=tuple)

    def view(self) -> dict:
        return {"rooms": self.rooms, "types": list(self.types), "entire": self.entire, "min_rating": self.min_rating,
                "min_stars": self.min_stars, "boards": list(self.boards), "free_cancel": self.free_cancel,
                "amenities": list(self.amenities)}

    def to_json(self) -> str:
        return json.dumps(self.view())

    def accepts(self, offer: StayOffer) -> bool:
        """¿Cumple la oferta los filtros? Lo que la oferta no dice (None o un tipo desconocido) se da por bueno."""
        if self.types and offer.type in TYPES and offer.type not in self.types:
            return False
        if self.boards and offer.board in BOARDS and offer.board not in self.boards:
            return False
        if self.entire and offer.entire is False:
            return False
        if self.min_rating is not None and offer.rating is not None and offer.rating < self.min_rating:
            return False
        if self.min_stars is not None and offer.stars is not None and offer.stars < self.min_stars:
            return False
        if self.free_cancel and offer.free_cancel is False:
            return False
        if self.amenities and offer.amenities is not None and not set(self.amenities) <= set(offer.amenities):
            return False
        return True

    def describe(self) -> str:
        """«1 habitación · hotel o apartamento · nota 8+ · desayuno · cancelación gratuita»."""
        parts = [f"{self.rooms} habitación" if self.rooms == 1 else f"{self.rooms} habitaciones"]
        if self.types:
            parts.append(" o ".join(TYPES[t].lower() for t in self.types))
        if self.entire:
            parts.append("alojamiento entero")
        if self.min_stars:
            parts.append(f"{self.min_stars}★ o más")
        if self.min_rating is not None:
            parts.append(f"nota {self.min_rating:g}+")
        if self.boards:
            parts.append(" o ".join(BOARDS[b].lower() for b in self.boards))
        if self.free_cancel:
            parts.append("cancelación gratuita")
        if self.amenities:
            parts.append(", ".join(AMENITIES[a].lower() for a in self.amenities))
        return " · ".join(parts)


DEFAULT = StayFilters()


def load(raw) -> StayFilters:
    """Los filtros de `watches.filters` (JSON o dict); los de por defecto si no hay."""
    if not raw:
        return DEFAULT
    d = json.loads(raw) if isinstance(raw, str) else raw
    return StayFilters(int(d.get("rooms") or 1), tuple(d.get("types") or ()), bool(d.get("entire")),
                       d.get("min_rating"), d.get("min_stars"), tuple(d.get("boards") or ()),
                       bool(d.get("free_cancel")), tuple(d.get("amenities") or ()))


def parse(raw, errors: list[str]) -> StayFilters:
    """Filtros del formulario o errores en `errors`."""
    raw = raw if isinstance(raw, dict) else {}

    def number(key, label, lo, hi, kind=float):
        text = str(raw.get(key) if raw.get(key) is not None else "").strip().replace(",", ".")
        if not text:
            return None
        try:
            v = kind(float(text)) if kind is int else float(text)
            if not lo <= v <= hi or not math.isfinite(v):
                raise ValueError
            return v
        except ValueError:
            errors.append(f"{label} debe ser un número entre {lo} y {hi}.")
            return None

    def chosen(key, allowed: dict, label):
        values = raw.get(key) or []
        if not isinstance(values, list):
            values = []
        bad = [v for v in values if v not in allowed]
        if bad:
            errors.append(f"{label} desconocido: {', '.join(map(str, bad))}.")
        return tuple(k for k in allowed if k in values)

    rooms = number("rooms", "Las habitaciones", 1, MAX_ROOMS, int) or 1
    return StayFilters(
        rooms=rooms, types=chosen("types", TYPES, "Tipo de alojamiento"), entire=bool(raw.get("entire")),
        min_rating=number("min_rating", "La puntuación mínima", 0, 10),
        min_stars=number("min_stars", "Las estrellas mínimas", 1, 5, int),
        boards=chosen("boards", BOARDS, "Régimen"), free_cancel=bool(raw.get("free_cancel")),
        amenities=chosen("amenities", AMENITIES, "Servicio"),
    )


def options() -> dict:
    """Lo que el formulario necesita para los filtros."""
    def items(d):
        return [{"key": k, "label": v} for k, v in d.items()]
    return {"types": items(TYPES), "boards": items(BOARDS), "amenities": items(AMENITIES), "max_rooms": MAX_ROOMS,
            "place_max": PLACE_MAX}


def offer_text(offer: dict) -> str:
    """«Hotel Playa (hotel, 4★, 8,6) · desayuno · cancelación gratuita»: una oferta guardada, para los avisos."""
    extra = [TYPES.get(offer.get("type", ""), offer.get("type", "")).lower()]
    if offer.get("stars"):
        extra.append(f"{offer['stars']}★")
    if offer.get("rating") is not None:
        extra.append(f"{offer['rating']:g}".replace(".", ","))
    name = offer.get("name") or "Alojamiento"
    inner = ", ".join(e for e in extra if e)
    text = f"{name} ({inner})" if inner else name
    if offer.get("board"):
        text += f" · {BOARDS.get(offer['board'], offer['board']).lower()}"
    if offer.get("free_cancel"):
        text += " · cancelación gratuita"
    return text


# ------------------------------------------------------------------- qué consultar
def plan(trip: dict, today: date, out_by_day: dict | None, ret_by_day: dict | None,
         checked: dict[tuple[str, int], str], limit: int | None = None) -> list[tuple[date, int]]:
    """Combinaciones (entrada, noches) que consultar en esta ronda para una web.

    `out_by_day`/`ret_by_day`: precios por día de la ida y de la vuelta (None = el viaje no tiene ese tramo).
    `checked`: {(entrada ISO, noches): última consulta} de esa web. Con transporte, solo las fechas de ida con
    precio (y vuelta para esas noches), de la más barata a la más cara; sin transporte, todas las de la ventana.
    """
    lo = max(today, date.fromisoformat(trip["date_from"])) if trip.get("date_from") else today
    hi = date.fromisoformat(trip["date_to"]) if trip.get("date_to") else None
    nights = range(trip["min_nights"], trip["max_nights"] + 1)
    candidates: list[tuple[float, date, int]] = []
    if out_by_day is not None:
        for day, row in out_by_day.items():
            d = date.fromisoformat(day)
            if d < lo or (hi and d > hi):
                continue
            for n in nights:
                back = (d + timedelta(days=n)).isoformat()
                if ret_by_day is not None and back not in ret_by_day:
                    continue
                cost = row["price"] + (ret_by_day[back]["price"] if ret_by_day is not None else 0)
                candidates.append((cost, d, n))
        candidates = sorted(candidates)[:MAX_CANDIDATES]
    else:
        end = hi or today + timedelta(days=HORIZON_DAYS)
        d = lo
        while d <= end:
            candidates += [(0.0, d, n) for n in nights]
            d += timedelta(days=1)
    order = {(d, n): i for i, (_c, d, n) in enumerate(candidates)}
    picked = sorted(order, key=lambda k: (checked.get((k[0].isoformat(), k[1]), ""), order[k]))
    return picked[:MAX_QUERIES if limit is None else limit]
