"""Proveedores propios: scripts de Python escritos desde el panel (zona «Proveedores», solo administradores).

Contrato
--------
El script es un módulo de Python que define:

    def fetch_route(api, origin, destination, start, max_months):
        # Precios de origin→destination (aeropuertos IATA) desde `start` (date) durante `max_months` meses.
        # Devuelve {date: precio en euros}, {date: DayPrice} o una lista de DayPrice; {} si no opera la ruta.

y, según la cobertura elegida en el formulario:

    network    def network(api, origin) -> códigos IATA con vuelo directo desde `origin`
    probe      def probe(api, origin, destination) -> True/False (¿opera la ruta?)
    universal  nada más (cubre cualquier ruta)

`api` (`ScriptApi`) hace las peticiones en el turno del proveedor, como los proveedores de serie: una a la
vez y con pausas, 403/429/página anti-bot → bloqueado, 404 → None y copia en diagnóstico si está activo.
En el espacio de nombres del script ya están `date`, `datetime`, `timedelta`, `re`, `json`, `math`, `DayPrice`,
`ProviderError`, `ProviderBlocked` y `add_months`.

Seguridad: el script se ejecuta dentro del proceso del servidor, con sus mismos permisos (puede leer la BD
y sus secretos). Por eso solo lo escribe un administrador, hay que confirmar la contraseña para guardar o
probar código, se anota quién lo guardó y `PROVIDER_SCRIPTS=0` desactiva todos (ni se cargan).
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import traceback
from datetime import date, datetime, timedelta

from .base import ApiProvider, DayPrice, ProviderBlocked, ProviderError, add_months

log = logging.getLogger("scripts")

#: `PROVIDER_SCRIPTS=0` desactiva los proveedores propios: no se cargan ni se pueden guardar ni probar.
ENABLED = os.getenv("PROVIDER_SCRIPTS", "1").strip() != "0"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,29}$")
MAX_CODE = 100_000
MAX_LOGS = 200
#: Función que exige cada tipo de cobertura, además de `fetch_route`.
COVERAGE_FUNCS = {"network": "network", "probe": "probe", "universal": None}

#: Lo que el script tiene a mano sin importarlo.
SCRIPT_GLOBALS = {
    "date": date, "datetime": datetime, "timedelta": timedelta, "re": re, "json": json, "math": math, "DayPrice": DayPrice,
    "ProviderError": ProviderError, "ProviderBlocked": ProviderBlocked, "add_months": add_months,
}

TEMPLATE = '''"""Proveedor propio. Rellena las URL y adapta la lectura del JSON a lo que devuelva la web."""

PRICES_URL = "https://www.ejemplo.com/api/precios/{origin}/{destination}"
ROUTES_URL = "https://www.ejemplo.com/api/rutas/{origin}"


def network(api, origin):
    """Cobertura «red de rutas»: destinos con vuelo directo desde `origin` (códigos IATA)."""
    data = api.get_json(ROUTES_URL.format(origin=origin))
    if data is None:  # 404: el aeropuerto no está en su red
        return []
    return [r["destino"] for r in data]


def fetch_route(api, origin, destination, start, max_months):
    """Precio más barato de cada día. {} si no opera la ruta."""
    out = {}
    for i in range(max_months):
        month = add_months(start, i)
        data = api.get_json(PRICES_URL.format(origin=origin, destination=destination),
                            mes=month.strftime("%Y-%m"), moneda="EUR")
        if data is None:  # 404: no opera la ruta
            break
        for dia in data.get("dias", []):
            if not dia.get("precio"):
                continue
            day = date.fromisoformat(dia["fecha"][:10])
            if day >= start:
                # Con otra moneda o con escalas: DayPrice(day, precio, currency="GBP", stops=1)
                out[day] = min(float(dia["precio"]), out.get(day, math.inf))
    return out
'''


class ScriptError(ProviderError):
    """El script no se puede cargar: error de sintaxis, fallo al ejecutarlo o no cumple el contrato."""


def filename(key: str) -> str:
    return f"<proveedor {key}>"


def describe(exc: BaseException, key: str) -> str:
    """«KeyError: 'precio' (línea 12 del script)»: el error con la última línea del script por la que pasó."""
    line = None
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == filename(key):
            line = frame.lineno
    text = f"{type(exc).__name__}: {exc}".splitlines()[0][:300]
    return text + (f" (línea {line} del script)" if line else "")


def load(key: str, code: str, coverage: str) -> dict:
    """Compila y ejecuta el script en un espacio de nombres propio y comprueba el contrato."""
    try:
        compiled = compile(code, filename(key), "exec")
    except SyntaxError as exc:
        raise ScriptError(f"Error de sintaxis en la línea {exc.lineno}: {exc.msg}") from exc
    ns = {"__name__": f"fw_script_{key}", **SCRIPT_GLOBALS}
    try:
        exec(compiled, ns)  # noqa: S102 - código de un administrador (ver la cabecera del módulo)
    except Exception as exc:  # noqa: BLE001 - un script roto no debe tumbar el servidor
        raise ScriptError(f"Falla al cargarlo: {describe(exc, key)}") from exc
    missing = [f for f in ("fetch_route", COVERAGE_FUNCS.get(coverage)) if f and not callable(ns.get(f))]
    if missing:
        raise ScriptError("Falta definir " + " y ".join(f"`{f}`" for f in missing)
                          + (f" (cobertura «{coverage}»)" if COVERAGE_FUNCS.get(coverage) in missing else "") + ".")
    return ns


class ScriptApi:
    """Lo que el script usa para hablar con la web: siempre en el turno del proveedor."""

    def __init__(self, prov: ScriptedProvider, session, debug_dir, tag: str):
        self._prov, self.session, self.debug_dir, self._tag, self._n = prov, session, debug_dir, tag, 0

    def _next(self) -> str:
        self._n += 1
        return f"{self._tag}-{self._n:02d}" if self.debug_dir else ""

    def request(self, method: str, url: str, **kw):
        """`requests.Response`, o None si la web responde 404."""
        return self._prov.request(self.session, method, url, self.debug_dir, self._next(), **kw)

    def get_json(self, url: str, **params):
        """JSON de un GET (None si 404)."""
        return self._prov.get_json(self.session, url, self.debug_dir, self._next(), **params)

    def post_json(self, url: str, body, **params):
        """JSON de un POST con cuerpo JSON (None si 404)."""
        return self._prov.post_json(self.session, url, body, self.debug_dir, self._next(), **params)

    def log(self, *parts):
        """Mensaje para el log del servidor y para la prueba del editor."""
        text = " ".join(str(p) for p in parts)[:500]
        log.info("[%s] %s", self._prov.key, text)
        if self._prov.logs is not None and len(self._prov.logs) < MAX_LOGS:
            self._prov.logs.append(text)


def _day(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError


def _price(value) -> float | None:
    """Precio válido (> 0) o None si no hay precio ese día."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError
    return float(value) if math.isfinite(value) and value > 0 else None


