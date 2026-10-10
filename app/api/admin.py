"""Solo administradores: usuarios, ajustes globales, proveedores (prueba de acceso) y diagnóstico."""
from __future__ import annotations

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import auth, avatars, checker, db, health, places, scheduler
from ..config import DEBUG_DIR
from ..providers import COVERAGE_LABELS, PROVIDERS
from ..providers.candidates import CANDIDATES
from .account import drop_avatar, read_upload, replace_avatar
from .deps import Invalid, public, require_admin

router = APIRouter(dependencies=[Depends(require_admin)])


# --------------------------------------------------------------------- usuarios
class UserIn(BaseModel):
    username: str = ""
    display_name: str = ""
    role: str = "user"
    password: str = ""
    enabled: bool = True


def _check_identity(con, body: UserIn, role: str, uid: int | None) -> tuple[dict, list[str]]:
    errors = []
    username = auth.normalize_username(body.username)
    if err := auth.validate_username(username):
        errors.append(err)
    else:
        other = db.get_user_by_username(con, username)
        if other and other["id"] != uid:
            errors.append("Ya existe un usuario con ese nombre.")
    if role not in auth.ROLES:
        errors.append("Rol desconocido.")
    return {"username": username, "display_name": body.display_name.strip()[:100] or username, "role": role}, errors


def _would_orphan_admins(con, target: dict, new_role: str, new_enabled: bool) -> bool:
    """True si el cambio deja el panel sin ningún administrador activo."""
    was_active_admin = target["role"] == "admin" and target["enabled"]
    stays = new_role == "admin" and new_enabled
    return was_active_admin and not stays and db.count_admins(con, exclude_id=target["id"]) == 0


def _target(con, uid: int) -> dict:
    u = db.get_user(con, uid)
    if not u:
        raise HTTPException(404, "No existe ese usuario")
    return u


@router.get("/users")
def list_users():
    with db.connect() as con:
        counts, ch_counts = db.watch_counts(con), db.channel_counts(con)
        return {"users": [{**public(u), "n_watches": counts.get(u["id"], 0), "n_channels": ch_counts.get(u["id"], 0)}
                          for u in db.list_users(con)]}


@router.post("/users", status_code=201)
def create_user(body: UserIn):
    with db.connect() as con:
        ident, errors = _check_identity(con, body, body.role, None)
        if err := auth.validate_password(body.password):
            errors.append(err)
        if errors:
            raise Invalid(errors)
        uid = db.create_user(con, ident["username"], ident["display_name"], auth.hash_password(body.password),
                             ident["role"], body.enabled)
        return {"user": public(db.get_user(con, uid))}


@router.get("/users/{uid}")
def get_user(uid: int):
    with db.connect() as con:
        return {"user": public(_target(con, uid))}


@router.put("/users/{uid}")
def update_user(uid: int, body: UserIn, request: Request, admin: dict = Depends(require_admin)):
    with db.connect() as con:
        target = _target(con, uid)
        is_self = uid == admin["id"]
        # Sobre uno mismo, rol y estado no se tocan: así no hay forma de quedarse fuera.
        role = target["role"] if is_self else body.role
        active = bool(target["enabled"]) if is_self else body.enabled
        ident, errors = _check_identity(con, body, role, uid)
        if body.password and (err := auth.validate_password(body.password)):
            errors.append(err)
        if _would_orphan_admins(con, target, ident["role"], active):
            errors.append("Debe quedar al menos un administrador activo.")
        if errors:
            raise Invalid(errors)
        values = {**ident, "enabled": active}
        if body.password:
            values["password_hash"] = auth.hash_password(body.password)
        db.update_user(con, uid, **values)
        user = public(db.get_user(con, uid))
    if is_self and body.password:
        request.session["ph"] = auth.fingerprint(values["password_hash"])
    return {"user": user}


@router.delete("/users/{uid}", status_code=204)
def delete_user(uid: int, admin: dict = Depends(require_admin)):
    if uid == admin["id"]:
        raise Invalid("No puedes eliminar tu propia cuenta.")
    with db.connect() as con:
        target = _target(con, uid)
        if _would_orphan_admins(con, target, "user", False):
            raise Invalid("Debe quedar al menos un administrador activo.")
        db.delete_user(con, uid)
    avatars.remove(target["avatar"])
    return Response(status_code=204)


@router.post("/users/{uid}/avatar")
def upload_user_avatar(uid: int, avatar: UploadFile | None = File(None)):
    data = read_upload(avatar)
    with db.connect() as con:
        replace_avatar(con, _target(con, uid), data)
        return {"user": public(db.get_user(con, uid))}


@router.delete("/users/{uid}/avatar")
def delete_user_avatar(uid: int):
    with db.connect() as con:
        drop_avatar(con, _target(con, uid))
        return {"user": public(db.get_user(con, uid))}


# ---------------------------------------------------------------------- ajustes
def _settings_view(values: dict) -> dict:
    return {
        "values": {k: values[k] for k in db.DEFAULT_SETTINGS}
        | {f"link_{pk}": values.get(f"link_{pk}", "") for pk in PROVIDERS},
        "providers": [{"key": p.key, "label": p.label, "default_link_template": p.default_link_template}
                      for p in PROVIDERS.values()],
    }


@router.get("/settings")
def get_settings():
    return _settings_view(db.get_settings())


