"""Panel web de Flight Watcher (FastAPI + Jinja2 + Chart.js)."""
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

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import checker, db, fmt, notify, scheduler
from .config import BASE_DIR, DEBUG_DIR
from .providers import PROVIDERS, link_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ------------------------------------------------------------------ autenticación
security = HTTPBasic(auto_error=False)


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)):
    """Basic Auth si defines PANEL_USER y PANEL_PASSWORD (recomendado si el panel es accesible)."""
    user, pwd = os.getenv("PANEL_USER"), os.getenv("PANEL_PASSWORD")
    if not user or not pwd:
        return
    ok = (
        credentials is not None
        and secrets.compare_digest(credentials.username.encode(), user.encode())
        and secrets.compare_digest(credentials.password.encode(), pwd.encode())
    )
    if not ok:
        raise HTTPException(401, "Autenticación requerida", headers={"WWW-Authenticate": "Basic"})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    if os.getenv("SEED_DEFAULTS", "1") == "1":
        db.seed_defaults()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Flight Watcher", dependencies=[Depends(require_auth)], lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters.update(fdate=fmt.fmt_day, price=fmt.fmt_price, dt=fmt.fmt_dt)


def render(request: Request, name: str, **ctx):
    ctx.setdefault("msg", request.query_params.get("msg"))
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


# ------------------------------------------------------------------------ panel
@app.get("/")
def index(request: Request):
    s = db.get_settings()
    today = datetime.now(_tz(s)).date().isoformat()
    cards = []
    with db.connect() as con:
        for w in db.list_watches(con):
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
            cards.append({"w": w, "providers": provs})
        runs = db.list_runs(con, 8)
        alerts = db.list_alerts(con, 8)
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


@app.get("/watches/new")
def watch_new(request: Request):
    blank = {"name": "", "origin": "", "destination": "", "providers": ["vueling"], "max_price": None,
             "discount_pct": 30, "date_from": "", "date_to": "", "enabled": 1}
    return render(request, "watch_form.html", w=blank, is_new=True, errors=[], providers=PROVIDERS)


@app.post("/watches")
def watch_create(
    request: Request, name: str = Form(""), origin: str = Form(""), destination: str = Form(""),
    providers: list[str] = Form(default=[]), max_price: str = Form(""), discount_pct: str = Form("30"),
    date_from: str = Form(""), date_to: str = Form(""), enabled: str = Form(""),
):
    data, errors = _parse_watch_form(name, origin, destination, providers, max_price, discount_pct,
                                     date_from, date_to, enabled)
    if errors:
        return render(request, "watch_form.html", w=data, is_new=True, errors=errors, providers=PROVIDERS)
    with db.connect() as con:
        wid = db.create_watch(con, data)
    return go(f"/watches/{wid}", "Vigilancia creada. Pulsa «Comprobar ahora» para traer los primeros precios.")


@app.get("/watches/{wid}/edit")
def watch_edit(request: Request, wid: int):
    with db.connect() as con:
        w = db.get_watch(con, wid)
    if not w:
        raise HTTPException(404)
    return render(request, "watch_form.html", w=w, is_new=False, errors=[], providers=PROVIDERS)


@app.post("/watches/{wid}/edit")
def watch_update(
    request: Request, wid: int, name: str = Form(""), origin: str = Form(""), destination: str = Form(""),
    providers: list[str] = Form(default=[]), max_price: str = Form(""), discount_pct: str = Form("30"),
    date_from: str = Form(""), date_to: str = Form(""), enabled: str = Form(""),
):
    data, errors = _parse_watch_form(name, origin, destination, providers, max_price, discount_pct,
                                     date_from, date_to, enabled)
    if errors:
        data["id"] = wid
        return render(request, "watch_form.html", w=data, is_new=False, errors=errors, providers=PROVIDERS)
    with db.connect() as con:
        if not db.get_watch(con, wid):
            raise HTTPException(404)
        db.update_watch(con, wid, data)
    return go(f"/watches/{wid}", "Cambios guardados.")


@app.post("/watches/{wid}/delete")
def watch_delete(wid: int):
    with db.connect() as con:
        db.delete_watch(con, wid)
    return go("/", "Vigilancia eliminada junto con su histórico.")


@app.post("/watches/{wid}/toggle")
def watch_toggle(wid: int):
    with db.connect() as con:
        db.toggle_watch(con, wid)
    return go("/")


@app.post("/watches/{wid}/run")
def watch_run(wid: int):
    started = scheduler.run_now(wid)
    return go(f"/watches/{wid}", "Comprobación lanzada…" if started else "Ya hay una comprobación en marcha.")


@app.post("/run")
def run_all():
    started = scheduler.run_now(None)
    return go("/", "Comprobación lanzada…" if started else "Ya hay una comprobación en marcha.")


