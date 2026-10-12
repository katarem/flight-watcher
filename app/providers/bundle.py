"""Paquetes de proveedores: el formato para exportarlos e importarlos (archivo `.fwp` o enlace) y los incluidos.

Formato
-------
Texto UTF-8. La primera línea lo identifica y fija el separador; después, un bloque por proveedor: una línea con
el separador y sus datos en JSON (una sola línea) y, debajo, el script **tal cual**, sin escapar:

    #flight-watcher:proveedores v1 separador=%%fw%%
    # Comentarios opcionales (empiezan por #) antes del primer bloque.
    %%fw%% {"key": "vueling", "label": "Vueling", "color": "#e8a800", "coverage": "probe", …}
    \"\"\"Vueling.\"\"\"
    def fetch_route(api, origin, destination, start, max_months):
        …
    %%fw%% {"key": "ryanair", …}
    …

¿Por qué no JSON? Ocuparía casi lo mismo (lo grande es el código y en JSON solo se escapan saltos de línea y
comillas), pero el script quedaría en una sola línea ilegible. Así se puede leer, revisar y comparar (diff) el
código antes de importarlo, que es lo importante cuando ese código se va a ejecutar en el servidor. El separador
se elige al exportar para que ninguna línea de ningún script empiece por él.

Proveedores incluidos
---------------------
`catalog/incluidos.fwp` (Vueling y Ryanair, verificados) se crea en la BD la primera vez que arranca esta versión
(`seed()`); `catalog/sin-verificar.fwp` (Wizz Air y Google Flights) solo si alguna vigilancia ya los usaba;
`catalog/aireuropa.fwp` nunca (hay que rellenar sus credenciales). Todos (`CATALOGS`) se pueden importar desde el
panel (o desde su enlace en GitHub) para recuperarlos o actualizarlos.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

import requests

from .. import __version__
from . import stealth

log = logging.getLogger("providers")

MAGIC = "#flight-watcher:proveedores"
VERSION = 1
HEADER_RE = re.compile(r"^#flight-watcher:proveedores v(\d+) separador=(\S+)\s*$")
DEFAULT_SEPARATOR = "%%fw%%"
#: Lo que se exporta de cada proveedor además del código (la clave, la primera).
FIELDS = ("key", "label", "color", "coverage", "max_routes", "health_origin", "health_destination", "link_template",
          "notes", "min_interval", "stealth")
MAX_BYTES = 2_000_000
MAX_PROVIDERS = 100

CATALOG_DIR = Path(__file__).resolve().parent / "catalog"
INCLUDED = CATALOG_DIR / "incluidos.fwp"
EXTRA = CATALOG_DIR / "sin-verificar.fwp"
#: Paquetes del catálogo que el panel ofrece importar desde GitHub (archivo, nombre en el panel).
CATALOGS = (
    (INCLUDED.name, "Incluidos (Vueling y Ryanair)"),
    (EXTRA.name, "Sin verificar (Wizz Air y Google Flights)"),
    ("aireuropa.fwp", "Air Europa (sin verificar; hay que poner sus credenciales)"),
)
#: Dónde están publicados los paquetes incluidos (para importarlos o actualizarlos desde el panel).
CATALOG_URL = "https://raw.githubusercontent.com/katarem/flight-watcher/main/app/providers/catalog/"
#: Ajuste que marca que ya se crearon los proveedores incluidos (así, si se borran, no vuelven solos).
SEED_FLAG = "providers_seeded"
SEED_USER = "flight-watcher"


class BundleError(ValueError):
    """El texto no es un paquete de proveedores válido (el mensaje es para el usuario)."""


def dumps(rows: list[dict]) -> str:
    """Paquete con los proveedores dados (filas de `provider_scripts`)."""
    codes = [r["code"].replace("\r\n", "\n").rstrip("\n") + "\n" for r in rows]
    sep, n = DEFAULT_SEPARATOR, 1
    while any(line.startswith(sep) for code in codes for line in code.split("\n")):
        n += 1
        sep = f"%%fw{n}%%"
    out = [f"{MAGIC} v{VERSION} separador={sep}",
           f"# {len(rows)} proveedor{'es' if len(rows) != 1 else ''} exportado{'s' if len(rows) != 1 else ''} el "
           f"{date.today().isoformat()} desde flight-watcher {__version__}.",
           "# Cada bloque: una línea con el separador y los datos en JSON, y debajo el script de Python tal cual."]
    for row, code in zip(rows, codes):
        meta = {k: row.get(k) for k in FIELDS} | {"stealth": stealth.level(row.get("stealth")) or stealth.OFF}
        out.append(f"{sep} {json.dumps(meta, ensure_ascii=False)}")
        out.append(code.rstrip("\n"))
    return "\n".join(out) + "\n"


def loads(text: str) -> list[dict]:
    """Proveedores de un paquete: [{key, label, …, code}]. Lanza `BundleError` con un mensaje claro."""
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        raise BundleError(f"El paquete es demasiado grande (máximo {MAX_BYTES // 1_000_000} MB).")
    lines = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    m = HEADER_RE.match(lines[0].strip()) if lines else None
    if not m:
        if lines and lines[0].lstrip().startswith(("<", "{", "[")):
            raise BundleError("No es un paquete de proveedores (parece una página web o un JSON). Comprueba que el "
                              "enlace lleva al archivo en bruto (en GitHub, el botón «Raw»).")
        raise BundleError(f"No es un paquete de proveedores: la primera línea debe empezar por «{MAGIC} v1».")
    if int(m[1]) != VERSION:
        raise BundleError(f"El paquete es de una versión del formato que no conozco (v{m[1]}). Actualiza flight-watcher.")
    sep = m[2]
    out: list[dict] = []
    current: dict | None = None
    code: list[str] = []

    def close():
        if current is not None:
            current["code"] = "\n".join(code).strip("\n") + "\n"
            out.append(current)

    for n, line in enumerate(lines[1:], start=2):
        if line.startswith(sep + " ") or line == sep:
            close()
            try:
                meta = json.loads(line[len(sep):].strip() or "null")
            except ValueError as exc:
                raise BundleError(f"Línea {n}: los datos del proveedor no son JSON válido ({exc.msg}).") from exc
            if not isinstance(meta, dict) or not isinstance(meta.get("key"), str):
                raise BundleError(f"Línea {n}: faltan los datos del proveedor (al menos su clave, «key»).")
            current, code = {k: meta.get(k) for k in FIELDS if k in meta}, []
        elif current is None:
            if line.strip() and not line.startswith("#"):
                raise BundleError(f"Línea {n}: antes del primer proveedor solo puede haber comentarios (#).")
        else:
            code.append(line)
    close()
    if not out:
        raise BundleError("El paquete no tiene ningún proveedor.")
    if len(out) > MAX_PROVIDERS:
        raise BundleError(f"El paquete tiene demasiados proveedores (máximo {MAX_PROVIDERS}).")
    keys = [p["key"] for p in out]
    if dup := sorted({k for k in keys if keys.count(k) > 1}):
        raise BundleError(f"El paquete repite la clave {', '.join(dup)}.")
    return out


def raw_url(url: str) -> str:
    """Un enlace a un archivo de GitHub (…/blob/…) se cambia por el del archivo en bruto."""
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/blob/(.+)$", url)
    return f"https://raw.githubusercontent.com/{m[1]}/{m[2]}/{m[3]}" if m else url


def download(url: str) -> str:
    """Texto de un enlace (como mucho MAX_BYTES). Lanza `BundleError` con un mensaje claro. Los tests lo sustituyen."""
    from .base import USER_AGENT
    try:
        with requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain, */*"}, timeout=20,
                          stream=True) as r:
            if r.status_code == 404:
                raise BundleError("El enlace no existe (HTTP 404).")
            if not r.ok:
                raise BundleError(f"El enlace respondió HTTP {r.status_code}.")
            body = b""
            for chunk in r.iter_content(64 * 1024):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise BundleError(f"El archivo del enlace es demasiado grande (máximo {MAX_BYTES // 1_000_000} MB).")
    except requests.Timeout as exc:
        raise BundleError("El enlace no responde (tiempo agotado).") from exc
    except requests.RequestException as exc:
        raise BundleError(f"No se puede descargar el enlace ({type(exc).__name__}).") from exc
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError("El archivo del enlace no es texto UTF-8.") from exc


def values(p: dict) -> dict:
    """Columnas de `provider_scripts` de un proveedor de un paquete de confianza (los incluidos), sin validar."""
    return {
        "label": p.get("label") or p["key"], "color": (p.get("color") or "#64748b").lower(),
        "coverage": p.get("coverage") or "probe", "max_routes": p.get("max_routes"),
        "health_origin": (p.get("health_origin") or "MAD").upper(),
        "health_destination": (p.get("health_destination") or "BCN").upper(),
        "link_template": p.get("link_template") or "", "notes": p.get("notes") or "",
        "min_interval": float(p["min_interval"]) if p.get("min_interval") is not None else 1.5, "code": p["code"],
        "stealth": stealth.level(p.get("stealth")) or stealth.OFF,
    }


def seed() -> list[str]:
    """Primer arranque con los proveedores como scripts: crea los incluidos (y los del paquete sin verificar que ya
    use alguna vigilancia) y pasa a cada proveedor la plantilla de enlace que tuviera en Ajustes. Solo una vez:
    si después se borra uno, no vuelve solo. Devuelve las claves creadas."""
    from .. import db

    with db.connect() as con:
        if db.get_setting(con, SEED_FLAG):
            return []
        used = db.providers_in_use(con)
        links = db.pop_link_settings(con)
        existing = {r["key"]: r for r in db.list_provider_scripts(con)}
        bundled = [(p, INCLUDED) for p in loads(INCLUDED.read_text("utf-8"))]
        bundled += [(p, EXTRA) for p in loads(EXTRA.read_text("utf-8")) if p["key"] in used]
        created = []
        for p, path in bundled:
            if p["key"] in existing:
                continue
            row = values(p) | {"enabled": 1, "source": CATALOG_URL + path.name}
            if links.get(p["key"]):
                row["link_template"] = links[p["key"]]
            db.save_provider_script(con, p["key"], row, SEED_USER)
            created.append(p["key"])
        for key, tpl in links.items():  # plantillas de Ajustes de los proveedores propios que ya había
            if key in existing and tpl:
                db.save_provider_script(con, key, {"link_template": tpl}, existing[key]["updated_by"])
        db.set_setting(con, SEED_FLAG, "1")
    if created:
        log.info("Proveedores incluidos creados: %s", ", ".join(created))
    return created