@router.put("/settings")
def save_settings(body: dict[str, str | int | float | bool | None]):
    g = lambda k, d="": str(body.get(k) if body.get(k) is not None else d).strip()  # noqa: E731
    errors, new = [], {}

    hours = g("schedule_hours", "8").replace(" ", "")
    if not scheduler.valid_hours(hours):
        errors.append("Las horas deben ser números entre 0 y 23 separados por comas (p. ej. 8,20).")
    new["schedule_hours"] = hours

    def integer(key, label, lo, hi):
        try:
            v = int(g(key))
            if not lo <= v <= hi:
                raise ValueError
            new[key] = str(v)
        except ValueError:
            errors.append(f"{label} debe ser un entero entre {lo} y {hi}.")

    integer("schedule_minute", "El minuto", 0, 59)
    integer("max_months", "Los meses a recorrer", 1, 12)
    integer("min_samples", "El mínimo de muestras", 1, 5000)
    integer("retention_days", "La retención del histórico (días)", 30, 3650)

    tz = g("timezone", "Europe/Madrid")
    try:
        ZoneInfo(tz)
        new["timezone"] = tz
    except Exception:  # noqa: BLE001
        errors.append(f"Zona horaria desconocida: {tz}")

    for key, label in (("panel_url", "La URL del panel"), ("proxy_url", "El proxy")):
        val = g(key)
        if val and not re.match(r"^https?://|^socks5://", val):
            errors.append(f"{label} debe empezar por http://, https:// o socks5://")
        new[key] = val
    for pk in PROVIDERS:
        tpl = g(f"link_{pk}")
        if tpl and not tpl.startswith(("http://", "https://")):
            errors.append(f"La plantilla de enlace de {PROVIDERS[pk].label} debe empezar por https://")
        new[f"link_{pk}"] = tpl

    for flag in ("headless", "debug"):
        new[flag] = "1" if body.get(flag) in (True, 1, "1", "true", "on") else "0"

    if errors:
        raise Invalid(errors)
    db.save_settings(new)
    scheduler.reschedule()
    return _settings_view(db.get_settings())


# ------------------------------------------------------------------- proveedores
def _provider_info(p, last: dict | None) -> dict:
    return {
        "key": p.key, "label": p.label, "color": p.color, "coverage": p.coverage,
        "coverage_label": COVERAGE_LABELS[p.coverage], "needs_browser": p.needs_browser,
        "max_routes": p.max_routes, "stops_filter": p.stops_filter, "min_interval": p.min_interval,
        "health_route": f"{p.health_route[0]}→{p.health_route[1]}", "verified": p.verified or None,
        "notes": p.notes, "last": last and {k: last[k] for k in ("status", "detail", "latency_ms", "checked_at")},
        "scripted": bool(getattr(p, "scripted", False)),
    }


@router.get("/providers")
def list_providers():
    """Proveedores registrados con su último resultado de la prueba de acceso y las aerolíneas en estudio."""
    with db.connect() as con:
        last = db.list_health(con)
    return {
        "providers": [_provider_info(p, last.get(p.key)) for p in PROVIDERS.values()],
        "candidates": [{"key": k, "label": c["label"], "url": c["url"], "notes": c["notes"]}
                       for k, c in CANDIDATES.items() if k not in PROVIDERS],
        "status_labels": health.STATUS_LABELS,
    }


class HealthIn(BaseModel):
    providers: list[str] | None = None
    origin: str = ""
    destination: str = ""
    browser: bool = False
    candidates: bool = False


def _airport(raw: str, label: str, errors: list[str]) -> str | None:
    code = raw.strip().upper()
    if not code:
        return None
    place = places.get(code)
    if not place or place.kind != "airport":
        errors.append(f"El {label} de la prueba debe ser un aeropuerto (código IATA de 3 letras).")
    return code


@router.post("/providers/health")
def providers_health(body: HealthIn):
    """Prueba de acceso: cobertura y precios de un mes por proveedor, desde la IP del panel."""
    errors: list[str] = []
    origin, destination = _airport(body.origin, "origen", errors), _airport(body.destination, "destino", errors)
    if bool(origin) != bool(destination):
        errors.append("Indica origen y destino, o deja los dos vacíos para usar la ruta de prueba de cada proveedor.")
    if origin and origin == destination:
        errors.append("Origen y destino no pueden ser iguales.")
    keys = [k for k in (body.providers if body.providers is not None else PROVIDERS) if k in PROVIDERS]
    unknown = [k for k in body.providers or [] if k not in PROVIDERS]
    if unknown:
        errors.append(f"Proveedor desconocido: {', '.join(unknown)}")
    if errors:
        raise Invalid(errors)
    settings = db.get_settings()
    factory = (lambda: checker.browser_session(settings)) if body.browser else None  # noqa: E731
    results = health.run(keys, origin, destination, factory)
    out = {"results": results, "fx": health.check_fx() if body.providers is None else None, "candidates": []}
    if body.candidates:
        out["candidates"] = [health.check_candidate(k, factory) for k in CANDIDATES if k not in PROVIDERS]
    return out


@router.post("/providers/revalidate")
def providers_revalidate():
    """Revalida ya la cobertura de las vigilancias (lo mismo que hace el planificador cada lunes)."""
    return {"started": scheduler.revalidate_now()}


# ------------------------------------------------------------------ diagnóstico
@router.get("/debug/files")
def debug_files():
    files = sorted((f for f in DEBUG_DIR.glob("*") if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)
    return {"files": [{"name": f.name, "size_kb": f.stat().st_size // 1024,
                       "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                       "image": f.suffix == ".png"} for f in files[:200]]}


@router.get("/debug/files/{name}")
def debug_file(name: str):
    path = DEBUG_DIR / os.path.basename(name)
    if not path.is_file():
        raise HTTPException(404, "No existe ese archivo")
    return FileResponse(path)
