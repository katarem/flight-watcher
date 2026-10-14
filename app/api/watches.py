"""Vigilancias del usuario: CRUD, detalle con precios, gráficas, avisos y ejecuciones."""
from __future__ import annotations

import statistics
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import checker, coverage, db, fmt, kinds, places
from ..providers import PROVIDERS, link_for, ordered
from .deps import Invalid, current_user, own_watch

router = APIRouter()


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


def _link(pk, w, row) -> str:
    return link_for(pk, row["origin"] or w["origin"], row["destination"] or w["destination"],
                    fmt.to_date(row["flight_date"]))


def watch_view(w: dict) -> dict:
    return {k: w[k] for k in ("id", "name", "origin", "destination", "max_price", "discount_pct", "date_from",
                              "date_to", "max_stops", "channel_ids", "created_at")} | {
        "kind": w.get("kind") or kinds.DEFAULT,
        "enabled": bool(w["enabled"]), "providers": ordered(w["providers"]),
        "origin_place": places.view(w["origin"]), "destination_place": places.view(w["destination"]),
        "coverage": [{"key": k, "routes": [db.pair_key(p) for p in w["coverage"][k]["routes"]],
                      "active": w["coverage"][k]["active"], "checked_at": w["coverage"][k]["checked_at"]}
                     for k in ordered(w["providers"])],
    }


def _money(row) -> dict:
    """Moneda original, escalas y horas de un precio guardado."""
    return {"currency": row.get("currency") or "EUR", "orig_price": row.get("orig_price"), "stops": row.get("stops"),
            "departs_at": row.get("departs_at"), "arrives_at": row.get("arrives_at")}


def _run_view(run: dict | None) -> dict | None:
    if not run:
        return None
    return {"ok": bool(run["ok"]), "error": run["error"], "finished_at": run["finished_at"], "n_prices": run["n_prices"]}


