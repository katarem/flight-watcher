"""Catálogo de lugares para origen y destino.

Lugares de un transporte (donde empieza y acaba un trayecto):
- **Aeropuertos** (código IATA de 3 letras): los de OurAirports (dominio público) con vuelos regulares,
  en `app/data/airports.csv` (se regenera con `scripts/build_places.py`).
- **Estaciones**, **puertos** y **paradas de bus** (código de 4 a 10 letras o cifras): `app/data/stations.csv`,
  `ports.csv` y `stops.csv` (`NODE_FILES`). Llegan con sus transportes (3.x): hoy solo traen la cabecera.

Lugares que agrupan otros:
- **Ciudades** (código IATA de ciudad, 3 letras: TCI, LON…): las de `CITIES`, el nodo común de sus aeropuertos,
  estaciones, puertos y paradas (estos dicen su ciudad en la columna `city_code`).
- **Países** (código ISO de 2 letras: ES, PT…): todos sus lugares de cada transporte.
- **Grupos** (nombre corto en minúsculas: canarias, baleares…): conjuntos propios de `GROUPS`.

Una vigilancia guarda el código del lugar y su transporte; `routes()` lo convierte en pares de lugares reales de
ese transporte (una vigilancia de vuelos desde TCI consulta TFN y TFS, nunca el puerto de Santa Cruz).
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

#: Tipo de lugar → transporte (`kinds.KINDS`) de los lugares donde empieza y acaba un trayecto.
NODE_MODES = {"airport": "flight", "station": "train", "port": "ship", "stop": "bus"}
#: Lugares que no son aeropuertos (estaciones, puertos, paradas): `code,name,city,city_code,country,keywords`, con
#: `city_code` = código de la ciudad de `CITIES` que los agrupa (opcional). Llegan con sus transportes (3.x); si el
#: archivo no existe o está vacío, no hay lugares de ese tipo.
NODE_FILES = {"station": "stations.csv", "port": "ports.csv", "stop": "stops.csv"}
#: Código de un aeropuerto (IATA) y del resto de lugares de un transporte (UIC, UN/LOCODE, el de la web…: de 4 a 10
#: letras o cifras, así nunca chocan con un aeropuerto, un país o un grupo).
NODE_CODE = {"airport": re.compile(r"^[A-Z]{3}$")}
OTHER_NODE_CODE = re.compile(r"^[A-Z0-9]{4,10}$")
NODE_MAX = 10

KIND_LABELS = {"airport": "Aeropuerto", "station": "Estación", "port": "Puerto", "stop": "Parada de bus",
               "city": "Ciudad", "country": "País", "group": "Grupo"}
#: Plural de cada tipo de lugar, para describir lo que agrupa una ciudad, un país o un grupo.
NODE_PLURALS = {"airport": "aeropuertos", "station": "estaciones", "port": "puertos", "stop": "paradas"}


def node_code_ok(code: str, mode: str = "flight") -> bool:
    """¿Es un código válido para un lugar del transporte `mode`?"""
    node = next((k for k, m in NODE_MODES.items() if m == mode), "airport")
    return bool(NODE_CODE.get(node, OTHER_NODE_CODE).match(code or ""))


@dataclass(frozen=True)
class Place:
    code: str
    kind: str  # airport | station | port | stop (lugares de un transporte) | city | country | group
    label: str  # «Sevilla (SVQ)», «Tenerife (todos)», «España»…
    detail: str  # nombre del lugar y país, o lo que incluye
    country: str
    #: Lugares reales que incluye por transporte: {"flight": ("TFN", "TFS"), "ship": (…)}.
    nodes: tuple[tuple[str, tuple[str, ...]], ...]
    search: str = ""  # texto normalizado para buscar
    city: str = ""  # ciudad de `CITIES` que lo agrupa (solo lugares de un transporte)

    def nodes_for(self, mode: str) -> tuple[str, ...]:
        return dict(self.nodes).get(mode, ())

    @property
    def airports(self) -> tuple[str, ...]:
        return self.nodes_for("flight")

    @property
    def modes(self) -> list[str]:
        return [m for m, codes in self.nodes if codes]

    def view(self) -> dict:
        return {"code": self.code, "kind": self.kind, "kind_label": KIND_LABELS[self.kind], "label": self.label,
                "detail": self.detail, "country": self.country, "modes": self.modes,
                "nodes": {m: list(c) for m, c in self.nodes if c}, "airports": list(self.airports)}


def normalize(text: str) -> str:
    """Minúsculas y sin tildes, para buscar «sevilla» con «Sevilla» o «malaga» con «Málaga»."""
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def _list(codes) -> str:
    codes = list(codes)
    return ", ".join(codes) if len(codes) <= 6 else ", ".join(codes[:6]) + f"… ({len(codes)})"


def _by_mode(codes, places: dict) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Lugares reales agrupados por transporte, en el orden de `NODE_MODES`."""
    out: dict[str, list[str]] = {}
    for c in codes:
        if c in places:
            out.setdefault(NODE_MODES[places[c].kind], []).append(c)
    return tuple((m, tuple(out[m])) for m in NODE_MODES.values() if m in out)


def _contents(nodes, only_airports_text: str) -> str:
    """«Todos sus aeropuertos: TFN, TFS» o, con varios transportes, «Aeropuertos: … · Puertos: …»."""
    node_of = {m: k for k, m in NODE_MODES.items()}
    if len(nodes) == 1 and nodes[0][0] == "flight":
        return f"{only_airports_text}: {_list(nodes[0][1])}"
    return " · ".join(f"{NODE_PLURALS[node_of[m]].capitalize()}: {_list(c)}" for m, c in nodes)


