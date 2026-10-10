"""Regenera el catálogo de aeropuertos y países (`app/data/airports.csv` y `app/data/countries.csv`).

Fuente: OurAirports (https://ourairports.com/data/, dominio público). Solo se guardan los aeropuertos
con código IATA y vuelos regulares (`scheduled_service = yes`), sin helipuertos ni bases de hidroaviones.
Los nombres de los países salen en castellano de las traducciones ISO 3166 de `pycountry` (solo hace
falta para ejecutar este script, no para la app).

    pip install pycountry
    python scripts/build_places.py                    # descarga airports.csv de OurAirports
    python scripts/build_places.py --source airports.csv   # o a partir de una copia local

Las ciudades (TCI, LON…) y los grupos (Canarias, Baleares…) no salen de aquí: están en `app/places.py`.
"""
from __future__ import annotations

import argparse
import csv
import gettext
import io
import sys
import urllib.request
from pathlib import Path

URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OUT = Path(__file__).resolve().parent.parent / "app" / "data"
TYPES = {"large_airport": "L", "medium_airport": "M", "small_airport": "S"}

# Nombres oficiales de ISO demasiado largos o poco usados en España.
COUNTRY_NAMES = {
    "BO": "Bolivia", "VE": "Venezuela", "KR": "Corea del Sur", "KP": "Corea del Norte", "RU": "Rusia",
    "IR": "Irán", "TZ": "Tanzania", "TW": "Taiwán", "SY": "Siria", "LA": "Laos", "MD": "Moldavia",
    "PS": "Palestina", "FM": "Micronesia", "CI": "Costa de Marfil", "CD": "República Democrática del Congo",
    "CG": "República del Congo", "VA": "Ciudad del Vaticano", "BN": "Brunéi", "GB": "Reino Unido",
    "US": "Estados Unidos", "CZ": "Chequia", "VN": "Vietnam", "MK": "Macedonia del Norte",
    "XK": "Kosovo", "BQ": "Caribe Neerlandés", "SH": "Santa Elena", "UM": "Islas menores de EE. UU.",
}


def read_source(source: str | None) -> list[dict]:
    if source:
        text = Path(source).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(URL, timeout=60) as r:  # noqa: S310 - URL fija de OurAirports
            text = r.read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def country_name(code: str) -> str:
    if code in COUNTRY_NAMES:
        return COUNTRY_NAMES[code]
    import pycountry

    country = pycountry.countries.get(alpha_2=code)
    if not country:
        return code
    es = gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=["es"])
    return es.gettext(country.name)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", help="airports.csv de OurAirports ya descargado")
    args = ap.parse_args()

    airports = {}
    for row in read_source(args.source):
        iata = (row.get("iata_code") or "").strip().upper()
        if len(iata) != 3 or not iata.isalpha() or row.get("scheduled_service") != "yes" or row["type"] not in TYPES:
            continue
        prev = airports.get(iata)
        # Si hay códigos repetidos, se queda el aeropuerto más grande.
        if prev and "LMS".index(prev["type"]) <= "LMS".index(TYPES[row["type"]]):
            continue
        airports[iata] = {
            "iata": iata, "name": row["name"].strip(), "city": (row.get("municipality") or "").strip(),
            "country": row["iso_country"].strip().upper(), "type": TYPES[row["type"]],
            "keywords": " ".join((row.get("keywords") or "").replace(",", " ").split())[:120],
        }

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "airports.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["iata", "name", "city", "country", "type", "keywords"], lineterminator="\n")
        w.writeheader()
        w.writerows(airports[k] for k in sorted(airports))
    countries = sorted({a["country"] for a in airports.values()})
    with open(OUT / "countries.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["code", "name"])
        w.writerows([c, country_name(c)] for c in countries)
    print(f"{len(airports)} aeropuertos y {len(countries)} países en {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
