"""Panel web de Flight Watcher (FastAPI + Jinja2 + Chart.js): sesiones, vigilancias por usuario y administración."""
from __future__ import annotations

import logging
import os
import re
import secrets
import statistics
from contextlib import asynccontextmanager
from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import __version__, auth, avatars, checker, db, fmt, notify, scheduler
from .config import AVATAR_DIR, BASE_DIR, DEBUG_DIR, SECRET_KEY
from .providers import PROVIDERS, link_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

log = logging.getLogger("main")

# ------------------------------------------------------------------ autenticación
class NotAuthenticated(Exception):
    pass


PUBLIC_PATHS = {"/login"}
throttle = auth.LoginThrottle()


def require_login(request: Request):
    """Exige sesión iniciada (cookie firmada) y deja el usuario en `request.state.user`."""
    if request.url.path in PUBLIC_PATHS:
        return
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
    admin_id = _bootstrap_admin()
    if os.getenv("SEED_DEFAULTS", "1") == "1":
        db.seed_defaults(admin_id)
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Flight Watcher", version=__version__, dependencies=[Depends(require_login)], lifespan=lifespan)
app.add_middleware(
    SessionMiddleware, secret_key=SECRET_KEY, session_cookie="fw_session", max_age=30 * 86400,
    same_site="lax", https_only=os.getenv("COOKIE_SECURE") == "1",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters.update(fdate=fmt.fmt_day, price=fmt.fmt_price, dt=fmt.fmt_dt)
templates.env.globals["version"] = __version__


@app.exception_handler(NotAuthenticated)
async def _not_authenticated(request: Request, _exc: NotAuthenticated):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Autenticación requerida"}, status_code=401)
    target = "/login"
    if request.method == "GET" and request.url.path != "/":
        target += "?next=" + quote(request.url.path + ("?" + request.url.query if request.url.query else ""))
    return RedirectResponse(target, status_code=303)


def _public(user: dict | None) -> dict | None:
    """Lo que las plantillas pueden ver de un usuario: nunca el hash ni los secretos de los canales."""
    if user is None:
        return None
    return {k: user[k] for k in ("id", "username", "display_name", "role", "enabled", "avatar", "created_at")}


def render(request: Request, name: str, **ctx):
    ctx.setdefault("msg", request.query_params.get("msg"))
    ctx["me"] = _public(getattr(request.state, "user", None))
    ctx["running"] = checker.is_running()
    ctx["next_run"] = scheduler.next_run()
    return templates.TemplateResponse(request, name, ctx)


def go(url: str, msg: str | None = None):
    if msg:
        url += ("&" if "?" in url else "?") + "msg=" + quote(msg)
    return RedirectResponse(url, status_code=303)


def _tz(settings) -> ZoneInfo:
    try:
        return ZoneInfo(settings["timezone"])
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _route(w, row) -> str | None:
    """Aeropuertos reales del precio si difieren de la vigilancia (p. ej. TCI → TFS)."""
    o, d = row["origin"] or w["origin"], row["destination"] or w["destination"]
    return f"{o}→{d}" if (o, d) != (w["origin"], w["destination"]) else None


def _link(settings, pk, w, row) -> str:
    return link_for(settings, pk, row["origin"] or w["origin"], row["destination"] or w["destination"],
                    fmt.to_date(row["flight_date"]))


def _own_watch(con, wid: int, user: dict) -> dict:
    """La vigilancia solo existe para su dueño: para cualquier otro (admin incluido) es un 404."""
    w = db.get_watch(con, wid)
    if not w or w["user_id"] != user["id"]:
        raise HTTPException(404)
    return w


# ------------------------------------------------------------------------ panel
@app.get("/")
def index(request: Request, user: dict = Depends(current_user)):
    s = db.get_settings()
    today = datetime.now(_tz(s)).date().isoformat()
    cards = []
    with db.connect() as con:
        chan_names = {c["id"]: c["name"] for c in db.list_channels(con, user["id"], only_enabled=True)}
        for w in db.list_watches(con, user["id"]):
            provs = []
            for pk in w["providers"]:
                prov = PROVIDERS.get(pk)
                if not prov:
                    continue
                snap = db.latest_snapshot(con, w["id"], pk)
                best = dict(snap[0]) if snap else None
                base = db.baseline(con, w["id"], pk, f"{today}T00:00:00", int(s["min_samples"]))
                provs.append({
                    "key": pk, "label": prov.label, "color": prov.color, "best": best, "base": base,
                    "route": _route(w, best) if best else None,
                    "link": _link(s, pk, w, best) if best else None,
                    "deal": checker.deal_reason(w, best["price"], base) if best else None,
                    "run": db.last_run(con, w["id"], pk),
                })
            cards.append({"w": w, "providers": provs,
                          "channels": [chan_names[i] for i in w["channel_ids"] if i in chan_names]})
        runs = db.list_runs(con, 8, user["id"])
        alerts = db.list_alerts(con, 8, user_id=user["id"])
    return render(request, "index.html", cards=cards, runs=runs, alerts=alerts, providers=PROVIDERS)


# ---------------------------------------------------------- vigilancias (CRUD)
_IATA = re.compile(r"^[A-Za-z]{3}$")


def _parse_watch_form(name, origin, destination, providers, max_price, discount_pct,
                      date_from, date_to, enabled):
    errors = []
    origin, destination = origin.strip().upper(), destination.strip().upper()
    for label, code in (("origen", origin), ("destino", destination)):
        if not _IATA.match(code):
            errors.append(f"El {label} debe ser un código IATA de 3 letras (p. ej. SVQ).")
    if origin == destination and _IATA.match(origin):
        errors.append("Origen y destino no pueden ser iguales.")
    providers = [p for p in providers if p in PROVIDERS]
    if not providers:
        errors.append("Elige al menos un proveedor.")

    def number(text, label, default=None, lo=0.0, hi=100000.0):
        text = (text or "").strip().replace(",", ".")
        if not text:
            return default
        try:
            v = float(text)
        except ValueError:
            errors.append(f"{label} no es un número válido.")
            return default
        if not lo < v <= hi:
            errors.append(f"{label} fuera de rango.")
        return v

    max_p = number(max_price, "El precio máximo")
    disc = number(discount_pct, "El descuento", default=30.0, lo=-1.0, hi=95.0)

    def iso(text, label):
        text = (text or "").strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            errors.append(f"{label} no es una fecha válida.")
            return None

    d_from, d_to = iso(date_from, "«Desde»"), iso(date_to, "«Hasta»")
    if d_from and d_to and d_from > d_to:
        errors.append("«Desde» no puede ser posterior a «Hasta».")

    data = {
        "name": name.strip() or f"{origin} → {destination}",
        "origin": origin, "destination": destination, "providers": providers,
        "max_price": max_p, "discount_pct": disc if disc is not None else 30.0,
        "date_from": d_from, "date_to": d_to, "enabled": bool(enabled),
    }
    return data, errors


def _watch_form_page(request: Request, user: dict, w: dict, is_new: bool, errors=()):
    with db.connect() as con:
        chans = _channel_rows(db.list_channels(con, user["id"]))
    return render(request, "watch_form.html", w=w, is_new=is_new, errors=list(errors), providers=PROVIDERS,
                  channels=chans)


def _own_channel_ids(user: dict, raw: list[str]) -> list[int]:
    """Los ids marcados que de verdad son canales del usuario (el resto se ignora)."""
    with db.connect() as con:
        mine = {c["id"] for c in db.list_channels(con, user["id"])}
    return sorted({int(c) for c in raw if c.isdigit() and int(c) in mine})


@app.get("/watches/new")
def watch_new(request: Request, user: dict = Depends(current_user)):
    with db.connect() as con:
        default_channels = [c["id"] for c in db.list_channels(con, user["id"], only_enabled=True)]
    blank = {"name": "", "origin": "", "destination": "", "providers": ["vueling"], "max_price": None,
             "discount_pct": 30, "date_from": "", "date_to": "", "enabled": 1, "channel_ids": default_channels}
    return _watch_form_page(request, user, blank, True)


@app.post("/watches")
def watch_create(
    request: Request, user: dict = Depends(current_user), name: str = Form(""), origin: str = Form(""), destination: str = Form(""),
    providers: list[str] = Form(default=[]), max_price: str = Form(""), discount_pct: str = Form("30"),
    date_from: str = Form(""), date_to: str = Form(""), enabled: str = Form(""), channels: list[str] = Form(default=[]),
):
    data, errors = _parse_watch_form(name, origin, destination, providers, max_price, discount_pct,
                                     date_from, date_to, enabled)
    data["channel_ids"] = _own_channel_ids(user, channels)
    if errors:
        return _watch_form_page(request, user, data, True, errors)
    with db.connect() as con:
        wid = db.create_watch(con, user["id"], data)
        db.set_watch_channels(con, wid, data["channel_ids"])
    return go(f"/watches/{wid}", "Vigilancia creada. Pulsa «Comprobar ahora» para traer los primeros precios.")


@app.get("/watches/{wid}/edit")
def watch_edit(request: Request, wid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        w = _own_watch(con, wid, user)
    return _watch_form_page(request, user, w, False)


@app.post("/watches/{wid}/edit")
def watch_update(
    request: Request, wid: int, user: dict = Depends(current_user), name: str = Form(""), origin: str = Form(""), destination: str = Form(""),
    providers: list[str] = Form(default=[]), max_price: str = Form(""), discount_pct: str = Form("30"),
    date_from: str = Form(""), date_to: str = Form(""), enabled: str = Form(""), channels: list[str] = Form(default=[]),
):
    data, errors = _parse_watch_form(name, origin, destination, providers, max_price, discount_pct,
                                     date_from, date_to, enabled)
    data["channel_ids"] = _own_channel_ids(user, channels)
    if errors:
        data["id"] = wid
        return _watch_form_page(request, user, data, False, errors)
    with db.connect() as con:
        _own_watch(con, wid, user)
        db.update_watch(con, wid, data)
        db.set_watch_channels(con, wid, data["channel_ids"])
    return go(f"/watches/{wid}", "Cambios guardados.")


@app.post("/watches/{wid}/delete")
def watch_delete(wid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        _own_watch(con, wid, user)
        db.delete_watch(con, wid)
    return go("/", "Vigilancia eliminada junto con su histórico.")


@app.post("/watches/{wid}/toggle")
def watch_toggle(wid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        _own_watch(con, wid, user)
        db.toggle_watch(con, wid)
    return go("/")


@app.post("/watches/{wid}/run")
def watch_run(wid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        _own_watch(con, wid, user)
    started = scheduler.run_now(wid, user["id"])
    return go(f"/watches/{wid}", "Comprobación lanzada…" if started else "Ya hay una comprobación en marcha.")


@app.post("/run")
def run_all(user: dict = Depends(current_user)):
    started = scheduler.run_now(None, user["id"])
    return go("/", "Comprobación lanzada…" if started else "Ya hay una comprobación en marcha.")


# --------------------------------------------------------------- detalle + histórico
@app.get("/watches/{wid}")
def watch_detail(request: Request, wid: int, provider: str = "", user: dict = Depends(current_user)):
    s = db.get_settings()
    today = datetime.now(_tz(s)).date().isoformat()
    with db.connect() as con:
        w = _own_watch(con, wid, user)
        provs, rows, dates = [], [], set()
        for pk in w["providers"]:
            prov = PROVIDERS.get(pk)
            if not prov:
                continue
            snap = db.latest_snapshot(con, wid, pk)
            base = db.baseline(con, wid, pk, f"{today}T00:00:00", int(s["min_samples"]))
            best = dict(snap[0]) if snap else None
            provs.append({
                "key": pk, "label": prov.label, "color": prov.color, "best": best, "base": base,
                "median": statistics.median(r["price"] for r in snap) if snap else None,
                "count": len(snap), "run": db.last_run(con, wid, pk),
                "route": _route(w, best) if best else None,
                "link": _link(s, pk, w, best) if best else None,
                "deal": checker.deal_reason(w, best["price"], base) if best else None,
            })
            for r in snap:
                dates.add(r["flight_date"])
                rows.append({
                    "provider": pk, "label": prov.label, "color": prov.color,
                    "flight_date": r["flight_date"], "price": r["price"],
                    "route": _route(w, r), "link": _link(s, pk, w, r),
                    "deal": checker.deal_reason(w, r["price"], base),
                })
        rows.sort(key=lambda r: (r["price"], r["flight_date"]))
        if provider:
            rows = [r for r in rows if r["provider"] == provider]
        summary = db.checks_summary(con, wid, 40)
        alerts = db.list_alerts(con, 15, wid)
    default_date = rows[0]["flight_date"] if rows else (sorted(dates)[0] if dates else "")
    return render(request, "watch_detail.html", w=w, provs=provs, rows=rows[:40], summary=summary,
                  alerts=alerts, dates=sorted(dates), default_date=default_date,
                  provider_filter=provider, providers=PROVIDERS)


def _align(points: dict[str, dict[str, float]]) -> dict:
    labels = sorted({label for series in points.values() for label in series})
    return {"labels": labels, "series": {pk: [s.get(label) for label in labels] for pk, s in points.items()}}


def _provider_meta(w) -> dict:
    return {pk: {"label": PROVIDERS[pk].label, "color": PROVIDERS[pk].color}
            for pk in w["providers"] if pk in PROVIDERS}


@app.get("/api/watches/{wid}/charts")
def api_charts(wid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        w = _own_watch(con, wid, user)
        keys = [pk for pk in w["providers"] if pk in PROVIDERS]
        over_time = {pk: {} for pk in keys}
        for r in db.chart_min_over_time(con, wid):
            if r["provider"] in over_time:
                over_time[r["provider"]][r["d"]] = r["p"]
        by_date = {pk: {r["flight_date"]: r["price"] for r in db.latest_snapshot(con, wid, pk)} for pk in keys}
    return JSONResponse({"providers": _provider_meta(w), "min_over_time": _align(over_time),
                         "by_flight_date": _align(by_date)})


@app.get("/api/watches/{wid}/date-history")
def api_date_history(wid: int, date: str, user: dict = Depends(current_user)):
    with db.connect() as con:
        w = _own_watch(con, wid, user)
        series = {pk: {} for pk in w["providers"] if pk in PROVIDERS}
        for r in db.date_history(con, wid, date):
            if r["provider"] in series:
                series[r["provider"]][r["d"]] = r["p"]
    return JSONResponse({"providers": _provider_meta(w), **_align(series)})


@app.get("/api/status")
def api_status(user: dict = Depends(current_user)):
    # El nombre de lo que se está comprobando puede ser de otro usuario: solo lo ve el administrador.
    return {"running": checker.is_running(), "current": checker.STATE["current"] if user["role"] == "admin" else ""}


# ------------------------------------------------------------------------ ajustes
@app.get("/settings", dependencies=[Depends(require_admin)])
def settings_page(request: Request):
    return render(request, "settings.html", s=db.get_settings(), errors=[], providers=PROVIDERS)


@app.post("/settings", dependencies=[Depends(require_admin)])
async def settings_save(request: Request):
    form = await request.form()
    old = db.get_settings()
    g = lambda k, d="": str(form.get(k, d)).strip()  # noqa: E731
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
        new[flag] = "1" if form.get(flag) else "0"

    if errors:
        return render(request, "settings.html", s={**old, **new}, errors=errors, providers=PROVIDERS)
    db.save_settings(new)
    scheduler.reschedule()
    return go("/settings", "Ajustes guardados.")


# --------------------------------------------------------- ejecuciones y diagnóstico
@app.get("/runs")
def runs_page(request: Request, user: dict = Depends(current_user)):
    with db.connect() as con:
        runs = db.list_runs(con, 200, user["id"])
    return render(request, "runs.html", runs=runs, providers=PROVIDERS)


@app.get("/debug", dependencies=[Depends(require_admin)])
def debug_page(request: Request):
    files = sorted((f for f in DEBUG_DIR.glob("*") if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)
    items = [{"name": f.name, "size": f.stat().st_size // 1024,
              "mtime": datetime.fromtimestamp(f.stat().st_mtime), "image": f.suffix == ".png"}
             for f in files[:200]]
    return render(request, "debug.html", files=items)


@app.get("/debug/file/{name}", dependencies=[Depends(require_admin)])
def debug_file(name: str):
    path = DEBUG_DIR / os.path.basename(name)
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


# ------------------------------------------------------------ sesión (login / logout)
def _safe_next(value: str) -> str:
    """Solo rutas internas: evita que /login?next=https://otro.sitio sirva de redirección abierta."""
    return value if value.startswith("/") and not value.startswith(("//", "/\\")) else "/"


def _start_session(request: Request, user: dict):
    request.session.clear()
    request.session.update({"uid": user["id"], "ph": auth.fingerprint(user["password_hash"])})


@app.get("/login")
def login_page(request: Request, next: str = ""):
    return render(request, "login.html", next=_safe_next(next), error=None, username="")


@app.post("/login")
def login_submit(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("")):
    username = auth.normalize_username(username)
    key = f"{request.client.host if request.client else '?'}|{username}"
    error = None
    if throttle.blocked(key):
        error = "Demasiados intentos fallidos. Espera unos minutos."
    else:
        with db.connect() as con:
            user = db.get_user_by_username(con, username)
        if auth.check_login(user, password):
            throttle.reset(key)
            _start_session(request, user)
            return go(_safe_next(next))
        throttle.fail(key)
        error = "Usuario o contraseña incorrectos."
    return render(request, "login.html", next=_safe_next(next), error=error, username=username)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return go("/login")


# ----------------------------------------------------------------------- avatares
@app.get("/avatars/{name}")
def avatar_file(name: str):
    path = AVATAR_DIR / os.path.basename(name)
    media = avatars.MEDIA_TYPES.get(path.suffix.lstrip("."))
    if not path.is_file() or not media:
        raise HTTPException(404)
    return FileResponse(path, media_type=media, headers={
        "Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff",
    })


def _read_upload(upload: UploadFile | None) -> bytes | None:
    if upload is None or not upload.filename:
        return None
    return upload.file.read(avatars.MAX_BYTES + 1) or None


def _change_avatar(con, user: dict, upload: UploadFile | None, remove: bool, errors: list[str]):
    """Sustituye o quita el avatar de `user`; los fallos de validación se añaden a `errors`."""
    data = _read_upload(upload)
    if data is not None:
        try:
            name = avatars.save(user["id"], data)
        except ValueError as exc:
            errors.append(str(exc))
            return
        avatars.remove(user["avatar"])
        db.update_user(con, user["id"], avatar=name)
    elif remove and user["avatar"]:
        avatars.remove(user["avatar"])
        db.update_user(con, user["id"], avatar=None)


# ------------------------------------------------------------------------- perfil
def _channel_rows(chans: list[dict]) -> list[dict]:
    """Lo que ven las plantillas de un canal: nunca su configuración (secretos)."""
    return [{"id": c["id"], "kind": c["kind"], "kind_label": notify.KINDS[c["kind"]]["label"], "name": c["name"],
             "enabled": c["enabled"]} for c in chans if c["kind"] in notify.KINDS]


def _profile_page(request: Request, user: dict, errors=(), pw_errors=(), **override):
    with db.connect() as con:
        chans = _channel_rows(db.list_channels(con, user["id"]))
    view = {**_public(user), "notify_errors": user["notify_errors"], **override}
    return render(request, "profile.html", u=view, errors=list(errors), pw_errors=list(pw_errors),
                  channels=chans, ch_base="/profile")


@app.get("/profile")
def profile_page(request: Request, user: dict = Depends(current_user)):
    return _profile_page(request, user)


@app.post("/profile")
def profile_save(
    request: Request, user: dict = Depends(current_user), display_name: str = Form(""),
    notify_errors: str = Form(""), avatar: UploadFile | None = File(None), remove_avatar: str = Form(""),
):
    errors = []
    with db.connect() as con:
        db.update_user(con, user["id"], display_name=display_name.strip()[:100] or user["display_name"],
                       notify_errors=bool(notify_errors))
        _change_avatar(con, user, avatar, bool(remove_avatar), errors)
    if errors:  # el resto sí se ha guardado; solo falló el avatar
        with db.connect() as con:
            user = db.get_user(con, user["id"])
        return _profile_page(request, user, errors)
    return go("/profile", "Perfil guardado.")


@app.post("/profile/password")
def profile_password(
    request: Request, user: dict = Depends(current_user), current_password: str = Form(""),
    new_password: str = Form(""), confirm_password: str = Form(""),
):
    errors = []
    if not auth.verify_password(current_password, user["password_hash"]):
        errors.append("La contraseña actual no es correcta.")
    if err := auth.validate_password(new_password):
        errors.append(err)
    if new_password != confirm_password:
        errors.append("La confirmación no coincide con la nueva contraseña.")
    if errors:
        return _profile_page(request, user, pw_errors=errors)
    new_hash = auth.hash_password(new_password)
    with db.connect() as con:
        db.update_user(con, user["id"], password_hash=new_hash)
    request.session["ph"] = auth.fingerprint(new_hash)  # esta sesión sigue; las demás se cierran
    return go("/profile", "Contraseña cambiada.")


# ------------------------------------------------- canales de aviso (propios o, el admin, de cualquiera)
def owner_self(user: dict = Depends(current_user)) -> dict:
    return user


def owner_admin(uid: int, admin: dict = Depends(require_admin)) -> dict:
    with db.connect() as con:
        owner = db.get_user(con, uid)
    if not owner:
        raise HTTPException(404)
    return owner


def _channel_routes(tag: str, prefix: str, owner_dep, back_fn):
    """Mismas pantallas para `/profile/channels…` (el propio usuario) y `/admin/users/{uid}/channels…` (admin)."""

    def base(owner: dict) -> str:
        return prefix.replace("{uid}", str(owner["id"]))

    def own_channel(con, owner: dict, cid: int) -> dict:
        ch = db.get_channel(con, cid)
        if not ch or ch["user_id"] != owner["id"] or ch["kind"] not in notify.KINDS:
            raise HTTPException(404)
        return ch

    def form_page(request, owner, kind, *, ch=None, name=None, enabled=True, errors=(), form=None):
        config = (ch or {}).get("config") or {}
        fields = notify.view_fields(kind, config)
        for f in fields:  # tras un error se conserva lo escrito (menos los secretos)
            if form and not f["secret"]:
                f["value"] = form.get(f["key"], "")
        return render(request, "channel_form.html", owner=_public(owner), kind=kind, kind_label=notify.KINDS[kind]["label"],
                      fields=fields, ch=ch, is_new=ch is None, ch_name=name if name is not None else (ch["name"] if ch else ""),
                      enabled=enabled, errors=list(errors), action=base(owner) + ("/channels" if ch is None else f"/channels/{ch['id']}/edit"),
                      back=back_fn(owner))

    @app.get(prefix + "/channels/new", name=f"{tag}_channel_new")
    def channel_new(request: Request, kind: str = "", owner: dict = Depends(owner_dep)):
        if kind not in notify.KINDS:
            return render(request, "channel_kinds.html", owner=_public(owner), kinds=notify.KINDS,
                          new_url=base(owner) + "/channels/new", back=back_fn(owner))
        return form_page(request, owner, kind)

    @app.post(prefix + "/channels", name=f"{tag}_channel_create")
    async def channel_create(request: Request, owner: dict = Depends(owner_dep)):
        form = dict(await request.form())
        kind = str(form.get("kind", ""))
        if kind not in notify.KINDS:
            raise HTTPException(400, "Tipo de canal desconocido")
        config, errors = notify.validate_config(kind, form)
        name = str(form.get("name", "")).strip()[:100] or notify.KINDS[kind]["label"]
        enabled = bool(form.get("enabled"))
        if errors:
            return form_page(request, owner, kind, name=name, enabled=enabled, errors=errors, form=form)
        with db.connect() as con:
            db.create_channel(con, owner["id"], kind, name, config, enabled)
        return go(back_fn(owner), f"Canal «{name}» añadido. Asígnalo a tus vigilancias para recibir avisos.")

    @app.get(prefix + "/channels/{cid}/edit", name=f"{tag}_channel_edit")
    def channel_edit(request: Request, cid: int, owner: dict = Depends(owner_dep)):
        with db.connect() as con:
            ch = own_channel(con, owner, cid)
        return form_page(request, owner, ch["kind"], ch=ch, enabled=bool(ch["enabled"]))

    @app.post(prefix + "/channels/{cid}/edit", name=f"{tag}_channel_update")
    async def channel_update(request: Request, cid: int, owner: dict = Depends(owner_dep)):
        form = dict(await request.form())
        with db.connect() as con:
            ch = own_channel(con, owner, cid)
            config, errors = notify.validate_config(ch["kind"], form, ch["config"])
            name = str(form.get("name", "")).strip()[:100] or notify.KINDS[ch["kind"]]["label"]
            enabled = bool(form.get("enabled"))
            if errors:
                return form_page(request, owner, ch["kind"], ch=ch, name=name, enabled=enabled, errors=errors, form=form)
            db.update_channel(con, cid, name, config, enabled)
        return go(back_fn(owner), f"Canal «{name}» guardado.")

    @app.post(prefix + "/channels/{cid}/delete", name=f"{tag}_channel_delete")
    def channel_delete(cid: int, owner: dict = Depends(owner_dep)):
        with db.connect() as con:
            ch = own_channel(con, owner, cid)
            db.delete_channel(con, cid)
        return go(back_fn(owner), f"Canal «{ch['name']}» eliminado (también de las vigilancias que lo usaban).")

    @app.post(prefix + "/channels/{cid}/test", name=f"{tag}_channel_test")
    def channel_test(cid: int, owner: dict = Depends(owner_dep)):
        with db.connect() as con:
            ch = own_channel(con, owner, cid)
        ok, errors = notify.send_text([ch], "✅ Flight Watcher: las notificaciones funcionan.")
        return go(back_fn(owner), ("Fallo al enviar: " + ", ".join(errors)) if errors else f"Mensaje de prueba enviado a «{ch['name']}».")


_channel_routes("me", "/profile", owner_self, lambda o: "/profile")
_channel_routes("admin", "/admin/users/{uid}", owner_admin, lambda o: f"/admin/users/{o['id']}/edit")


# --------------------------------------------------------- usuarios (solo admin)
def _user_row(u: dict, n_watches: int, n_channels: int) -> dict:
    return {**_public(u), "n_watches": n_watches, "n_channels": n_channels}


def _admin_form(request: Request, u: dict, is_new: bool, errors=()):
    chans = []
    if not is_new:
        with db.connect() as con:
            chans = _channel_rows(db.list_channels(con, u["id"]))
    return render(request, "user_form.html", u=u, is_new=is_new, errors=list(errors), roles=auth.ROLES,
                  channels=chans, ch_base=f"/admin/users/{u['id']}")


@app.get("/admin/users")
def users_page(request: Request, admin: dict = Depends(require_admin)):
    with db.connect() as con:
        counts, ch_counts = db.watch_counts(con), db.channel_counts(con)
        rows = [_user_row(u, counts.get(u["id"], 0), ch_counts.get(u["id"], 0)) for u in db.list_users(con)]
    return render(request, "users.html", users=rows)


@app.get("/admin/users/new")
def user_new(request: Request, admin: dict = Depends(require_admin)):
    blank = {"username": "", "display_name": "", "role": "user", "enabled": 1, "avatar": None, "id": None}
    return _admin_form(request, blank, True)


def _check_identity(con, username: str, display_name: str, role: str, uid: int | None) -> tuple[dict, list[str]]:
    errors = []
    username = auth.normalize_username(username)
    if err := auth.validate_username(username):
        errors.append(err)
    else:
        other = db.get_user_by_username(con, username)
        if other and other["id"] != uid:
            errors.append("Ya existe un usuario con ese nombre.")
    if role not in auth.ROLES:
        errors.append("Rol desconocido.")
    return {"username": username, "display_name": display_name.strip()[:100] or username, "role": role}, errors


@app.post("/admin/users")
def user_create(
    request: Request, admin: dict = Depends(require_admin), username: str = Form(""), display_name: str = Form(""),
    role: str = Form("user"), password: str = Form(""), enabled: str = Form(""),
    avatar: UploadFile | None = File(None),
):
    with db.connect() as con:
        ident, errors = _check_identity(con, username, display_name, role, None)
        if err := auth.validate_password(password):
            errors.append(err)
        form = {**ident, "enabled": bool(enabled), "avatar": None, "id": None}
        if errors:
            return _admin_form(request, form, True, errors)
        uid = db.create_user(con, ident["username"], ident["display_name"], auth.hash_password(password),
                             ident["role"], bool(enabled))
        _change_avatar(con, {"id": uid, "avatar": None}, avatar, False, errors)
    return go("/admin/users", f"Usuario «{ident['username']}» creado."
              + (f" Pero el avatar no se guardó: {errors[0]}" if errors else ""))


def _would_orphan_admins(con, target: dict, new_role: str, new_enabled: bool) -> bool:
    """True si el cambio deja el panel sin ningún administrador activo."""
    was_active_admin = target["role"] == "admin" and target["enabled"]
    stays = new_role == "admin" and new_enabled
    return was_active_admin and not stays and db.count_admins(con, exclude_id=target["id"]) == 0


@app.get("/admin/users/{uid}/edit")
def user_edit(request: Request, uid: int, admin: dict = Depends(require_admin)):
    with db.connect() as con:
        u = db.get_user(con, uid)
    if not u:
        raise HTTPException(404)
    return _admin_form(request, _public(u), False)


@app.post("/admin/users/{uid}/edit")
def user_update(
    request: Request, uid: int, admin: dict = Depends(require_admin), username: str = Form(""),
    display_name: str = Form(""), role: str = Form(""), password: str = Form(""), enabled: str = Form(""),
    avatar: UploadFile | None = File(None), remove_avatar: str = Form(""),
):
    with db.connect() as con:
        target = db.get_user(con, uid)
        if not target:
            raise HTTPException(404)
        is_self = uid == admin["id"]
        # Sobre uno mismo, rol y estado no se tocan (los campos ni se envían): así no hay forma de quedarse fuera.
        role = target["role"] if is_self else role
        active = bool(target["enabled"]) if is_self else bool(enabled)
        ident, errors = _check_identity(con, username, display_name, role, uid)
        if password and (err := auth.validate_password(password)):
            errors.append(err)
        if _would_orphan_admins(con, target, ident["role"], active):
            errors.append("Debe quedar al menos un administrador activo.")
        form = {**_public(target), **ident, "enabled": int(active)}
        if errors:
            return _admin_form(request, form, False, errors)
        values = {**ident, "enabled": active}
        if password:
            values["password_hash"] = auth.hash_password(password)
        db.update_user(con, uid, **values)
        _change_avatar(con, target, avatar, bool(remove_avatar), errors)
    if is_self and password:
        request.session["ph"] = auth.fingerprint(values["password_hash"])
    return go("/admin/users", f"Usuario «{ident['username']}» actualizado."
              + (f" Pero el avatar no se guardó: {errors[0]}" if errors else ""))


@app.post("/admin/users/{uid}/delete")
def user_delete(uid: int, admin: dict = Depends(require_admin)):
    if uid == admin["id"]:
        return go("/admin/users", "No puedes eliminar tu propia cuenta.")
    with db.connect() as con:
        target = db.get_user(con, uid)
        if not target:
            raise HTTPException(404)
        if _would_orphan_admins(con, target, "user", False):
            return go("/admin/users", "Debe quedar al menos un administrador activo.")
        db.delete_user(con, uid)
    avatars.remove(target["avatar"])
    return go("/admin/users", f"Usuario «{target['username']}» eliminado junto con sus vigilancias.")
