"""Proveedores propios (solo administradores): scripts de Python que cumplen el contrato de
`app/providers/scripted.py`, con su prueba sin guardar.

El script se ejecuta en el proceso del servidor: guardar un script activo, activarlo o probarlo exige
confirmar la contraseña (así una sesión robada no basta para ejecutar código) y se anota quién lo guardó.
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from .. import auth, coverage, db, health, places
from ..providers import COVERAGE_LABELS, PROVIDERS
from ..providers import scripted
from .deps import Invalid, require_admin

log = logging.getLogger("scripts")
router = APIRouter(prefix="/providers/scripts", dependencies=[Depends(require_admin)])
throttle = auth.LoginThrottle()

FIELDS = ("key", "label", "color", "coverage", "max_routes", "health_origin", "health_destination", "link_template",
          "notes", "min_interval", "enabled", "created_at", "updated_at", "updated_by")


class ScriptIn(BaseModel):
    key: str = ""
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
    #: Contraseña del administrador: obligatoria si el cambio va a ejecutar el código.
    password: str = ""


class ScriptTestIn(ScriptIn):
    #: Ruta de la prueba (aeropuertos); vacía = la ruta de prueba del formulario.
    origin: str = ""
    destination: str = ""


def _view(row: dict, code: bool = False) -> dict:
    with db.connect() as con:
        n_watches = db.provider_usage(con, row["key"])
    prov = PROVIDERS.get(row["key"])
    return {k: row[k] for k in FIELDS} | {
        "enabled": bool(row["enabled"]), "loaded": bool(getattr(prov, "scripted", False)),
        "error": scripted.ERRORS.get(row["key"]), "n_watches": n_watches,
    } | ({"code": row["code"]} if code else {})


def _airport(raw: str, label: str, errors: list[str]) -> str:
    code = (raw or "").strip().upper()
    place = places.get(code) if code else None
    if not place or place.kind != "airport":
        errors.append(f"El {label} de la ruta de prueba debe ser un aeropuerto (código IATA de 3 letras).")
    return code


def _parse(body: ScriptIn, for_test: bool = False, errors: list[str] | None = None) -> dict:
    """Valores listos para guardar (sin la clave) o `Invalid` con todos los errores (más los de `errors`)."""
    errors = errors if errors is not None else []
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
    origin = _airport(body.health_origin, "origen", errors)
    destination = _airport(body.health_destination, "destino", errors)
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
    code = body.code.replace("\r\n", "\n")
    if not code.strip():
        errors.append("Falta el código del script.")
    elif len(code) > scripted.MAX_CODE:
        errors.append(f"El script es demasiado largo (máximo {scripted.MAX_CODE // 1000} KB).")
    if errors:
        raise Invalid(errors)
    return {"label": label or "Borrador", "color": color.lower(), "coverage": body.coverage, "max_routes": max_routes,
            "health_origin": origin, "health_destination": destination, "link_template": link,
            "notes": body.notes.strip()[:1000], "min_interval": interval, "code": code,
            "enabled": int(body.enabled)}


def _require_enabled():
    if not scripted.ENABLED:
        raise Invalid("Los proveedores propios están desactivados en este servidor (PROVIDER_SCRIPTS=0).", status=403)


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


def _check_loads(key: str, values: dict):
    """Compila el script (y, si va a estar activo, lo carga y comprueba el contrato)."""
    try:
        if values["enabled"]:
            scripted.ScriptedProvider({"key": key, **values})
        else:
            compile(values["code"], scripted.filename(key), "exec")
    except scripted.ScriptError as exc:
        raise Invalid(str(exc)) from exc
    except SyntaxError as exc:
        raise Invalid(f"Error de sintaxis en la línea {exc.lineno}: {exc.msg}") from exc


def _get(con, key: str) -> dict:
    row = db.get_provider_script(con, key)
    if not row:
        raise HTTPException(404, "No existe ese proveedor propio")
    return row


@router.get("")
def list_scripts():
    with db.connect() as con:
        rows = db.list_provider_scripts(con)
    return {"scripts": [_view(r) for r in rows], "enabled": scripted.ENABLED, "template": scripted.TEMPLATE}


@router.get("/{key}")
def get_script(key: str):
    with db.connect() as con:
        return {"script": _view(_get(con, key), code=True)}


@router.post("", status_code=201)
def create_script(body: ScriptIn, admin: dict = Depends(require_admin)):
    _require_enabled()
    key = body.key.strip().lower()
    errors = []
    if not scripted.KEY_RE.fullmatch(key):
        errors.append("La clave debe tener 2-30 caracteres: minúsculas, números o guion bajo, empezando por una letra.")
    with db.connect() as con:
        if db.get_provider_script(con, key) or key in PROVIDERS:
            errors.append("Ya hay un proveedor con esa clave.")
    values = _parse(body, errors=errors)
    if values["enabled"]:
        _confirm(admin, body.password)
    _check_loads(key, values)
    with db.connect() as con:
        db.save_provider_script(con, key, values, admin["username"])
    log.warning("Proveedor propio «%s» creado por %s", key, admin["username"])
    coverage.forget(key)
    scripted.reload()
    with db.connect() as con:
        return {"script": _view(_get(con, key), code=True)}


@router.put("/{key}")
def update_script(key: str, body: ScriptIn, admin: dict = Depends(require_admin)):
    _require_enabled()
    with db.connect() as con:
        old = _get(con, key)
    values = _parse(body)
    # Ejecuta código si queda activo y cambia el script o estaba desactivado.
    if values["enabled"] and (values["code"] != old["code"] or not old["enabled"]):
        _confirm(admin, body.password)
    _check_loads(key, values)
    with db.connect() as con:
        db.save_provider_script(con, key, values, admin["username"])
    log.warning("Proveedor propio «%s» guardado por %s", key, admin["username"])
    if (values["code"], values["coverage"]) != (old["code"], old["coverage"]):
        coverage.forget(key)  # lo que dijo el script anterior ya no vale
    scripted.reload()
    with db.connect() as con:
        return {"script": _view(_get(con, key), code=True)}


@router.delete("/{key}", status_code=204)
def delete_script(key: str, admin: dict = Depends(require_admin)):
    with db.connect() as con:
        _get(con, key)
        db.delete_provider_script(con, key)
    log.warning("Proveedor propio «%s» eliminado por %s", key, admin["username"])
    coverage.forget(key)
    scripted.reload()
    return Response(status_code=204)


@router.post("/test")
def test_script(body: ScriptTestIn, admin: dict = Depends(require_admin)):
    """Prueba el script del formulario sin guardarlo: carga, cobertura y precios de un mes."""
    _require_enabled()
    values = _parse(body, for_test=True)
    errors: list[str] = []
    origin = _airport(body.origin, "origen", errors) if body.origin.strip() else values["health_origin"]
    destination = _airport(body.destination, "destino", errors) if body.destination.strip() else values["health_destination"]
    if origin == destination:
        errors.append("Origen y destino no pueden ser iguales.")
    if errors:
        raise Invalid(errors)
    _confirm(admin, body.password)
    key = body.key.strip().lower()
    key = key if scripted.KEY_RE.fullmatch(key) else "borrador"
    try:
        prov = scripted.ScriptedProvider({"key": key, **values})
    except scripted.ScriptError as exc:
        step = {"name": "Carga del script", "status": "error", "detail": str(exc), "http_status": None, "ms": 0,
                "route": f"{origin}→{destination}"}
        return {"result": {"key": key, "status": "error", "route": step["route"], "steps": [step], "latency_ms": 0,
                           "checked_at": health._now(), "sample": [], "n_prices": 0, "logs": []}}
    return {"result": health.check_draft(prov, origin, destination)}