def normalize(result, label: str) -> dict[date, DayPrice | float]:
    """Comprueba lo que devuelve `fetch_route` y lo deja como {fecha: precio | DayPrice} (el mínimo por día)."""
    if result is None:
        return {}
    if isinstance(result, dict):
        items = list(result.items())
    elif isinstance(result, (list, tuple)):
        items = [(p.day if isinstance(p, DayPrice) else None, p) for p in result]
    else:
        raise ProviderError(f"{label}: `fetch_route` debe devolver un dict o una lista de DayPrice "
                            f"(devolvió {type(result).__name__})")
    out: dict[date, DayPrice | float] = {}
    for raw_day, value in items:
        try:
            day = _day(raw_day)
            if isinstance(value, DayPrice):
                value.day, value.currency = day, (value.currency or "EUR").upper()
                if _price(value.price) is None:
                    continue
                price = value.price
            else:
                price = value = _price(value)
                if price is None:
                    continue
        except (TypeError, ValueError) as exc:
            raise ProviderError(f"{label}: `fetch_route` devolvió un elemento no válido ({raw_day!r}: {value!r}); "
                                "se espera {fecha: precio} o DayPrice") from exc
        old = out.get(day)
        if old is None or price < (old.price if isinstance(old, DayPrice) else old):
            out[day] = value
    return out


