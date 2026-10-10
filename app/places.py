"""Catálogo de lugares para origen y destino: aeropuertos, ciudades, países y grupos.

- **Aeropuertos** (código IATA de 3 letras): los de OurAirports (dominio público) con vuelos regulares,
  en `app/data/airports.csv` (se regenera con `scripts/build_places.py`).
- **Ciudades** (código IATA de ciudad, 3 letras: TCI, LON…): las de `CITIES`, con varios aeropuertos.
- **Países** (código ISO de 2 letras: ES, PT…): todos sus aeropuertos con vuelos regulares.
- **Grupos** (nombre corto en minúsculas: canarias, baleares…): conjuntos propios de `GROUPS`.

Una vigilancia guarda el código del lugar; `routes()` lo convierte en pares de aeropuertos reales.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

#: Pares de aeropuertos como máximo por vigilancia (origen × destino): más sería martillear las webs.
MAX_PAIRS = 60
CODE_MAX = 40

# código: (nombre, país, aeropuertos, otros nombres para la búsqueda)
CITIES: dict[str, tuple[str, str, tuple[str, ...], str]] = {
    "TCI": ("Tenerife", "ES", ("TFN", "TFS"), ""),
    "LON": ("Londres", "GB", ("LHR", "LGW", "STN", "LTN", "LCY", "SEN"), "London"),
    "PAR": ("París", "FR", ("CDG", "ORY", "BVA"), "Paris"),
    "MIL": ("Milán", "IT", ("MXP", "LIN", "BGY"), "Milano Milan"),
    "ROM": ("Roma", "IT", ("FCO", "CIA"), "Rome"),
    "STO": ("Estocolmo", "SE", ("ARN", "BMA", "NYO", "VST"), "Stockholm"),
    "REK": ("Reikiavik", "IS", ("KEF", "RKV"), "Reykjavik"),
    "BUH": ("Bucarest", "RO", ("OTP", "BBU"), "Bucharest Bucuresti"),
    "MOW": ("Moscú", "RU", ("SVO", "DME", "VKO"), "Moscow"),
    "NYC": ("Nueva York", "US", ("JFK", "EWR", "LGA"), "New York"),
    "WAS": ("Washington", "US", ("IAD", "DCA", "BWI"), ""),
    "CHI": ("Chicago", "US", ("ORD", "MDW"), ""),
    "YTO": ("Toronto", "CA", ("YYZ", "YTZ"), ""),
    "BUE": ("Buenos Aires", "AR", ("EZE", "AEP"), ""),
    "SAO": ("São Paulo", "BR", ("GRU", "CGH", "VCP"), "Sao Paulo"),
    "RIO": ("Río de Janeiro", "BR", ("GIG", "SDU"), "Rio de Janeiro"),
    "TYO": ("Tokio", "JP", ("HND", "NRT"), "Tokyo"),
    "SEL": ("Seúl", "KR", ("ICN", "GMP"), "Seoul"),
    "BJS": ("Pekín", "CN", ("PEK", "PKX"), "Beijing"),
}

# código: (nombre, aeropuertos, otros nombres para la búsqueda)
GROUPS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "canarias": ("Islas Canarias", ("LPA", "TFN", "TFS", "ACE", "FUE", "SPC", "VDE", "GMZ"), "Canary Islands"),
    "baleares": ("Islas Baleares", ("PMI", "IBZ", "MAH"), "Balearic Islands Mallorca Ibiza Menorca"),
    "andalucia": ("Andalucía", ("SVQ", "AGP", "GRX", "XRY", "LEI"), ""),
    "bruselas": ("Bruselas y Charleroi", ("BRU", "CRL"), "Brussels"),
    "oslo": ("Oslo y Torp", ("OSL", "TRF"), ""),
    "venecia": ("Venecia y Treviso", ("VCE", "TSF"), "Venice Venezia"),
    "glasgow": ("Glasgow y Prestwick", ("GLA", "PIK"), ""),
}

#: Nombre en castellano de la ciudad de algunos aeropuertos (OurAirports trae el municipio en inglés o local).
CITY_NAMES = {
    "LPA": "Gran Canaria", "FUE": "Fuerteventura", "ACE": "Lanzarote", "SPC": "La Palma", "VDE": "El Hierro",
    "GMZ": "La Gomera", "IBZ": "Ibiza", "MAH": "Menorca", "PMI": "Palma de Mallorca", "XRY": "Jerez",
    "LEI": "Almería", "RMU": "Murcia", "SCQ": "Santiago de Compostela", "BJZ": "Badajoz", "CDT": "Castellón",
    "LCG": "A Coruña", "EAS": "San Sebastián", "VIT": "Vitoria", "PNA": "Pamplona", "REU": "Reus", "GRO": "Girona",
    "LHR": "Londres", "LGW": "Londres", "STN": "Londres", "LTN": "Londres", "LCY": "Londres", "SEN": "Londres",
    "CDG": "París", "ORY": "París", "BVA": "París (Beauvais)", "LIS": "Lisboa", "OPO": "Oporto", "FAO": "Faro",
    "FCO": "Roma", "CIA": "Roma", "MXP": "Milán", "LIN": "Milán", "BGY": "Bérgamo", "VCE": "Venecia",
    "NAP": "Nápoles", "FLR": "Florencia", "TRN": "Turín", "ATH": "Atenas", "BRU": "Bruselas", "CRL": "Charleroi",
    "AMS": "Ámsterdam", "CPH": "Copenhague", "ARN": "Estocolmo", "WAW": "Varsovia", "KRK": "Cracovia",
    "PRG": "Praga", "VIE": "Viena", "GVA": "Ginebra", "ZRH": "Zúrich", "MUC": "Múnich", "FRA": "Fráncfort",
    "CGN": "Colonia", "DUS": "Düsseldorf", "HAM": "Hamburgo", "BER": "Berlín", "DUB": "Dublín",
    "EDI": "Edimburgo", "MAN": "Mánchester", "IST": "Estambul", "SAW": "Estambul", "MRS": "Marsella",
    "NCE": "Niza", "LYS": "Lyon", "BOD": "Burdeos", "TLS": "Toulouse", "RAK": "Marrakech", "CMN": "Casablanca",
    "JFK": "Nueva York", "EWR": "Nueva York", "LGA": "Nueva York", "MIA": "Miami", "CUN": "Cancún",
    "MEX": "Ciudad de México", "BOG": "Bogotá", "LIM": "Lima", "EZE": "Buenos Aires", "GRU": "São Paulo",
}

KIND_LABELS = {"airport": "Aeropuerto", "city": "Ciudad", "country": "País", "group": "Grupo"}


@dataclass(frozen=True)
class Place:
    code: str
    kind: str  # airport | city | country | group
    label: str  # «Sevilla (SVQ)», «Tenerife (todos)», «España»…
    detail: str  # nombre del aeropuerto y país, o los aeropuertos que incluye
    country: str
    airports: tuple[str, ...]
    search: str = ""  # texto normalizado para buscar

    def view(self) -> dict:
        return {"code": self.code, "kind": self.kind, "kind_label": KIND_LABELS[self.kind], "label": self.label,
                "detail": self.detail, "country": self.country, "airports": list(self.airports)}


def normalize(text: str) -> str:
    """Minúsculas y sin tildes, para buscar «sevilla» con «Sevilla» o «malaga» con «Málaga»."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _list(codes) -> str:
    codes = list(codes)
    return ", ".join(codes) if len(codes) <= 6 else ", ".join(codes[:6]) + f"… ({len(codes)})"