def _provider_stats(con, settings, w, detail: bool = False) -> tuple[list[dict], list[dict]]:
    """Resumen por web (mejor precio, habitual, último error) y, si `detail`, todas las filas de la última comprobación."""
    today = _today(settings)
    stats, rows = [], []
    for pk in ordered(w["providers"]):
        prov = PROVIDERS[pk]
        cov = w["coverage"][pk]
        snap = db.latest_snapshot(con, w["id"], pk)
        base = db.baseline(con, w["id"], pk, f"{today}T00:00:00", int(settings["min_samples"]))
        best = dict(snap[0]) if snap else None
        item = {
            "key": pk, "label": prov.label, "color": prov.color, "base": base,
            "active": cov["active"], "routes": [db.pair_key(p) for p in cov["routes"]], "checked_at": cov["checked_at"],
            "best": best and {**best, **_money(best), "route": _route(w, best), "link": _link(pk, w, best),
                              "deal": checker.deal_reason(w, best["price"], base)},
            "run": _run_view(db.last_run(con, w["id"], pk)),
        }
        if detail:
            item["median"] = statistics.median(r["price"] for r in snap) if snap else None
            item["count"] = len(snap)
            rows += [{"provider": pk, "flight_date": r["flight_date"], "price": r["price"], "route": _route(w, r),
                      "link": _link(pk, w, r), "deal": checker.deal_reason(w, r["price"], base), **_money(r)}
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


# Las vigilancias ya no se listan ni se gestionan sueltas: son tramos internos de un viaje (ver api/trips.py).
# De aquí solo quedan el detalle de un tramo (calendario, gráficas) y las utilidades que usa el formulario de
# viaje (lugares y comprobación de rutas), además de los avisos y ejecuciones del usuario.
@router.get("/alerts")
def list_alerts(limit: int = 10, user: dict = Depends(current_user)):
    with db.connect() as con:
        return {"alerts": db.list_alerts(con, max(1, min(limit, 200)), user_id=user["id"])}


@router.get("/runs")
def list_runs(limit: int = 50, user: dict = Depends(current_user)):
    with db.connect() as con:
        rows = db.list_runs(con, max(1, min(limit, 500)), user["id"])
    return {"runs": [{**r, "ok": None if r["ok"] is None else bool(r["ok"])} for r in rows]}


# --------------------------------------------------------------- tramos (vigilancias)
class LegIn(BaseModel):
    """Un tramo de un viaje. El precio máximo, el descuento y las fechas viven en el viaje, no en el tramo."""
    #: Transporte del tramo (app/kinds.py); vacío = vuelos.
    kind: str = kinds.DEFAULT
    name: str = ""
    origin: str = ""
    destination: str = ""
    providers: list[str] = []
    max_stops: int | str | None = 0


def parse_kind(raw: str | None, errors: list[str]) -> str:
    """Transporte de una vigilancia: uno de los disponibles (hoy, vuelos)."""
    kind = (raw or kinds.DEFAULT).strip().lower()
    if kind in kinds.KINDS and kinds.KINDS[kind].available and kinds.KINDS[kind].transport:
        return kind
    k = kinds.KINDS.get(kind)
    errors.append(f"Las vigilancias de {k.label.lower()} llegan en la {k.since}." if k and k.since
                  else "Tipo de transporte desconocido.")
    return kinds.DEFAULT


def parse_route(origin_raw: str, destination_raw: str, errors: list[str],
                kind: str = kinds.DEFAULT) -> tuple[str, str]:
    """Códigos de lugar válidos para el transporte `kind` o errores en `errors`."""
    origin, destination = places.clean_code(origin_raw), places.clean_code(destination_raw)
    k = kinds.get(kind)
    ok = True
    for label, code in (("origen", origin), ("destino", destination)):
        place = places.get(code)
        if not place:
            ok = False
            errors.append(f"El {label} no es un {k.node_label}, ciudad, país o grupo conocido: elígelo de la lista"
                          + (" (o escribe su código IATA, p. ej. SVQ)." if k.node == "airport" else "."))
        elif not place.nodes_for(kind):
            ok = False
            errors.append(f"El {label} ({place.label}) no tiene ningún {k.node_label}: elige otro lugar.")
    if ok:
        n = len(places.routes(origin, destination, kind))
        what = f"{places.NODE_PLURALS.get(k.node, 'lugares')}"
        if origin == destination or n == 0:
            errors.append("Origen y destino no pueden ser iguales.")
        elif n > places.MAX_PAIRS:
            errors.append(f"Esa ruta son {n} combinaciones de {what} (máximo {places.MAX_PAIRS}): "
                          "acota el origen o el destino.")
    return origin, destination


def parse_number(value, label: str, errors: list[str], default=None, lo=0.0, hi=100000.0) -> float | None:
    """Número con coma o punto decimal en (lo, hi]; vacío → `default`."""
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


def parse_dates(date_from, date_to, errors: list[str]) -> tuple[str | None, str | None]:
    """Ventana de fechas «Desde»/«Hasta» opcional (ISO)."""
    def iso(value, label):
        text = (value or "").strip()
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
    return d_from, d_to


def parse_leg(leg: LegIn, errors: list[str], enabled: bool) -> dict:
    """Valida un tramo y devuelve los datos para `db.create_watch` (los errores se acumulan en `errors`).
    `max_price`/`date_from`/`date_to` quedan vacíos en el tramo: las reglas y la ventana viven en el viaje."""
    kind = parse_kind(leg.kind, errors)
    origin, destination = parse_route(leg.origin, leg.destination, errors, kind)
    chosen = [p for p in dict.fromkeys(leg.providers) if p in PROVIDERS]
    providers = [p for p in chosen if PROVIDERS[p].kind == kind]
    if len(providers) < len(chosen):
        errors.append(f"Solo se pueden elegir webs de {kinds.get(kind).label.lower()}.")
    elif not providers:
        errors.append("Elige al menos un proveedor.")
    stops_text = str(leg.max_stops if leg.max_stops is not None else "").strip()
    max_stops = None
    if stops_text:
        if stops_text in ("0", "1", "2"):
            max_stops = int(stops_text)
        else:
            errors.append("El máximo de escalas debe ser 0 (solo directos), 1, 2 o vacío (sin límite).")
    return {
        "name": leg.name.strip()[:200] or f"{origin} → {destination}", "kind": kind,
        "origin": origin, "destination": destination, "providers": providers,
        "max_price": None, "discount_pct": 30.0, "date_from": None, "date_to": None,
        "max_stops": max_stops, "enabled": enabled,
    }


def with_coverage(data: dict, current: dict | None = None) -> dict:
    """Comprueba qué pares opera cada proveedor elegido (desde la caché si se acaba de comprobar)."""
    keep = current["coverage"] if current and (current["origin"], current["destination"], current["kind"]) == (
        data["origin"], data["destination"], data["kind"]) else None
    cov, errors = coverage.coverage_for(data["providers"], data["origin"], data["destination"], keep,
                                        mode=data["kind"])
    if errors:
        raise Invalid(errors)
    if keep:
        # Los que ahora no están cargados (un proveedor propio desactivado o roto) no salen en el formulario,
        # pero la vigilancia los conserva para cuando vuelvan (si no cambia la ruta).
        cov |= {k: c for k, c in keep.items() if k not in PROVIDERS}
    return {**data, "coverage": cov}


@router.get("/watches/{wid}")
def get_watch(wid: int, user: dict = Depends(current_user)):
    """Detalle de un tramo (lo pinta el detalle de su viaje): resumen por web, precios de la última
    comprobación, historial de comprobaciones y avisos. Las gráficas van aparte."""
    s = db.get_settings()
    with db.connect() as con:
        w = own_watch(con, wid, user)
        stats, rows = _provider_stats(con, s, w, detail=True)
        trip = db.get_trip(con, w["trip_id"])
        return {
            "watch": watch_view(w), "stats": stats, "prices": rows,
            "checks": db.checks_summary(con, wid, 40), "alerts": db.list_alerts(con, 15, wid),
            "trip": {"id": trip["id"], "name": trip["name"]},  # el viaje del que es tramo
        }


# --------------------------------------------------------------------- gráficas
def _align(points: dict[str, dict[str, float]]) -> dict:
    labels = sorted({label for series in points.values() for label in series})
    return {"labels": labels, "series": {pk: [s.get(label) for label in labels] for pk, s in points.items()}}


@router.get("/watches/{wid}/charts")
def charts(wid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        w = own_watch(con, wid, user)
        keys = ordered(w["providers"])
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
        series = {pk: {} for pk in ordered(w["providers"])}
        for r in db.date_history(con, wid, date):
            if r["provider"] in series:
                series[r["provider"]][r["d"]] = r["p"]
    return _align(series)


# ------------------------------------------------------- lugares y comprobación de rutas
@router.get("/places")
def search_places(q: str = "", limit: int = 10, kind: str | None = None):
    """Autocompletado de origen y destino. Con `kind` (transporte de la vigilancia), solo los lugares que tienen
    alguno de ese transporte: en una de vuelos, aeropuertos y ciudades, países o grupos con aeropuerto."""
    return {"places": places.search(q[:60], max(1, min(limit, 25)), kind if kind in kinds.KINDS else None)}


@router.get("/places/{code}")
def get_place(code: str):
    place = places.get(code)
    if not place:
        raise Invalid("Lugar desconocido.", status=404)
    return {"place": place.view()}


class RouteCheckIn(BaseModel):
    kind: str = kinds.DEFAULT
    origin: str = ""
    destination: str = ""
    providers: list[str] | None = None


@router.post("/route-check")
def route_check(body: RouteCheckIn):
    """Qué proveedores operan la ruta (en paralelo, con tiempo límite por proveedor) y por qué no los demás."""
    errors: list[str] = []
    kind = parse_kind(body.kind, errors)
    origin, destination = parse_route(body.origin, body.destination, errors, kind)
    if errors:
        raise Invalid(errors)
    pairs = places.routes(origin, destination, kind)
    keys = [k for k in (body.providers or PROVIDERS) if k in PROVIDERS and PROVIDERS[k].kind == kind]
    results = coverage.check_many(keys, pairs)
    return {"origin": places.view(origin), "destination": places.view(destination),
            "pairs": [db.pair_key(p) for p in pairs], "providers": [r.view() for r in results]}