class ScriptedProvider(ApiProvider):
    """Proveedor cuyo código es un script guardado en `provider_scripts`."""

    scripted = True

    def __init__(self, row: dict):
        self.key, self.label, self.color = row["key"], row["label"], row["color"]
        self.coverage = row["coverage"]
        self.max_routes = row.get("max_routes") if self.coverage == "universal" else None
        self.health_route = (row["health_origin"], row["health_destination"])
        self.default_link_template = row.get("link_template") or ""
        self.notes = row.get("notes") or ""
        self.min_interval = float(row.get("min_interval") if row.get("min_interval") is not None else 1.5)
        self.jitter = min(1.0, self.min_interval)
        self.updated_at, self.updated_by = row.get("updated_at"), row.get("updated_by")
        #: Mensajes de `api.log` (solo en la prueba del editor; None = solo al log del servidor).
        self.logs: list[str] | None = None
        self.ns = load(self.key, row["code"], self.coverage)

    def _call(self, name: str, *args):
        try:
            return self.ns[name](*args)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - el fallo del script es un error del proveedor, no de la ronda
            raise ProviderError(f"{self.label}: error en el script: {describe(exc, self.key)}") from exc

    def fetch_route(self, session, origin, destination, start, max_months, debug_dir, **_kw):
        api = ScriptApi(self, session, debug_dir, f"{self.key}-{origin}-{destination}")
        return normalize(self._call("fetch_route", api, origin, destination, start, max_months), self.label)

    def network(self, session, origin):
        found = self._call("network", ScriptApi(self, session, None, ""), origin) or []
        if isinstance(found, (str, bytes)) or not hasattr(found, "__iter__"):
            raise ProviderError(f"{self.label}: `network` debe devolver una lista de códigos IATA")
        codes = {str(c).strip().upper() for c in found if c}
        bad = sorted(c for c in codes if not re.fullmatch(r"[A-Z]{3}", c))
        if bad:
            raise ProviderError(f"{self.label}: `network` devolvió códigos que no son IATA: {', '.join(bad[:5])}")
        return codes

    def probe(self, session, origin, destination):
        return bool(self._call("probe", ScriptApi(self, session, None, ""), origin, destination))


# ----------------------------------------------------------------------- registro
#: Error de carga de cada script activo que no se pudo registrar (se muestra en la zona Proveedores).
ERRORS: dict[str, str] = {}
_reload_lock = threading.Lock()


def reload() -> None:
    """Sincroniza el registro `PROVIDERS` con los scripts activos de la BD (al arrancar y tras cada cambio).

    Se cambia el mismo diccionario (no se sustituye) para que todos los módulos que lo importaron lo vean.
    """
    from .. import db
    from . import PROVIDERS

    with _reload_lock:
        with db.connect() as con:
            rows = db.list_provider_scripts(con) if ENABLED else []
        new: dict[str, ScriptedProvider] = {}
        errors: dict[str, str] = {}
        for row in rows:
            if not row["enabled"]:
                continue
            if row["key"] in PROVIDERS and not getattr(PROVIDERS[row["key"]], "scripted", False):
                errors[row["key"]] = "La clave coincide con la de un proveedor de serie."
                continue
            try:
                new[row["key"]] = ScriptedProvider(row)
            except ScriptError as exc:
                errors[row["key"]] = str(exc)
                log.warning("No se carga el proveedor propio «%s»: %s", row["key"], exc)
        for key in [k for k, p in PROVIDERS.items() if getattr(p, "scripted", False) and k not in new]:
            del PROVIDERS[key]
        PROVIDERS.update(new)
        ERRORS.clear()
        ERRORS.update(errors)