def _read(name: str) -> list[dict]:
    path = DATA_DIR / name
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def catalog() -> dict[str, Place]:
    """Todos los lugares por código (se carga una vez)."""
    countries = {r["code"]: r["name"] for r in _read("countries.csv")}
    places: dict[str, Place] = {}
    by_country: dict[str, list[str]] = {}
    by_city: dict[str, list[str]] = {}
    for r in _read("airports.csv"):
        country = countries.get(r["country"], r["country"])
        city = CITY_NAMES.get(r["iata"]) or r["city"] or r["name"]
        places[r["iata"]] = Place(
            r["iata"], "airport", f"{city} ({r['iata']})", f"{r['name']} · {country}", r["country"],
            (("flight", (r["iata"],)),),
            normalize(f"{r['iata']} {city} {r['city']} {r['name']} {r['keywords']} {country}"),
        )
        by_country.setdefault(r["country"], []).append(r["iata"])
    for kind, name in NODE_FILES.items():
        for r in _read(name):
            code = (r.get("code") or "").strip().upper()
            if not OTHER_NODE_CODE.match(code) or code in places:
                continue
            country = countries.get(r["country"], r["country"])
            city = r.get("city") or r["name"]
            places[code] = Place(
                code, kind, f"{r['name']} ({city})" if city and city not in r["name"] else r["name"],
                f"{KIND_LABELS[kind]} · {city} · {country}" if city else f"{KIND_LABELS[kind]} · {country}",
                r["country"], ((NODE_MODES[kind], (code,)),),
                normalize(f"{code} {r['name']} {city} {r.get('keywords', '')} {country}"),
                (r.get("city_code") or "").upper(),
            )
            by_country.setdefault(r["country"], []).append(code)
            if places[code].city:
                by_city.setdefault(places[code].city, []).append(code)

    for code, (name, country, codes, aliases) in CITIES.items():
        nodes = _by_mode([*codes, *by_city.get(code, ())], places)
        if code in places or not nodes:  # nunca tapar un aeropuerto con el mismo código
            continue
        places[code] = Place(code, "city", f"{name} ({code})", f"{_contents(nodes, 'Todos sus aeropuertos')} · "
                             f"{countries.get(country, country)}", country, nodes, normalize(f"{code} {name} {aliases}"))
    for code, (name, codes, aliases) in GROUPS.items():
        nodes = _by_mode(codes, places)
        countries_in = {places[c].country for m, cs in nodes for c in cs}
        places[code] = Place(code, "group", name, _contents(nodes, "Aeropuertos"),
                             countries_in.pop() if len(countries_in) == 1 else "", nodes, normalize(f"{name} {aliases}"))
    for code, name in countries.items():
        nodes = _by_mode(sorted(by_country.get(code, ())), places)
        if nodes:
            if len(nodes) == 1 and nodes[0][0] == "flight":
                detail = f"{len(nodes[0][1])} aeropuertos: {_list(nodes[0][1])}"
            else:
                detail = _contents(nodes, "")
            places[code] = Place(code, "country", name, detail, code, nodes, normalize(f"{code} {name}"))
    return places


_CODE = re.compile(r"^(?:[A-Za-z]{2,3}|[a-z][a-z0-9-]{1,38}|[A-Z0-9]{4,10})$")


def clean_code(raw: str) -> str:
    """Código tal como se guarda: IATA/ISO y el resto de lugares en mayúsculas, grupos en minúsculas."""
    raw = (raw or "").strip()
    if raw.lower() in GROUPS:
        return raw.lower()
    if len(raw) <= 3 or raw.upper() in catalog():
        return raw.upper()
    return raw


def get(code: str) -> Place | None:
    code = clean_code(code)
    return catalog().get(code) if _CODE.match(code) else None


def nodes(code: str, mode: str = "flight") -> tuple[str, ...]:
    """Lugares reales de un transporte que incluye un lugar (un código desconocido se trata como uno de ellos)."""
    place = get(code)
    return place.nodes_for(mode) if place else (clean_code(code),)


def airports(code: str) -> tuple[str, ...]:
    """Aeropuertos reales de un lugar (un código desconocido se trata como aeropuerto)."""
    return nodes(code, "flight")


def routes(origin: str, destination: str, mode: str = "flight") -> list[tuple[str, str]]:
    """Pares (origen, destino) de lugares reales del transporte `mode` que cubre una vigilancia."""
    return [(o, d) for o, d in product(nodes(origin, mode), nodes(destination, mode)) if o != d]


def view(code: str) -> dict:
    place = get(code)
    return place.view() if place else {"code": code, "kind": "airport", "kind_label": KIND_LABELS["airport"],
                                       "label": code, "detail": "", "country": "", "modes": ["flight"],
                                       "nodes": {"flight": [code]}, "airports": [code]}


_KIND_BONUS = {"city": 10, "group": 8, "country": 7, "airport": 0, "station": 0, "port": 0, "stop": 0}
_SIZE_BONUS = {"L": 6, "M": 3, "S": 0}
HOME_COUNTRY = "ES"  # el panel es para gente que vuela desde España: sus aeropuertos, primero


def search(query: str, limit: int = 10, mode: str | None = None) -> list[dict]:
    """Lugares que encajan con lo escrito, de más a menos relevante. Con `mode`, solo los que tienen lugares de ese
    transporte (una vigilancia de vuelos no ofrece estaciones ni una ciudad sin aeropuerto)."""
    q = normalize(query).strip()
    if not q:
        return []
    words = q.split()
    scored = []
    for code, p in catalog().items():
        if mode and not p.nodes_for(mode):
            continue
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
