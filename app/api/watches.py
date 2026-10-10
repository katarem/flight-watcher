"""Vigilancias del usuario: CRUD, detalle con precios, gráficas, avisos y ejecuciones."""
from __future__ import annotations

import re
import statistics
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from .. import checker, db, fmt, scheduler
from ..providers import PROVIDERS, link_for
from .deps import Invalid, current_user, own_channel_ids, own_watch

router = APIRouter()

_IATA = re.compile(r"^[A-Za-z]{3}$")


def _tz(settings) -> ZoneInfo:
    try:
        return ZoneInfo(settings["timezone"])
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _today(settings) -> str:
    return datetime.now(_tz(settings)).date().isoformat()


def _route(w, row) -> str | None:
    """Aeropuertos reales del precio si difieren de la vigilancia (p. ej. TCI → TFS)."""
    o, d = row["origin"] or w["origin"], row["destination"] or w["destination"]
    return f"{o}→{d}" if (o, d) != (w["origin"], w["destination"]) else None


def _link(settings, pk, w, row) -> str:
    return link_for(settings, pk, row["origin"] or w["origin"], row["destination"] or w["destination"],
                    fmt.to_date(row["flight_date"]))


def watch_view(w: dict) -> dict:
    return {k: w[k] for k in ("id", "name", "origin", "destination", "providers", "max_price", "discount_pct",
                              "date_from", "date_to", "channel_ids", "created_at")} | {"enabled": bool(w["enabled"])}


def _run_view(run: dict | None) -> dict | None:
    if not run:
        return None
    return {"ok": bool(run["ok"]), "error": run["error"], "finished_at": run["finished_at"], "n_prices": run["n_prices"]}


def _provider_stats(con, settings, w, detail: bool = False) -> tuple[list[dict], list[dict]]:
    """Resumen por web (mejor precio, habitual, último error) y, si `detail`, todas las filas de la última comprobación."""
    today = _today(settings)
    stats, rows = [], []
    for pk in w["providers"]:
        prov = PROVIDERS.get(pk)
        if not prov:
            continue
        snap = db.latest_snapshot(con, w["id"], pk)
        base = db.baseline(con, w["id"], pk, f"{today}T00:00:00", int(settings["min_samples"]))
        best = dict(snap[0]) if snap else None
        item = {
            "key": pk, "label": prov.label, "color": prov.color, "base": base,
            "best": best and {**best, "route": _route(w, best), "link": _link(settings, pk, w, best),
                              "deal": checker.deal_reason(w, best["price"], base)},
            "run": _run_view(db.last_run(con, w["id"], pk)),
        }
        if detail:
            item["median"] = statistics.median(r["price"] for r in snap) if snap else None
            item["count"] = len(snap)
            rows += [{"provider": pk, "flight_date": r["flight_date"], "price": r["price"], "route": _route(w, r),
                      "link": _link(settings, pk, w, r), "deal": checker.deal_reason(w, r["price"], base)}
                     for r in snap]
        stats.append(item)
    rows.sort(key=lambda r: (r["price"], r["flight_date"]))
    return stats, rows


def _trend(con, wid: int, points: int = 30) -> list[dict]:
    """Precio mínimo entre todas las webs por día de comprobación (para la minigráfica del panel)."""
    by_day: dict[str, float] = {}
    for r in db.chart_min_over_time(con, wid):
        by_day[r["d"]] = min(r["p"], by_day.get(r["d"], r["p"]))
    return [{"d": d, "p": p} for d, p in sorted(by_day.items())[-points:]]


# ------------------------------------------------------------------------- lista
@router.get("/watches")
def list_watches(user: dict = Depends(current_user)):
    s = db.get_settings()
    out = []
    with db.connect() as con:
        names = {c["id"]: c["name"] for c in db.list_channels(con, user["id"], only_enabled=True)}
        for w in db.list_watches(con, user["id"]):
            stats, _ = _provider_stats(con, s, w)
            out.append({**watch_view(w), "stats": stats, "trend": _trend(con, w["id"]),
                        "channels": [names[i] for i in w["channel_ids"] if i in names]})
    return {"watches": out}


@router.get("/alerts")
def list_alerts(limit: int = 10, user: dict = Depends(current_user)):
    with db.connect() as con:
        return {"alerts": db.list_alerts(con, max(1, min(limit, 200)), user_id=user["id"])}


@router.get("/runs")
def list_runs(limit: int = 50, user: dict = Depends(current_user)):
    with db.connect() as con:
        rows = db.list_runs(con, max(1, min(limit, 500)), user["id"])
    return {"runs": [{**r, "ok": None if r["ok"] is None else bool(r["ok"])} for r in rows]}


# ------------------------------------------------------------------------- CRUD
class WatchIn(BaseModel):
    name: str = ""
    origin: str = ""
    destination: str = ""
    providers: list[str] = []
    max_price: float | str | None = None
    discount_pct: float | str | None = None
    date_from: str | None = None
    date_to: str | None = None
    enabled: bool = True
    channel_ids: list[int] = []


