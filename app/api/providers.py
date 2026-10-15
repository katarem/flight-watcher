"""Proveedores (solo administradores): lista con la prueba de acceso, alta/edición/borrado de su script, prueba
del editor con consola en vivo, exportar e importar paquetes (`providers/bundle.py`) y revalidar la cobertura.

Todos los proveedores son scripts que cumplen el contrato de `app/providers/scripted.py` y se ejecutan en el
proceso del servidor: guardar código nuevo de un proveedor activo, activarlo, importarlo o probarlo exige
confirmar la contraseña (así una sesión robada no basta para ejecutar código) y se anota quién lo guardó.
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

from .. import auth, checker, coverage, db, health, kinds, places, scheduler, stays
from ..providers import COVERAGE_LABELS, PROVIDERS, bundle, scripted, stealth
from .deps import Invalid, require_admin

log = logging.getLogger("providers")
router = APIRouter(prefix="/providers", dependencies=[Depends(require_admin)])
throttle = auth.LoginThrottle()

FIELDS = ("key", "kind", "label", "color", "coverage", "max_routes", "health_origin", "health_destination",
          "link_template", "notes", "min_interval", "enabled", "created_at", "updated_at", "updated_by", "source",
          "stealth")


class ProviderIn(BaseModel):
    key: str = ""
    #: Tipo de proveedor (transporte): flight, train, ship, bus (app/kinds.py).
    kind: str = kinds.DEFAULT
    label: str = ""
    color: str = "#64748b"
    coverage: str = "probe"
    max_routes: int | str | None = None
    health_origin: str = ""
    health_destination: str = ""
    link_template: str = ""
    notes: str = ""
    min_interval: float | str | None = 1.5
    code: str = ""
    enabled: bool = True
    #: «Medidas anti-bot»: 0 ninguna, 1 huella de Chrome, 2 siempre Chrome (providers/stealth.py). true/false de
    #: los paquetes antiguos = 1/0.
    stealth: int | bool | str | None = 0
    #: Contraseña del administrador: obligatoria si el cambio va a ejecutar el código.
    password: str = ""


class TestIn(ProviderIn):
    #: Ruta de la prueba (aeropuertos o lugares de su transporte; en uno de alojamiento, `origin` es el destino de
    #: prueba en texto); vacía = la ruta de prueba del formulario.
    origin: str = ""
    destination: str = ""


# ----------------------------------------------------------------------- vistas
def _view(row: dict, usage: dict[str, int], last: dict | None = None, code: bool = False) -> dict:
    prov = PROVIDERS.get(row["key"])
    loaded = isinstance(prov, scripted.ScriptedProvider)
    kind = kinds.KINDS.get(row.get("kind") or kinds.DEFAULT)
    return {k: row.get(k) for k in FIELDS} | {
        "kind": row.get("kind") or kinds.DEFAULT, "kind_label": kind.label if kind else row.get("kind"),
        "enabled": bool(row["enabled"]), "stealth": stealth.level(row.get("stealth")) or stealth.OFF,
        "loaded": loaded, "error": scripted.ERRORS.get(row["key"]),
        "coverage_label": COVERAGE_LABELS.get(row["coverage"], row["coverage"]),
        "stops_filter": loaded and prov.stops_filter, "party_aware": loaded and prov.party_aware,
        "n_watches": usage.get(row["key"], 0),
        "last": last and {k: last[k] for k in ("status", "detail", "latency_ms", "checked_at")},
    } | ({"code": row["code"]} if code else {})


def _get(con, key: str) -> dict:
    row = db.get_provider_script(con, key)
    if not row:
        raise HTTPException(404, "No existe ese proveedor")
    return row


def _one_view(key: str) -> dict:
    with db.connect() as con:
        return _view(_get(con, key), db.provider_usage_counts(con), db.list_health(con).get(key), code=True)


# ------------------------------------------------------------------- validación
def node_code(raw: str, kind: str = kinds.DEFAULT) -> str | None:
    """Código de un lugar real del transporte `kind` (aeropuerto, estación…) o None si no lo es."""
    code = (raw or "").strip().upper()
    node = kinds.get(kind).node if kind in kinds.KINDS else ""
    place = places.get(code) if code else None
    if place:
        return code if place.kind == node else None
    # Estaciones, puertos y paradas aún no tienen catálogo (llegan con sus transportes): basta con el formato.
    return code if node and node != "airport" and places.node_code_ok(code, kind) else None


def _airport(raw: str, label: str, errors: list[str], kind: str = kinds.DEFAULT,
             what: str = "de la ruta de prueba") -> str:
    code = (raw or "").strip().upper()
    if node_code(code, kind) is None:
        k = kinds.KINDS.get(kind) or kinds.get(kinds.DEFAULT)
        errors.append(f"El {label} {what} debe ser un aeropuerto (código IATA de 3 letras)." if k.node == "airport"
                      else f"El {label} {what} debe ser un lugar de tipo {k.node_label} "
                      "(código de 4 a 10 letras o cifras).")
    return code


def _stay_place(raw: str, errors: list[str], what: str) -> str:
    text = " ".join((raw or "").split())
    if not 2 <= len(text) <= stays.PLACE_MAX:
        errors.append(f"Indica un destino {what} para el alojamiento (una ciudad o una zona, de 2 a "
                      f"{stays.PLACE_MAX} caracteres).")
    return text


def _check_key(key: str, errors: list[str]):
    if not scripted.KEY_RE.fullmatch(key) or key in scripted.RESERVED_KEYS:
        errors.append("La clave debe tener 2-30 caracteres: minúsculas, números o guion bajo, empezando por una letra"
                      + (f" (y no puede ser «{key}»)." if key in scripted.RESERVED_KEYS else "."))


def _parse(body: ProviderIn, for_test: bool = False, errors: list[str] | None = None) -> dict:
    """Valores listos para guardar (sin la clave) o `Invalid` con todos los errores (más los de `errors`)."""
    errors = errors if errors is not None else []
    kind = (body.kind or kinds.DEFAULT).strip().lower()
    if kind not in kinds.provider_kinds():
        if kind in kinds.KINDS:
            k = kinds.KINDS[kind]
            errors.append(f"Los proveedores de tipo «{k.label}» llegan en la {k.since}.")
        else:
            errors.append("Tipo de proveedor desconocido (" + ", ".join(kinds.provider_kinds()) + ").")
        kind = kinds.DEFAULT
    label = body.label.strip()[:100]
    if not label and not for_test:
        errors.append("Ponle un nombre al proveedor.")
    color = body.color.strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        errors.append("El color debe ser hexadecimal (#rrggbb).")
    if body.coverage not in COVERAGE_LABELS:
        errors.append("Tipo de cobertura desconocido.")
    max_routes = None
    if body.coverage == "universal" and str(body.max_routes or "").strip():
        try:
            max_routes = int(str(body.max_routes).strip())
            if not 1 <= max_routes <= places.MAX_PAIRS:
                raise ValueError
        except ValueError:
            errors.append(f"El máximo de pares debe ser un entero entre 1 y {places.MAX_PAIRS}.")
    if kind == kinds.STAY:  # alojamiento: un destino de prueba en texto, sin ruta ni cobertura
        origin, destination = _stay_place(body.health_origin, errors, "de prueba"), ""
        body.coverage = "universal"
    else:
        origin = _airport(body.health_origin, "origen", errors, kind)
        destination = _airport(body.health_destination, "destino", errors, kind)
        if origin and origin == destination:
            errors.append("El origen y el destino de la ruta de prueba no pueden ser iguales.")
    link = body.link_template.strip()
    if link and not link.startswith(("http://", "https://")):
        errors.append("La plantilla de enlace debe empezar por https://")
    try:
        interval = float(str(body.min_interval if body.min_interval is not None else "1.5").replace(",", "."))
        if not 0 <= interval <= 60:
            raise ValueError
    except ValueError:
        errors.append("La pausa entre peticiones debe ser un número de segundos entre 0 y 60.")
        interval = 1.5
    level = stealth.level(body.stealth)
    if level is None:
        errors.append("Nivel de medidas anti-bot desconocido (" + ", ".join(f"{k} = {v}" for k, v in stealth.LEVELS.items()) + ").")
    code = body.code.replace("\r\n", "\n")
    if not code.strip():
        errors.append("Falta el código del script.")
    elif len(code) > scripted.MAX_CODE:
        errors.append(f"El script es demasiado largo (máximo {scripted.MAX_CODE // 1000} KB).")
    if errors:
        raise Invalid(errors)
    return {"kind": kind, "label": label or "Borrador", "color": color.lower(), "coverage": body.coverage,
            "max_routes": max_routes,
            "health_origin": origin, "health_destination": destination, "link_template": link,
            "notes": body.notes.strip()[:1000], "min_interval": interval, "code": code,
            "enabled": int(body.enabled), "stealth": level}


def _require_editable():
    if not scripted.EDITABLE:
        raise Invalid("En este servidor no se puede cambiar el código de los proveedores desde el panel "
                      "(PROVIDER_SCRIPTS=0).", status=403)


def _confirm(admin: dict, password: str):
    """Confirmación de la contraseña antes de ejecutar código (con freno tras varios fallos)."""
    key = f"script|{admin['id']}"
    if throttle.blocked(key):
        raise Invalid("Demasiados intentos fallidos. Espera unos minutos.", status=429)
    if not password:
        raise Invalid("Confirma tu contraseña para ejecutar el script.", status=403)
    if not auth.verify_password(password, admin["password_hash"]):
        throttle.fail(key)
        raise Invalid("La contraseña no es correcta.", status=403)
    throttle.reset(key)


def _load_error(key: str, values: dict) -> str | None:
    """Por qué no carga el script (o None): si va a estar activo, lo carga y comprueba el contrato; si no, compila."""
    try:
        if values["enabled"]:
            scripted.ScriptedProvider({"key": key, **values})
        else:
            compile(values["code"], scripted.filename(key), "exec")
    except scripted.ScriptError as exc:
        return str(exc)
    except SyntaxError as exc:
        return f"Error de sintaxis en la línea {exc.lineno}: {exc.msg}"
    return None


def _after_change(key: str, old: dict | None, values: dict):
    changed = (values["code"], values["coverage"], values["kind"]) != (old["code"], old["coverage"], old["kind"]) if old else True
    if changed:
        coverage.forget(key)  # lo que dijo el script anterior ya no vale


# ------------------------------------------------------------------- lista y CRUD
@router.get("")
def list_providers():
    """Todos los proveedores (también los desactivados o rotos) con su último resultado de la prueba de acceso."""
    with db.connect() as con:
        rows, usage, last = db.list_provider_scripts(con), db.provider_usage_counts(con), db.list_health(con)
    sources = sorted({r["source"] for r in rows if r["source"]})
    return {
        "providers": [_view(r, usage, last.get(r["key"])) for r in rows],
        "editable": scripted.EDITABLE, "template": scripted.TEMPLATE, "status_labels": health.STATUS_LABELS,
        "templates": {k: scripted.template_for(k) for k in kinds.provider_kinds()},
        "sources": sources,
        "catalogs": [{"label": label, "url": bundle.CATALOG_URL + name} for name, label in bundle.CATALOGS],
        "kinds": [kinds.view(kinds.KINDS[k]) for k in kinds.provider_kinds()],
    }


@router.get("/export")
def export_providers(keys: str = ""):
    """Paquete `.fwp` con los proveedores pedidos (`keys=a,b`; vacío = todos)."""
    wanted = [k for k in keys.split(",") if k.strip()]
    with db.connect() as con:
        rows = db.list_provider_scripts(con)
    if wanted:
        unknown = sorted(set(wanted) - {r["key"] for r in rows})
        if unknown:
            raise Invalid(f"No existe el proveedor {', '.join(unknown)}.", status=404)
        rows = [r for r in rows if r["key"] in wanted]
    if not rows:
        raise Invalid("No hay proveedores que exportar.", status=404)
    name = f"proveedores-{rows[0]['key'] if len(rows) == 1 else date.today().isoformat()}.fwp"
    return Response(bundle.dumps(rows), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/{key}")
def get_provider(key: str):
    return {"provider": _one_view(key)}


@router.post("", status_code=201)
def create_provider(body: ProviderIn, admin: dict = Depends(require_admin)):
    _require_editable()
    key = body.key.strip().lower()
    errors: list[str] = []
    _check_key(key, errors)
    with db.connect() as con:
        if db.get_provider_script(con, key) or key in PROVIDERS:
            errors.append("Ya hay un proveedor con esa clave.")
    values = _parse(body, errors=errors)
    if values["enabled"]:
        _confirm(admin, body.password)
    if err := _load_error(key, values):
        raise Invalid(err)
    with db.connect() as con:
        db.save_provider_script(con, key, {**values, "source": None}, admin["username"])
    log.warning("Proveedor «%s» creado por %s", key, admin["username"])
    _after_change(key, None, values)
    scripted.reload()
    return {"provider": _one_view(key)}


@router.put("/{key}")
def update_provider(key: str, body: ProviderIn, admin: dict = Depends(require_admin)):
    with db.connect() as con:
        old = _get(con, key)
    if (body.kind or kinds.DEFAULT).strip().lower() != old["kind"]:
        with db.connect() as con:
            used = db.provider_usage_counts(con).get(key, 0)
        if used:
            raise Invalid(f"No se puede cambiar el tipo de un proveedor que usan {used} tramo(s) de viaje: sus rutas son "
                          f"de {kinds.get(old['kind']).label.lower()}.")
    values = _parse(body)
    if values["code"] != old["code"]:
        _require_editable()
    # Ejecuta código si queda activo y cambia el script o estaba desactivado.
    if values["enabled"] and (values["code"] != old["code"] or not old["enabled"]):
        _confirm(admin, body.password)
    if err := _load_error(key, values):
        raise Invalid(err)
    with db.connect() as con:
        db.save_provider_script(con, key, values, admin["username"])
    log.warning("Proveedor «%s» guardado por %s", key, admin["username"])
    _after_change(key, old, values)
    scripted.reload()
    return {"provider": _one_view(key)}


@router.delete("/{key}", status_code=204)
def delete_provider(key: str, admin: dict = Depends(require_admin)):
    with db.connect() as con:
        _get(con, key)
        db.delete_provider_script(con, key)
    log.warning("Proveedor «%s» eliminado por %s", key, admin["username"])
    coverage.forget(key)
    scripted.reload()
    return Response(status_code=204)


# ---------------------------------------------------------- prueba del editor
@router.post("/test")
def test_provider(body: TestIn, admin: dict = Depends(require_admin)):
    """Prueba el script del formulario sin guardarlo: carga, cobertura y precios de un mes.

    Responde en streaming (NDJSON, una línea por evento) para que el editor vea la consola mientras ocurre:
    `{"t": ms, "level": …, "text": …}` por cada traza y, al final, `{"result": {…}}`.
    """
    _require_editable()
    values = _parse(body, for_test=True)
    errors: list[str] = []
    if values["kind"] == kinds.STAY:
        origin = _stay_place(body.origin, errors, "de la prueba") if body.origin.strip() else values["health_origin"]
        destination = ""
    else:
        origin = (_airport(body.origin, "origen", errors, values["kind"], "de la prueba") if body.origin.strip()
                  else values["health_origin"])
        destination = (_airport(body.destination, "destino", errors, values["kind"], "de la prueba")
                       if body.destination.strip() else values["health_destination"])
        if origin == destination:
            errors.append("Origen y destino no pueden ser iguales.")
    if errors:
        raise Invalid(errors)
    _confirm(admin, body.password)
    key = body.key.strip().lower()
    key = key if scripted.KEY_RE.fullmatch(key) else "borrador"
    log.warning("Prueba del script de «%s» por %s", key, admin["username"])

    events: queue.Queue = queue.Queue()
    started = time.monotonic()
    done = threading.Event()

    def say(level: str, text: str):
        if not done.is_set():
            events.put({"t": int((time.monotonic() - started) * 1000), "level": level, "text": text})

    def build(console):
        try:
            return scripted.ScriptedProvider({"key": key, **values}, console=console)
        except scripted.ScriptError as exc:
            for line in scripted.script_frames(exc.__cause__, key) if exc.__cause__ else []:
                console("error", f"  {line}")
            raise

    def work():
        where = origin if values["kind"] == kinds.STAY else f"{origin}→{destination}"
        say("info", f"Prueba de «{values['label']}» ({key}) en {where} desde la IP del servidor")
        try:
            result = health.check_draft(build, origin, destination, say)
        except Exception as exc:  # noqa: BLE001 - la prueba informa de cualquier fallo
            say("error", f"{type(exc).__name__}: {exc}")
            result = {"key": key, "status": "error", "route": where, "steps": [], "latency_ms": 0,
                      "checked_at": health._now(), "sample": [], "n_prices": 0}
        say("info", f"Fin de la prueba: {health.STATUS_LABELS[result['status']].lower()}")
        done.set()
        events.put({"result": result})

    threading.Thread(target=work, name="prueba-script", daemon=True).start()

    def stream():
        while True:
            event = events.get()
            yield json.dumps(event, ensure_ascii=False) + "\n"
            if "result" in event:
                return

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------ importar paquetes
class ImportIn(BaseModel):
    url: str = ""
    #: Contenido del paquete (archivo elegido en el navegador, o el texto ya leído en la vista previa).
    text: str = ""


class ImportApplyIn(ImportIn):
    keys: list[str] = []
    #: Dejar activos los proveedores importados.
    enabled: bool = True
    password: str = ""


def _read_bundle(body: ImportIn) -> tuple[str, str | None, list[dict]]:
    """(texto, enlace de origen o None, proveedores) del paquete del enlace o del texto."""
    url = body.url.strip()
    try:
        if body.text.strip():
            text = body.text
        elif url:
            if not url.startswith(("https://", "http://")):
                raise Invalid("El enlace debe empezar por https://")
            url = bundle.raw_url(url)
            text = bundle.download(url)
        else:
            raise Invalid("Indica un enlace o elige un archivo.")
        return text, url or None, bundle.loads(text)
    except bundle.BundleError as exc:
        raise Invalid(str(exc)) from exc


def _bundle_item(p: dict, enabled: bool = True) -> ProviderIn:
    """El proveedor de un paquete como si llegara del formulario (los tipos raros se quedan para `_parse`)."""
    data = {k: v for k, v in p.items() if v is not None}
    for k in ("key", "kind", "label", "color", "coverage", "health_origin", "health_destination", "link_template",
              "notes", "code"):
        data[k] = str(data.get(k, ProviderIn.model_fields[k].default))
    for k in ("max_routes", "min_interval"):
        if not isinstance(data.get(k), (int, float, str, type(None))) or isinstance(data.get(k), bool):
            data[k] = "?"
    try:
        return ProviderIn(**data, enabled=enabled)
    except ValidationError as exc:
        raise Invalid("Los datos del proveedor no son válidos.") from exc


@router.post("/import/preview")
def import_preview(body: ImportIn):
    """Lee el paquete y dice, sin guardar nada, qué proveedores trae y qué haría importarlos."""
    text, source, items = _read_bundle(body)
    with db.connect() as con:
        current = {r["key"]: r for r in db.list_provider_scripts(con)}
        usage = db.provider_usage_counts(con)
    out = []
    for p in items:
        key = str(p["key"]).strip().lower()
        errors: list[str] = []
        _check_key(key, errors)
        try:
            values = _parse(_bundle_item(p), errors=errors)
        except Invalid as exc:
            values, errors = None, errors + [e for e in exc.errors if e not in errors]
        old = current.get(key)
        changes = [] if not (old and values) else [
            f for f in ("kind", "label", "color", "coverage", "max_routes", "health_origin", "health_destination",
                        "link_template", "notes", "min_interval", "stealth", "code") if values[f] != old[f]]
        out.append({
            "key": key, "label": (values or {}).get("label") or str(p.get("label") or key),
            "color": (values or {}).get("color") or "#64748b", "coverage": p.get("coverage"),
            "kind": (values or {}).get("kind") or str(p.get("kind") or kinds.DEFAULT),
            "coverage_label": COVERAGE_LABELS.get(str(p.get("coverage")), str(p.get("coverage"))),
            "notes": str(p.get("notes") or ""), "code": str(p.get("code") or ""),
            "status": "new" if not old else ("changed" if changes else "same"), "changes": changes,
            "errors": errors, "n_watches": usage.get(key, 0), "enabled": bool(old["enabled"]) if old else None,
        })
    return {"source": source, "text": text, "providers": out}


@router.post("/import")
def import_apply(body: ImportApplyIn, admin: dict = Depends(require_admin)):
    """Importa los proveedores elegidos del paquete (nuevos o sustituyendo a los que tienen la misma clave)."""
    _require_editable()
    text, source, items = _read_bundle(body)
    wanted = set(body.keys)
    chosen = [p for p in items if str(p["key"]).strip().lower() in wanted]
    if not chosen:
        raise Invalid("Elige al menos un proveedor del paquete.")
    _confirm(admin, body.password)
    errors: list[str] = []
    ready: list[tuple[str, dict]] = []
    for p in chosen:
        key = str(p["key"]).strip().lower()
        item_errors: list[str] = []
        _check_key(key, item_errors)
        try:
            values = _parse(_bundle_item(p, body.enabled), errors=item_errors)
        except Invalid as exc:
            errors += [f"{key}: {e}" for e in exc.errors]
            continue
        if err := _load_error(key, values):
            errors.append(f"{key}: {err}")
            continue
        ready.append((key, values | {"source": source}))
    if errors:
        raise Invalid(["No se ha importado nada:"] + errors)
    with db.connect() as con:
        old = {r["key"]: r for r in db.list_provider_scripts(con)}
        for key, values in ready:
            db.save_provider_script(con, key, values, admin["username"])
    for key, values in ready:
        _after_change(key, old.get(key), values)
    log.warning("Proveedores importados por %s%s: %s", admin["username"], f" desde {source}" if source else "",
                ", ".join(k for k, _ in ready))
    scripted.reload()
    return {"imported": [k for k, _ in ready], "created": [k for k, _ in ready if k not in old]}


# ---------------------------------------------------------- prueba de acceso
class HealthIn(BaseModel):
    providers: list[str] | None = None
    origin: str = ""
    destination: str = ""
    browser: bool = False


def _test_airport(raw: str, label: str, errors: list[str]) -> str | None:
    code = raw.strip().upper()
    if not code:
        return None
    if not any(node_code(code, k) for k in kinds.provider_kinds()):
        errors.append(f"El {label} de la prueba debe ser un aeropuerto (código IATA de 3 letras) o un lugar de "
                      "otro transporte.")
    return code


@router.post("/health")
def providers_health(body: HealthIn):
    """Prueba de acceso: cobertura y precios de un mes por proveedor activo, desde la IP del panel."""
    errors: list[str] = []
    origin = _test_airport(body.origin, "origen", errors)
    destination = _test_airport(body.destination, "destino", errors)
    if bool(origin) != bool(destination):
        errors.append("Indica origen y destino, o deja los dos vacíos para usar la ruta de prueba de cada proveedor.")
    if origin and origin == destination:
        errors.append("Origen y destino no pueden ser iguales.")
    keys = [k for k in (body.providers if body.providers is not None else PROVIDERS) if k in PROVIDERS]
    unknown = [k for k in body.providers or [] if k not in PROVIDERS]
    if unknown:
        errors.append(f"Proveedor desconocido o desactivado: {', '.join(unknown)}")
    if errors:
        raise Invalid(errors)
    settings = db.get_settings()
    factory = (lambda: checker.browser_session(settings)) if body.browser else None  # noqa: E731
    results = health.run(keys, origin, destination, factory)
    return {"results": results, "fx": health.check_fx() if body.providers is None else None}


@router.post("/revalidate")
def providers_revalidate():
    """Revalida ya la cobertura de las vigilancias (lo mismo que hace el planificador cada lunes)."""
    return {"started": scheduler.revalidate_now()}

