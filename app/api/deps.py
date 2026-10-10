"""Dependencias y utilidades comunes de la API: sesión, permisos, errores y vistas saneadas."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from .. import auth, db, notify


class NotAuthenticated(Exception):
    """Sin sesión válida: la API responde 401 y el panel lleva al login."""


class Invalid(Exception):
    """Errores de validación para el usuario (en castellano). La API responde 422 con la lista."""

    def __init__(self, errors: list[str] | str, status: int = 422):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        self.status = status
        super().__init__("; ".join(self.errors))


def require_login(request: Request):
    """Exige sesión iniciada (cookie firmada) y deja el usuario en `request.state.user`."""
    user, uid = None, request.session.get("uid")
    if uid:
        with db.connect() as con:
            user = db.get_user(con, uid)
        # Un usuario desactivado o con la contraseña cambiada pierde la sesión al instante.
        if user and (not user["enabled"] or auth.fingerprint(user["password_hash"]) != request.session.get("ph")):
            user = None
    if not user:
        request.session.clear()
        raise NotAuthenticated()
    request.state.user = user


def current_user(request: Request) -> dict:
    return request.state.user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Solo para administradores")
    return user


def start_session(request: Request, user: dict):
    request.session.clear()
    request.session.update({"uid": user["id"], "ph": auth.fingerprint(user["password_hash"])})


def public(user: dict | None) -> dict | None:
    """Lo que el navegador puede ver de un usuario: nunca el hash ni los secretos de los canales."""
    if user is None:
        return None
    return {k: user[k] for k in ("id", "username", "display_name", "role", "avatar", "created_at")} | {
        "enabled": bool(user["enabled"]),
    }


def channel_rows(chans: list[dict]) -> list[dict]:
    """Lo que el navegador ve de un canal: nunca su configuración (secretos)."""
    return [{"id": c["id"], "kind": c["kind"], "kind_label": notify.KINDS[c["kind"]]["label"], "name": c["name"],
             "enabled": bool(c["enabled"])} for c in chans if c["kind"] in notify.KINDS]


def own_watch(con, wid: int, user: dict) -> dict:
    """La vigilancia solo existe para su dueño: para cualquier otro (admin incluido) es un 404."""
    w = db.get_watch(con, wid)
    if not w or w["user_id"] != user["id"]:
        raise HTTPException(404, "No existe esa vigilancia")
    return w


def own_trip(con, tid: int, user: dict) -> dict:
    """Como `own_watch`: un viaje solo existe para su dueño."""
    t = db.get_trip(con, tid)
    if not t or t["user_id"] != user["id"]:
        raise HTTPException(404, "No existe ese viaje")
    return t


def own_channel_ids(user: dict, raw: list[int]) -> list[int]:
    """Los ids marcados que de verdad son canales del usuario (el resto se ignora)."""
    with db.connect() as con:
        mine = {c["id"] for c in db.list_channels(con, user["id"])}
    return sorted({int(c) for c in raw if int(c) in mine})