def parse_watch(body: WatchIn) -> dict:
    """Datos listos para guardar o `Invalid` con todos los errores encontrados."""
    errors = []
    origin, destination = body.origin.strip().upper(), body.destination.strip().upper()
    for label, code in (("origen", origin), ("destino", destination)):
        if not _IATA.match(code):
            errors.append(f"El {label} debe ser un código IATA de 3 letras (p. ej. SVQ).")
    if origin == destination and _IATA.match(origin):
        errors.append("Origen y destino no pueden ser iguales.")
    providers = [p for p in dict.fromkeys(body.providers) if p in PROVIDERS]
    if not providers:
        errors.append("Elige al menos un proveedor.")

    def number(value, label, default=None, lo=0.0, hi=100000.0):
        text = str(value if value is not None else "").strip().replace(",", ".")
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

    def iso(value, label):
        text = (value or "").strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            errors.append(f"{label} no es una fecha válida.")
            return None

    max_p = number(body.max_price, "El precio máximo")
    disc = number(body.discount_pct, "El descuento", default=30.0, lo=-1.0, hi=95.0)
    d_from, d_to = iso(body.date_from, "«Desde»"), iso(body.date_to, "«Hasta»")
    if d_from and d_to and d_from > d_to:
        errors.append("«Desde» no puede ser posterior a «Hasta».")
    if errors:
        raise Invalid(errors)
    return {
        "name": body.name.strip()[:200] or f"{origin} → {destination}",
        "origin": origin, "destination": destination, "providers": providers,
        "max_price": max_p, "discount_pct": disc if disc is not None else 30.0,
        "date_from": d_from, "date_to": d_to, "enabled": body.enabled,
    }


@router.post("/watches", status_code=201)
def create_watch(body: WatchIn, user: dict = Depends(current_user)):
    data = parse_watch(body)
    channel_ids = own_channel_ids(user, body.channel_ids)
    with db.connect() as con:
        wid = db.create_watch(con, user["id"], data)
        db.set_watch_channels(con, wid, channel_ids)
        return {"watch": watch_view(db.get_watch(con, wid))}


@router.get("/watches/{wid}")
def get_watch(wid: int, user: dict = Depends(current_user)):
    """Todo lo del detalle salvo las gráficas: resumen por web, precios de la última comprobación,
    historial de comprobaciones y avisos enviados."""
    s = db.get_settings()
    with db.connect() as con:
        w = own_watch(con, wid, user)
        stats, rows = _provider_stats(con, s, w, detail=True)
        return {
            "watch": watch_view(w), "stats": stats, "prices": rows,
            "checks": db.checks_summary(con, wid, 40), "alerts": db.list_alerts(con, 15, wid),
        }


@router.put("/watches/{wid}")
def update_watch(wid: int, body: WatchIn, user: dict = Depends(current_user)):
    with db.connect() as con:
        own_watch(con, wid, user)
    data = parse_watch(body)
    channel_ids = own_channel_ids(user, body.channel_ids)
    with db.connect() as con:
        db.update_watch(con, wid, data)
        db.set_watch_channels(con, wid, channel_ids)
        return {"watch": watch_view(db.get_watch(con, wid))}


@router.delete("/watches/{wid}", status_code=204)
def delete_watch(wid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        own_watch(con, wid, user)
        db.delete_watch(con, wid)
    return Response(status_code=204)


@router.post("/watches/{wid}/toggle")
def toggle_watch(wid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        own_watch(con, wid, user)
        db.toggle_watch(con, wid)
        return {"watch": watch_view(db.get_watch(con, wid))}


@router.post("/watches/{wid}/run")
def run_watch(wid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        own_watch(con, wid, user)
    return {"started": scheduler.run_now(wid, user["id"])}


# --------------------------------------------------------------------- gráficas
def _align(points: dict[str, dict[str, float]]) -> dict:
    labels = sorted({label for series in points.values() for label in series})
    return {"labels": labels, "series": {pk: [s.get(label) for label in labels] for pk, s in points.items()}}


@router.get("/watches/{wid}/charts")
def charts(wid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        w = own_watch(con, wid, user)
        keys = [pk for pk in w["providers"] if pk in PROVIDERS]
        over_time = {pk: {} for pk in keys}
        for r in db.chart_min_over_time(con, wid):
            if r["provider"] in over_time:
                over_time[r["provider"]][r["d"]] = r["p"]
        by_date = {pk: {r["flight_date"]: r["price"] for r in db.latest_snapshot(con, wid, pk)} for pk in keys}
    return {"min_over_time": _align(over_time), "by_flight_date": _align(by_date)}


@router.get("/watches/{wid}/date-history")
def date_history(wid: int, date: str, user: dict = Depends(current_user)):
    with db.connect() as con:
        w = own_watch(con, wid, user)
        series = {pk: {} for pk in w["providers"] if pk in PROVIDERS}
        for r in db.date_history(con, wid, date):
            if r["provider"] in series:
                series[r["provider"]][r["d"]] = r["p"]
    return _align(series)
