"""Sesión (entrar/salir), datos del usuario actual, metadatos del panel y estado de la ronda."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from .. import __version__, auth, avatars, checker, db, notify, scheduler
from ..providers import PROVIDERS
from .deps import Invalid, current_user, public, start_session

public_router = APIRouter()
router = APIRouter()
throttle = auth.LoginThrottle()


class LoginIn(BaseModel):
    username: str = ""
    password: str = ""


@public_router.post("/session")
def login(body: LoginIn, request: Request):
    username = auth.normalize_username(body.username)
    key = f"{request.client.host if request.client else '?'}|{username}"
    if throttle.blocked(key):
        raise Invalid("Demasiados intentos fallidos. Espera unos minutos.", status=429)
    with db.connect() as con:
        user = db.get_user_by_username(con, username)
    if not auth.check_login(user, body.password):
        throttle.fail(key)
        raise Invalid("Usuario o contraseña incorrectos.", status=401)
    throttle.reset(key)
    start_session(request, user)
    return {"user": me_view(user)}


@public_router.delete("/session", status_code=204)
def logout(request: Request):
    request.session.clear()
    return Response(status_code=204)


def me_view(user: dict) -> dict:
    return {**public(user), "notify_errors": bool(user["notify_errors"])}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {"user": me_view(user)}


@router.get("/meta")
def meta():
    """Lo que el panel necesita conocer del servidor: versión, webs y tipos de canal."""
    return {
        "version": __version__,
        "providers": [{"key": p.key, "label": p.label, "color": p.color} for p in PROVIDERS.values()],
        "channel_kinds": [
            {"key": key, "label": k["label"],
             "fields": [{"key": f, "label": label, "secret": secret, "placeholder": ph}
                        for f, label, secret, ph, _ok, _msg in k["fields"]]}
            for key, k in notify.KINDS.items()
        ],
        "avatar_max_bytes": avatars.MAX_BYTES,
    }


@router.get("/status")
def status(user: dict = Depends(current_user)):
    # El nombre de lo que se está comprobando puede ser de otro usuario: solo lo ve el administrador.
    nxt = scheduler.next_run()
    return {
        "running": checker.is_running(),
        "current": checker.STATE["current"] if user["role"] == "admin" else "",
        "next_run": nxt.isoformat() if nxt else None,
    }


@router.post("/run")
def run_all(user: dict = Depends(current_user)):
    """Comprueba ahora todas las vigilancias del usuario."""
    return {"started": scheduler.run_now(None, user["id"])}