@lru_cache(maxsize=1)
def catalog() -> dict[str, Place]:
    """Todos los lugares por código (se carga una vez)."""
    with open(DATA_DIR / "countries.csv", encoding="utf-8") as f:
        countries = {r["code"]: r["name"] for r in csv.DictReader(f)}
    places: dict[str, Place] = {}
    by_country: dict[str, list[str]] = {}
    with open(DATA_DIR / "airports.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        country = countries.get(r["country"], r["country"])
        city = CITY_NAMES.get(r["iata"]) or r["city"] or r["name"]
        places[r["iata"]] = Place(
            r["iata"], "airport", f"{city} ({r['iata']})", f"{r['name']} · {country}", r["country"], (r["iata"],),
            normalize(f"{r['iata']} {city} {r['city']} {r['name']} {r['keywords']} {country}"),
        )
        by_country.setdefault(r["country"], []).append(r["iata"])

    for code, (name, country, codes, aliases) in CITIES.items():
        codes = tuple(c for c in codes if c in places)
        if code in places or not codes:  # nunca tapar un aeropuerto con el mismo código
            continue
        places[code] = Place(code, "city", f"{name} ({code})", f"Todos sus aeropuertos: {_list(codes)} · "
                             f"{countries.get(country, country)}", country, codes, normalize(f"{code} {name} {aliases}"))
    for code, (name, codes, aliases) in GROUPS.items():
        codes = tuple(c for c in codes if c in places)
        countries_in = {places[c].country for c in codes}
        places[code] = Place(code, "group", name, f"Aeropuertos: {_list(codes)}",
                             countries_in.pop() if len(countries_in) == 1 else "", codes, normalize(f"{name} {aliases}"))
    for code, name in countries.items():
        codes = tuple(sorted(by_country.get(code, ())))
        if codes:
            places[code] = Place(code, "country", name, f"{len(codes)} aeropuertos: {_list(codes)}", code, codes,
                                 normalize(f"{code} {name}"))
    return places


_CODE = re.compile(r"^(?:[A-Za-z]{2,3}|[a-z][a-z0-9-]{1,38})$")


def clean_code(raw: str) -> str:
    """Código tal como se guarda: IATA/ISO en mayúsculas, grupos en minúsculas."""
    raw = (raw or "").strip()
    if raw.lower() in GROUPS:
        return raw.lower()
    return raw.upper() if len(raw) <= 3 else raw


def get(code: str) -> Place | None:
    code = clean_code(code)
    return catalog().get(code) if _CODE.match(code) else None


def airports(code: str) -> tuple[str, ...]:
    """Aeropuertos reales de un lugar (un código desconocido se trata como aeropuerto)."""
    place = get(code)
    return place.airports if place else (clean_code(code),)


def routes(origin: str, destination: str) -> list[tuple[str, str]]:
    """Pares (origen, destino) de aeropuertos reales que cubre una vigilancia."""
    return [(o, d) for o, d in product(airports(origin), airports(destination)) if o != d]


def view(code: str) -> dict:
    place = get(code)
    return place.view() if place else {"code": code, "kind": "airport", "kind_label": KIND_LABELS["airport"],
                                       "label": code, "detail": "", "country": "", "airports": [code]}


_KIND_BONUS = {"city": 10, "group": 8, "country": 7, "airport": 0}
_SIZE_BONUS = {"L": 6, "M": 3, "S": 0}
HOME_COUNTRY = "ES"  # el panel es para gente que vuela desde España: sus aeropuertos, primero


def search(query: str, limit: int = 10) -> list[dict]:
    """Lugares que encajan con lo escrito, de más a menos relevante."""
    q = normalize(query).strip()
    if not q:
        return []
    words = q.split()
    scored = []
    for code, p in catalog().items():
        score = 0
        if normalize(code) == q:
            score = 100
        elif all(w in p.search for w in words):
            label = normalize(p.label)
            if label.startswith(q):
                score = 60
            elif any(t.startswith(words[0]) for t in re.split(r"[\s(),·-]+", label)):
                score = 40
            elif any(t.startswith(words[0]) for t in p.search.split()):
                score = 25
            else:
                score = 10
        if score:
            score += _KIND_BONUS[p.kind] + (_size(p) if p.kind == "airport" else 0) + (3 if p.country == HOME_COUNTRY else 0)
            scored.append((-score, p.label, p))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [p.view() for _s, _l, p in scored[:limit]]


def _size(place: Place) -> int:
    return _SIZE_BONUS.get(_airport_types().get(place.code, "S"), 0)


@lru_cache(maxsize=1)
def _airport_types() -> dict[str, str]:
    with open(DATA_DIR / "airports.csv", encoding="utf-8") as f:
        return {r["iata"]: r["type"] for r in csv.DictReader(f)}
