"""Proveedores: cada uno es un script de Python guardado en la BD (zona «Proveedores», solo administradores).

No hay proveedores «de serie»: Vueling y Ryanair son scripts como cualquier otro que se crean al arrancar la primera
vez (`bundle.seed()`) y se pueden editar, exportar o borrar desde el panel.

Contrato
--------
El script es un módulo de Python que define:

    def fetch_route(api, origin, destination, start, max_months):
        # Precios de origin→destination (aeropuertos IATA) desde `start` (date) durante `max_months` meses.
        # Devuelve {date: precio en euros}, {date: DayPrice} o una lista de DayPrice; {} si no opera la ruta.
        # Si además acepta `max_stops` (fetch_route(…, max_months, max_stops=None)), recibe el máximo de escalas
        # de la vigilancia (0 = solo directos, None = sin límite) y filtra él mismo.

y, según la cobertura elegida en el formulario:

    network    def network(api, origin) -> códigos IATA con vuelo directo desde `origin`
    probe      def probe(api, origin, destination) -> True/False (¿opera la ruta?)
    universal  nada más (cubre cualquier ruta)

`api` (`ScriptApi`) hace las peticiones en el turno del proveedor: una a la vez y con pausas, 403/429/página
anti-bot → bloqueado, 404 → None y copia en diagnóstico si está activo. Una petición que no responde en 30 s se
repite una vez (otra vez sin respuesta → `ProviderTimeout`); para una web lenta, `timeout=` en segundos
(`api.post_json(url, body, timeout=60)`, `api.get_json(url, timeout=60, **params)`, `api.request(…, timeout=60)`). En el espacio de nombres del script ya
están `date`, `datetime`, `timedelta`, `re`, `json`, `math`, `DayPrice`, `ProviderError`, `ProviderBlocked` y
`add_months`. `api.log(…)` y `print(…)` escriben en el log del servidor y en la consola de la prueba del editor,
que además muestra cada petición (URL, estado, tiempo, tamaño y forma del JSON) y en qué línea falla el script.
Con «Aplicar medidas anti-bot» (`stealth`), sus peticiones se hacen pasar por las de una persona con Chrome (ver
`stealth.py`) y `api.stealth` lo indica.

Seguridad: el script se ejecuta dentro del proceso del servidor, con sus mismos permisos (puede leer la BD y sus
secretos). Por eso solo lo escribe o importa un administrador, hay que confirmar la contraseña para guardar,
importar o probar código, se anota quién lo guardó y `PROVIDER_SCRIPTS=0` bloquea el código desde el panel (se
siguen ejecutando los proveedores que ya hay, pero no se pueden crear, importar, cambiar su código ni probarlos).
"""
from __future__ import annotations

import inspect
import json
import linecache
import logging
import math
import os
import re
import threading
import time
import traceback
from collections.abc import Callable
from datetime import date, datetime, timedelta

from . import stealth
from .base import ApiProvider, DayPrice, ProviderBlocked, ProviderError, ProviderTimeout, add_months

log = logging.getLogger("scripts")

#: `PROVIDER_SCRIPTS=0` bloquea el código desde el panel: no se puede crear, importar, cambiar ni probar.
EDITABLE = os.getenv("PROVIDER_SCRIPTS", "1").strip() != "0"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,29}$")
#: Claves que no puede tener un proveedor (son rutas de la API: /providers/health, /providers/export…).
RESERVED_KEYS = {"health", "test", "export", "import", "revalidate", "new"}
MAX_CODE = 100_000
#: Función que exige cada tipo de cobertura, además de `fetch_route`.
COVERAGE_FUNCS = {"network": "network", "probe": "probe", "universal": None}

#: Lo que el script tiene a mano sin importarlo.
SCRIPT_GLOBALS = {
    "date": date, "datetime": datetime, "timedelta": timedelta, "re": re, "json": json, "math": math, "DayPrice": DayPrice,
    "ProviderError": ProviderError, "ProviderBlocked": ProviderBlocked, "add_months": add_months,
}

