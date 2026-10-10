"""API JSON del panel (`/api/v1`). El frontend React (carpeta `frontend/`) es su único cliente.

Toda ruta exige sesión salvo entrar y salir. Las respuestas son JSON; los errores para el usuario
llegan como `{"detail": "…", "errors": ["…"]}` (ver `deps.Invalid`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from . import account, admin, provider_scripts, session, trips, watches
from .deps import require_login

API_PREFIX = "/api/v1"

router = APIRouter(prefix=API_PREFIX)
router.include_router(session.public_router)

private = APIRouter(dependencies=[Depends(require_login)])
for module in (session, watches, trips, account, admin, provider_scripts):
    private.include_router(module.router)
router.include_router(private)
