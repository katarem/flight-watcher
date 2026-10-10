"""Servidor de Flight Watcher: API JSON (`/api/v1`) y el panel React ya compilado (`app/web`).

Un único proceso con un único worker: el planificador de comprobaciones vive dentro.
"""
from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, auth, avatars, db, scheduler
from .providers import scripted
from .api import API_PREFIX
from .api import router as api_router
from .api.deps import Invalid, NotAuthenticated, require_login
from .config import AVATAR_DIR, SECRET_KEY, WEB_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

log = logging.getLogger("main")

#: Cabecera que el panel manda en toda petición que cambia algo. Un formulario de otra web no puede
#: ponerla (ni mandar JSON sin permiso CORS), así que sirve de protección CSRF junto a SameSite=Lax.
CSRF_HEADER = "X-Requested-With"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _bootstrap_admin() -> int:
    """Primer arranque: crea el administrador con PANEL_USER / PANEL_PASSWORD (o uno con clave aleatoria)."""
    username = auth.normalize_username(os.getenv("PANEL_USER") or "admin")
    if auth.validate_username(username):
        log.warning("PANEL_USER no es un nombre de usuario válido; se usa «admin».")
        username = "admin"
    password = os.getenv("PANEL_PASSWORD") or ""
    generated = not password
    if generated:
        password = secrets.token_urlsafe(12)
    uid, created = db.bootstrap_admin(username, auth.hash_password(password))
    if created and generated:
        log.warning("Administrador inicial creado → usuario: %s · contraseña: %s (cámbiala en Perfil)",
                    username, password)
    return uid


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    scripted.reload()  # proveedores propios (scripts guardados desde el panel)
    admin_id = _bootstrap_admin()
    if os.getenv("SEED_DEFAULTS", "1") == "1":
        db.seed_defaults(admin_id)
    if not (WEB_DIR / "index.html").is_file():
        log.warning("No está compilado el panel (%s): cd frontend && npm ci && npm run build", WEB_DIR)
    scheduler.start()
    yield
    scheduler.stop()


# La documentación de la API (/api/v1/docs) se registra más abajo, solo con sesión iniciada.
app = FastAPI(title="Flight Watcher", version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method not in SAFE_METHODS \
            and not request.headers.get(CSRF_HEADER):
        return JSONResponse({"detail": "Petición no permitida.", "errors": ["Petición no permitida."]}, status_code=403)
    return await call_next(request)


app.add_middleware(
    SessionMiddleware, secret_key=SECRET_KEY, session_cookie="fw_session", max_age=30 * 86400,
    same_site="lax", https_only=os.getenv("COOKIE_SECURE") == "1",
)


# ------------------------------------------------------------------------ errores
def _error(status: int, errors: list[str]) -> JSONResponse:
    return JSONResponse({"detail": errors[0] if errors else "Error", "errors": errors}, status_code=status)


@app.exception_handler(NotAuthenticated)
async def _not_authenticated(_request: Request, _exc: NotAuthenticated):
    return _error(401, ["Inicia sesión para continuar."])


@app.exception_handler(Invalid)
async def _invalid(_request: Request, exc: Invalid):
    return _error(exc.status, exc.errors)


@app.exception_handler(RequestValidationError)
async def _bad_request(_request: Request, exc: RequestValidationError):
    fields = sorted({".".join(str(p) for p in e["loc"][1:]) or "cuerpo" for e in exc.errors()})
    return _error(422, [f"Datos no válidos: {', '.join(fields)}."])


@app.exception_handler(StarletteHTTPException)
async def _http_error(_request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "Error"
    if exc.status_code == 404 and detail == "Not Found":
        detail = "No encontrado."
    return _error(exc.status_code, [detail])


app.include_router(api_router)


@app.get(f"{API_PREFIX}/openapi.json", dependencies=[Depends(require_login)], include_in_schema=False)
def openapi_schema():
    return app.openapi()


@app.get(f"{API_PREFIX}/docs", dependencies=[Depends(require_login)], include_in_schema=False)
def api_docs():
    return get_swagger_ui_html(openapi_url=f"{API_PREFIX}/openapi.json", title="Flight Watcher · API")


# ----------------------------------------------------------------------- avatares
@app.get("/avatars/{name}", dependencies=[Depends(require_login)])
def avatar_file(name: str):
    path = AVATAR_DIR / os.path.basename(name)
    media = avatars.MEDIA_TYPES.get(path.suffix.lstrip("."))
    if not path.is_file() or not media:
        raise HTTPException(404)
    return FileResponse(path, media_type=media, headers={
        "Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff",
    })


# ------------------------------------------------------------------ panel (React)
class ImmutableFiles(StaticFiles):
    """Estáticos de Vite: llevan la huella del contenido en el nombre, así que se cachean para siempre."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


if (WEB_DIR / "assets").is_dir():
    app.mount("/assets", ImmutableFiles(directory=WEB_DIR / "assets"), name="assets")

_MISSING_BUILD = """<!doctype html><html lang="es"><meta charset="utf-8"><title>Flight Watcher</title>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto;padding:0 1rem">
<h1>Falta compilar el panel</h1><p>La API funciona, pero no se encuentra el panel web en <code>app/web</code>.
Compílalo con <code>cd frontend &amp;&amp; npm ci &amp;&amp; npm run build</code> o usa la imagen Docker.</p>"""


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    """Cualquier ruta que no sea de la API la resuelve el panel en el navegador (enrutado del lado cliente)."""
    # Lo que no es del panel (API, avatares, estáticos con huella) nunca cae en index.html: mejor un 404 claro.
    if full_path.split("/", 1)[0] in ("api", "avatars", "assets"):
        raise HTTPException(404)
    root = WEB_DIR.resolve()
    candidate = (root / full_path).resolve()
    index = root / "index.html"
    if full_path and candidate.is_file() and candidate.is_relative_to(root) and candidate != index:
        return FileResponse(candidate, headers={"Cache-Control": "public, max-age=3600"})
    if not index.is_file():
        return HTMLResponse(_MISSING_BUILD, status_code=503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