# --------------------------------------------------------------- detalle + histórico
@app.get("/watches/{wid}")
def watch_detail(request: Request, wid: int, provider: str = ""):
    s = db.get_settings()
    today = datetime.now(_tz(s)).date().isoformat()
    with db.connect() as con:
        w = db.get_watch(con, wid)
        if not w:
            raise HTTPException(404)
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
def api_charts(wid: int):
    with db.connect() as con:
        w = db.get_watch(con, wid)
        if not w:
            raise HTTPException(404)
        keys = [pk for pk in w["providers"] if pk in PROVIDERS]
        over_time = {pk: {} for pk in keys}
        for r in db.chart_min_over_time(con, wid):
            if r["provider"] in over_time:
                over_time[r["provider"]][r["d"]] = r["p"]
        by_date = {pk: {r["flight_date"]: r["price"] for r in db.latest_snapshot(con, wid, pk)} for pk in keys}
    return JSONResponse({"providers": _provider_meta(w), "min_over_time": _align(over_time),
                         "by_flight_date": _align(by_date)})


@app.get("/api/watches/{wid}/date-history")
def api_date_history(wid: int, date: str):
    with db.connect() as con:
        w = db.get_watch(con, wid)
        if not w:
            raise HTTPException(404)
        series = {pk: {} for pk in w["providers"] if pk in PROVIDERS}
        for r in db.date_history(con, wid, date):
            if r["provider"] in series:
                series[r["provider"]][r["d"]] = r["p"]
    return JSONResponse({"providers": _provider_meta(w), **_align(series)})


@app.get("/api/status")
def api_status():
    return {"running": checker.is_running(), "current": checker.STATE["current"]}


# ------------------------------------------------------------------------ ajustes
_WEBHOOK = re.compile(r"^https://(?:[\w-]+\.)?discord(?:app)?\.com/api/webhooks/")


def _settings_view(s: dict) -> dict:
    return {**s, "has_discord": bool(s["discord_webhook"]), "has_telegram": bool(s["telegram_token"])}


@app.get("/settings")
def settings_page(request: Request):
    s = db.get_settings()
    return render(request, "settings.html", s=_settings_view(s), errors=[], providers=PROVIDERS,
                  channels=notify.channels(s))


@app.post("/settings")
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

    hook = g("discord_webhook")
    if form.get("clear_discord"):
        new["discord_webhook"] = ""
    elif hook:
        if _WEBHOOK.match(hook):
            new["discord_webhook"] = hook
        else:
            errors.append("La URL del webhook de Discord no es válida.")
    tok = g("telegram_token")
    if form.get("clear_telegram"):
        new["telegram_token"] = ""
        new["telegram_chat_id"] = ""
    else:
        if tok:
            new["telegram_token"] = tok
        if g("telegram_chat_id"):
            new["telegram_chat_id"] = g("telegram_chat_id")

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

    for flag in ("headless", "debug", "notify_errors"):
        new[flag] = "1" if form.get(flag) else "0"

    if errors:
        view = _settings_view({**old, **{k: v for k, v in new.items() if k not in
                                          ("discord_webhook", "telegram_token")}})
        return render(request, "settings.html", s=view, errors=errors, providers=PROVIDERS,
                      channels=notify.channels(old))
    db.save_settings(new)
    scheduler.reschedule()
    return go("/settings", "Ajustes guardados.")


@app.post("/settings/test")
def settings_test():
    s = db.get_settings()
    if not notify.channels(s):
        return go("/settings", "No hay ningún canal configurado (Discord o Telegram).")
    ok, errors = notify.send_text(s, "✅ Flight Watcher: las notificaciones funcionan.")
    if errors:
        return go("/settings", "Fallo al enviar: " + ", ".join(errors))
    return go("/settings", "Mensaje de prueba enviado a: " + ", ".join(ok))


# --------------------------------------------------------- ejecuciones y diagnóstico
@app.get("/runs")
def runs_page(request: Request):
    with db.connect() as con:
        runs = db.list_runs(con, 200)
    return render(request, "runs.html", runs=runs, providers=PROVIDERS)


@app.get("/debug")
def debug_page(request: Request):
    files = sorted((f for f in DEBUG_DIR.glob("*") if f.is_file()), key=lambda f: f.stat().st_mtime, reverse=True)
    items = [{"name": f.name, "size": f.stat().st_size // 1024,
              "mtime": datetime.fromtimestamp(f.stat().st_mtime), "image": f.suffix == ".png"}
             for f in files[:200]]
    return render(request, "debug.html", files=items)


@app.get("/debug/file/{name}")
def debug_file(name: str):
    path = DEBUG_DIR / os.path.basename(name)
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)
