"""Viajeros de un viaje (2.1): cuántos son, sus edades y sus descuentos (residente, familia numerosa).

Los viajeros son del **viaje**, no de un tramo: cambian el precio de los transportes (cuántas plazas, qué
descuentos) y el del alojamiento (adultos, niños con sus edades). Se guardan como JSON en `trips.party`; NULL (los
viajes anteriores a la 2.1) = un adulto sin descuentos.

A los scripts de los proveedores les llega el objeto `Party` como `passengers` (transportes, si su `fetch_route` lo
acepta) o `guests` (alojamiento). Un proveedor de transporte que no lo acepta da el precio de **un adulto**: el
checker lo multiplica por las plazas y lo marca como estimado (sin los descuentos).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

#: Descuento de residente (vuelos y barcos nacionales con los territorios no peninsulares).
REGIONS = {"canarias": "Canarias", "baleares": "Baleares", "ceuta": "Ceuta", "melilla": "Melilla"}
#: Familia numerosa (categoría del título): vacío = no.
LARGE_FAMILY = {"": "No", "general": "General", "special": "Especial"}
#: Viajeros como máximo (lo que admiten casi todas las webs en una reserva).
MAX_TRAVELERS = 9
ADULT_AGE = 18
INFANT_AGE = 2


@dataclass(frozen=True)
class Traveler:
    #: Edad (0–17) de un niño; None = adulto.
    age: int | None = None
    #: Región del descuento de residente (`REGIONS`); "" = sin descuento.
    resident: str = ""

    @property
    def adult(self) -> bool:
        return self.age is None or self.age >= ADULT_AGE

    def view(self) -> dict:
        return {"age": self.age, "resident": self.resident}


@dataclass(frozen=True)
class Party:
    """Los viajeros. Para los scripts: `adults`, `children` (edades de 2 a 17), `infants` (menores de 2), `seats`
    (plazas: todos menos los bebés), `residents` ({región: cuántos}), `large_family` y `travelers`."""
    travelers: tuple[Traveler, ...] = field(default_factory=lambda: (Traveler(),))
    large_family: str = ""

    @property
    def size(self) -> int:
        return len(self.travelers)

    @property
    def adults(self) -> int:
        return sum(t.adult for t in self.travelers)

    @property
    def children(self) -> list[int]:
        """Edades de los niños con plaza (de 2 a 17 años)."""
        return [t.age for t in self.travelers if not t.adult and t.age >= INFANT_AGE]

    @property
    def child_ages(self) -> list[int]:
        """Edades de todos los menores (bebés incluidos): lo que piden los alojamientos."""
        return [t.age for t in self.travelers if not t.adult]

    @property
    def infants(self) -> int:
        return sum(not t.adult and t.age < INFANT_AGE for t in self.travelers)

    @property
    def seats(self) -> int:
        return self.size - self.infants

    @property
    def residents(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self.travelers:
            if t.resident:
                out[t.resident] = out.get(t.resident, 0) + 1
        return out

    @property
    def simple(self) -> bool:
        """Un adulto sin descuentos: el precio de cualquier web vale tal cual."""
        return self.size == 1 and self.adults == 1 and not self.residents and not self.large_family

    def to_json(self) -> str | None:
        """JSON para `trips.party` (None si es el de por defecto: un adulto sin descuentos)."""
        if self.simple:
            return None
        return json.dumps({"travelers": [t.view() for t in self.travelers], "large_family": self.large_family})

    def view(self) -> dict:
        return {"travelers": [t.view() for t in self.travelers], "large_family": self.large_family,
                "size": self.size, "adults": self.adults, "seats": self.seats, "label": self.describe()}

    def describe(self) -> str:
        """«2 adultos y 1 niño (8 años) · 1 residente en Canarias · familia numerosa general»."""
        parts = [f"{self.adults} adulto" + ("s" if self.adults != 1 else "")]
        minors = sorted(self.child_ages)
        if minors:
            ages = ", ".join(f"{a} año" + ("s" if a != 1 else "") if a else "menos de 1 año" for a in minors)
            parts[0] += f" y {len(minors)} " + ("niño" if len(minors) == 1 else "niños") + f" ({ages})"
        out = [parts[0]]
        for region, n in self.residents.items():
            out.append(f"{n} residente" + ("s" if n != 1 else "") + f" en {REGIONS.get(region, region)}")
        if self.large_family:
            out.append(f"familia numerosa {LARGE_FAMILY[self.large_family].lower()}")
        return " · ".join(out)


DEFAULT = Party()


def load(raw) -> Party:
    """El `Party` de un viaje a partir de `trips.party` (JSON o dict ya decodificado); por defecto, un adulto."""
    if not raw:
        return DEFAULT
    data = json.loads(raw) if isinstance(raw, str) else raw
    travelers = tuple(Traveler(t.get("age"), t.get("resident") or "") for t in data.get("travelers") or [])
    return Party(travelers or DEFAULT.travelers, data.get("large_family") or "")


def parse(raw, errors: list[str]) -> Party:
    """Viajeros del formulario ({"travelers": [{"age", "resident"}], "large_family"}) o errores en `errors`."""
    if not raw:
        return DEFAULT
    if not isinstance(raw, dict):
        errors.append("Los viajeros no son válidos.")
        return DEFAULT
    items = raw.get("travelers") or []
    if not isinstance(items, list) or not items:
        errors.append("El viaje necesita al menos un viajero.")
        return DEFAULT
    if len(items) > MAX_TRAVELERS:
        errors.append(f"Como mucho {MAX_TRAVELERS} viajeros por viaje (lo que admiten las webs en una reserva).")
        items = items[:MAX_TRAVELERS]
    travelers = []
    for i, t in enumerate(items, 1):
        t = t if isinstance(t, dict) else {}
        age = t.get("age")
        if age in ("", None):
            age = None
        else:
            try:
                age = int(str(age))
                if not 0 <= age < ADULT_AGE:
                    raise ValueError
            except ValueError:
                errors.append(f"La edad del viajero {i} debe ser de 0 a {ADULT_AGE - 1} años (o adulto).")
                age = None
        resident = str(t.get("resident") or "").strip().lower()
        if resident and resident not in REGIONS:
            errors.append(f"Residencia desconocida en el viajero {i} ({', '.join(REGIONS.values())}).")
            resident = ""
        travelers.append(Traveler(age, resident))
    if not any(t.adult for t in travelers):
        errors.append("Tiene que viajar al menos un adulto.")
    large = str(raw.get("large_family") or "").strip().lower()
    if large not in LARGE_FAMILY:
        errors.append("Categoría de familia numerosa desconocida (general o especial).")
        large = ""
    return Party(tuple(travelers), large)


def options() -> dict:
    """Lo que el formulario necesita para elegir viajeros."""
    return {"regions": [{"key": k, "label": v} for k, v in REGIONS.items()],
            "large_family": [{"key": k, "label": v} for k, v in LARGE_FAMILY.items()],
            "max_travelers": MAX_TRAVELERS, "adult_age": ADULT_AGE}