TEMPLATE = '''"""Proveedor nuevo. Rellena las URL y adapta la lectura del JSON a lo que devuelva la web."""

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
        # Web lenta: api.get_json(url, timeout=60, …) espera 60 s en vez de 30.
        api.log("mes", month.strftime("%Y-%m"), "→", len(data.get("dias", [])), "días")
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


def script_frames(exc: BaseException, key: str) -> list[str]:
    """Las líneas del script por las que pasó el error, para la consola: «línea 12, en fetch_route: x = d["a"]»."""
    return [f"línea {f.lineno}, en {f.name}: {(f.line or '').strip()}"[:300]
            for f in traceback.extract_tb(exc.__traceback__) if f.filename == filename(key)]


def load(key: str, code: str, coverage: str, printer: Callable[..., None] | None = None) -> dict:
    """Compila y ejecuta el script en un espacio de nombres propio y comprueba el contrato."""
    try:
        compiled = compile(code, filename(key), "exec")
    except SyntaxError as exc:
        raise ScriptError(f"Error de sintaxis en la línea {exc.lineno}: {exc.msg}") from exc
    # Para que los errores muestren el texto de la línea del script (como con un archivo de verdad).
    linecache.cache[filename(key)] = (len(code), None, code.splitlines(True), filename(key))
    ns = {"__name__": f"fw_script_{key}", **SCRIPT_GLOBALS}
    if printer:
        ns["print"] = printer
    try:
        exec(compiled, ns)  # noqa: S102 - código de un administrador (ver la cabecera del módulo)
    except Exception as exc:  # noqa: BLE001 - un script roto no debe tumbar el servidor
        raise ScriptError(f"Falla al cargarlo: {describe(exc, key)}") from exc
    missing = [f for f in ("fetch_route", COVERAGE_FUNCS.get(coverage)) if f and not callable(ns.get(f))]
    if missing:
        raise ScriptError("Falta definir " + " y ".join(f"`{f}`" for f in missing)
                          + (f" (cobertura «{coverage}»)" if COVERAGE_FUNCS.get(coverage) in missing else "") + ".")
    return ns


def _shown_url(url: str, params: dict | None) -> str:
    if not params:
        return url
    from urllib.parse import urlencode
    return url + ("&" if "?" in url else "?") + urlencode({k: v for k, v in params.items() if v is not None})


def _size(r) -> str:
    n = len(getattr(r, "content", None) or (r.text or "").encode())
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} KB"


def shape(data) -> str:
    """Forma de un JSON en pocas palabras, para la consola: «objeto con 3 claves: a, b, c»."""
    if isinstance(data, dict):
        keys = list(data)
        more = f"… (+{len(keys) - 8})" if len(keys) > 8 else ""
        return f"objeto con {len(keys)} clave{'s' if len(keys) != 1 else ''}" + (
            f": {', '.join(map(str, keys[:8]))}{more}" if keys else "")
    if isinstance(data, list):
        first = f"; el primero es {shape(data[0])}" if data and isinstance(data[0], (dict, list)) else ""
        return f"lista de {len(data)} elemento{'s' if len(data) != 1 else ''}{first}"
    return f"{type(data).__name__} {str(data)[:80]!r}"


class ScriptApi:
    """Lo que el script usa para hablar con la web: siempre en el turno del proveedor.

    Con la consola de la prueba del editor encendida (`prov.console`), cuenta cada petición y su respuesta.
    """

    def __init__(self, prov: ScriptedProvider, session, debug_dir, tag: str):
        self._prov, self.session, self.debug_dir, self._tag, self._n = prov, session, debug_dir, tag, 0
        #: True si el proveedor tiene activadas las medidas anti-bot (el script puede adaptarse).
        self.stealth = prov.stealth

    def _next(self) -> str:
        self._n += 1
        return f"{self._tag}-{self._n:02d}" if self.debug_dir else ""

    def request(self, method: str, url: str, **kw):
        """`requests.Response`, o None si la web responde 404. Sin respuesta a tiempo, se repite una vez.

        `timeout=` (segundos) para esta petición; por defecto, 30.
        """
        prov = self._prov
        for attempt in (1, 2):
            if prov.stopped:
                raise ProviderError(f"{prov.label}: prueba cortada, no se hacen más peticiones")
            prov.trace("http", f"{method.upper()} {_shown_url(url, kw.get('params'))}")
            started = time.monotonic()
            try:
                r = prov.request(self.session, method, url, self.debug_dir, self._next(), **kw)
                break
            except ProviderTimeout as exc:
                if attempt == 2:
                    prov.trace("error", f"  ✗ {exc}")
                    raise
                prov.trace("warn", f"  ✗ {exc}; lo repito una vez")
            except ProviderError as exc:
                prov.trace("error", f"  ✗ {exc}")
                raise
        ms = int((time.monotonic() - started) * 1000)
        if r is None:
            prov.trace("warn", f"  ← 404 en {ms} ms: no existe (la función recibe None)")
        else:
            ctype = (r.headers.get("content-type") or "").split(";")[0] or "sin tipo"
            prov.trace("ok", f"  ← {r.status_code} en {ms} ms · {_size(r)} · {ctype}")
        return r

    def _json(self, r):
        try:
            data = self._prov._json(r)
        except ProviderError:
            self._prov.trace("error", f"  ✗ no es JSON; empieza por: {(r.text or '')[:200]!r}")
            raise
        if r is not None:
            self._prov.trace("info", f"  JSON: {shape(data)}")
        return data

    def get_json(self, url: str, timeout: float | None = None, **params):
        """JSON de un GET (None si 404). `timeout`: segundos de espera (30 si no se indica)."""
        return self._json(self.request("GET", url, params=params, timeout=timeout))

    def post_json(self, url: str, body, timeout: float | None = None, **params):
        """JSON de un POST con cuerpo JSON (None si 404). `timeout`: segundos de espera (30 si no se indica)."""
        return self._json(self.request("POST", url, params=params, json=body, timeout=timeout))

    def log(self, *parts):
        """Mensaje para el log del servidor y para la consola de la prueba del editor."""
        self._prov.say(*parts)


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


#: Quien recibe las trazas de la consola de la prueba: (nivel, texto). Niveles: info, ok, warn, error, http, script.
Console = Callable[[str, str], None]


class ScriptedProvider(ApiProvider):
    """Proveedor cuyo código es un script guardado en `provider_scripts`."""

    def __init__(self, row: dict, console: Console | None = None):
        self.key, self.label, self.color = row["key"], row["label"], row["color"]
        self.coverage = row["coverage"]
        self.max_routes = row.get("max_routes") if self.coverage == "universal" else None
        self.health_route = (row["health_origin"], row["health_destination"])
        self.default_link_template = row.get("link_template") or ""
        self.notes = row.get("notes") or ""
        self.min_interval = float(row.get("min_interval") if row.get("min_interval") is not None else 1.5)
        self.jitter = min(1.0, self.min_interval)
        #: «Aplicar medidas anti-bot»: sesión que se hace pasar por Chrome y pausas más variables (ver stealth.py).
        self.stealth = bool(row.get("stealth"))
        if self.stealth:
            self.jitter = max(self.jitter, 2.0)
        self._shared: stealth.StealthClient | None = None
        self._session_lock = threading.Lock()
        self.updated_at, self.updated_by = row.get("updated_at"), row.get("updated_by")
        #: Consola de la prueba del editor (None en las rondas: solo el log del servidor).
        self.console = console
        #: True cuando se corta la prueba del editor: el script que sigue en segundo plano ya no hace peticiones.
        self.stopped = False
        self.ns = load(self.key, row["code"], self.coverage, printer=self.say)
        try:
            params = inspect.signature(self.ns["fetch_route"]).parameters
        except (TypeError, ValueError):
            params = {}
        #: Si `fetch_route` acepta `max_stops`, recibe el filtro de escalas de la vigilancia.
        self.stops_filter = "max_stops" in params
        if self.stealth:
            self.trace("info", stealth.describe())

    def new_session(self):
        """Con medidas anti-bot, una sesión «de navegador» sobre el mismo cliente (y sus cookies) mientras no caduque."""
        if not self.stealth:
            return super().new_session()
        with self._session_lock:
            if self._shared is None or self._shared.expired():
                if self._shared is not None:
                    self._shared.close()
                self._shared = stealth.StealthClient(self.trace)
            return stealth.StealthSession(self._shared, self.key, self.trace)

    def trace(self, level: str, text: str):
        self.pulse()
        if self.console is not None:
            self.console(level, text[:2000])

    def say(self, *parts, **_kw):
        """`api.log(…)` y `print(…)` del script: al log del servidor y a la consola de la prueba."""
        text = " ".join(str(p) for p in parts)[:1000]
        log.info("[%s] %s", self.key, text)
        self.trace("script", text)

    def _call(self, name: str, *args, **kw):
        try:
            return self.ns[name](*args, **kw)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - el fallo del script es un error del proveedor, no de la ronda
            for line in script_frames(exc, self.key):
                self.trace("error", f"  {line}")
            raise ProviderError(f"{self.label}: error en el script: {describe(exc, self.key)}") from exc

    def fetch_route(self, session, origin, destination, start, max_months, debug_dir, **kw):
        api = ScriptApi(self, session, debug_dir, f"{self.key}-{origin}-{destination}")
        kw = {"max_stops": kw.get("max_stops")} if self.stops_filter else {}
        return normalize(self._call("fetch_route", api, origin, destination, start, max_months, **kw), self.label)

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
    """Sincroniza el registro `PROVIDERS` con los proveedores activos de la BD (al arrancar y tras cada cambio).

    Se cambia el mismo diccionario (no se sustituye) para que todos los módulos que lo importaron lo vean. Lo que
    no es un script (los dobles de los tests) se deja como está.
    """
    from .. import db
    from . import PROVIDERS

    with _reload_lock:
        with db.connect() as con:
            rows = db.list_provider_scripts(con)
        new: dict[str, ScriptedProvider] = {}
        errors: dict[str, str] = {}
        for row in rows:
            if not row["enabled"]:
                continue
            try:
                new[row["key"]] = ScriptedProvider(row)
            except ScriptError as exc:
                errors[row["key"]] = str(exc)
                log.warning("No se carga el proveedor «%s»: %s", row["key"], exc)
        for key in [k for k, p in PROVIDERS.items() if isinstance(p, ScriptedProvider) and k not in new]:
            del PROVIDERS[key]
        PROVIDERS.update(new)
        ERRORS.clear()
        ERRORS.update(errors)
