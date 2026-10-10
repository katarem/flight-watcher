"""Viajes de ida y vuelta: juntan dos vigilancias (ida y vuelta) en un precio total por fecha y noches.

No consultan ninguna web: usan la última comprobación de cada tramo. Para cada fecha de ida `d` y cada
número de noches `n` permitido, total = vuelo de ida más barato del día `d` + vuelo de vuelta más barato
del día `d + n` (en euros, entre todas las webs activas de cada vigilancia).

En cada ronda que comprueba alguno de sus tramos se guarda en `trip_quotes` la combinación más barata de
cada fecha de ida, y se aplican las reglas de aviso de las vigilancias sobre el total: fijo (≤ `max_total`)
o relativo (≥ `discount_pct` % por debajo de la mediana histórica de esos totales). Para no inundar los
canales, solo se avisa de las `TOP_DEALS` fechas de ida más baratas que cumplen una regla, y de cada una
una sola vez (salvo que baje más).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db, fmt, notify
from .providers import link_for, ordered

log = logging.getLogger("trips")

#: Precios de un tramo más antiguos que esto no cuentan (p. ej. una web que ha dejado de responder).
STALE_DAYS = 3
#: Fechas de ida de las que se avisa como mucho en cada ronda (las más baratas).
TOP_DEALS = 5
MAX_NIGHTS = 60


def local_now(settings: dict) -> datetime:
    """Hora local de Ajustes sin zona (como se guardan las fechas de comprobación)."""
    try:
        tz = ZoneInfo(settings["timezone"])
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    return datetime.now(tz).replace(tzinfo=None)


def legs_by_day(con, settings: dict, watch: dict, now: datetime) -> dict[str, dict]:
    """Vuelo más barato de cada día (fecha ISO → fila de `prices`) entre las webs activas de la vigilancia,
    en su última comprobación si es reciente. Cada fila lleva `provider`, `link` y `route`."""
    since = (now - timedelta(days=STALE_DAYS)).isoformat(timespec="seconds")
    today = now.date().isoformat()
    best: dict[str, dict] = {}
    for key in ordered(watch["providers"]):
        if not watch["coverage"][key]["active"]:
            continue
        for r in db.latest_snapshot(con, watch["id"], key):
            if r["checked_at"] < since or r["flight_date"] < today:
                continue
            cur = best.get(r["flight_date"])
            if cur is None or r["price"] < cur["price"]:
                best[r["flight_date"]] = {**r, "provider": key}
    for day, r in best.items():
        o, d = r["origin"] or watch["origin"], r["destination"] or watch["destination"]
        r["link"] = link_for(settings, r["provider"], o, d, fmt.to_date(day))
        r["route"] = f"{o}→{d}" if (o, d) != (watch["origin"], watch["destination"]) else None
    return best


def combinations(trip: dict, out_legs: dict[str, dict], ret_legs: dict[str, dict], today: date) -> list[dict]:
    """Todas las combinaciones (fecha de ida × noches) con vuelo en ambos sentidos, en orden de ida y noches."""
    lo = max(today.isoformat(), trip["date_from"] or "")
    hi = trip["date_to"]
    out = []
    for day in sorted(out_legs):
        if day < lo or (hi and day > hi):
            continue
        start = date.fromisoformat(day)
        for n in range(trip["min_nights"], trip["max_nights"] + 1):
            back = (start + timedelta(days=n)).isoformat()
            if back in ret_legs:
                o, r = out_legs[day], ret_legs[back]
                out.append({"out_date": day, "ret_date": back, "nights": n, "total": round(o["price"] + r["price"], 2),
                            "out": o, "ret": r})
    return out


def best_per_day(combos: list[dict]) -> list[dict]:
    """La combinación más barata de cada fecha de ida (a igual precio, la de menos noches), por fecha."""
    best: dict[str, dict] = {}
    for c in combos:
        cur = best.get(c["out_date"])
        if cur is None or c["total"] < cur["total"]:
            best[c["out_date"]] = c
    return [best[d] for d in sorted(best)]


def deal_reason(trip: dict, total: float, base: float | None) -> str | None:
    """'fixed' si el total baja del máximo, 'relative' si baja X % de lo habitual (como `checker.deal_reason`)."""
    if trip["max_total"] is not None and total <= trip["max_total"]:
        return "fixed"
    if base is not None and total <= base * (1 - trip["discount_pct"] / 100):
        return "relative"
    return None


def legs(con, trip: dict) -> tuple[dict, dict]:
    """Las vigilancias de ida y de vuelta del viaje."""
    return db.get_watch(con, trip["outbound_id"]), db.get_watch(con, trip["return_id"])


def options(con, settings: dict, trip: dict, now: datetime) -> list[dict]:
    """Combinaciones del viaje con los precios actuales de sus tramos."""
    out_w, ret_w = legs(con, trip)
    return combinations(trip, legs_by_day(con, settings, out_w, now), legs_by_day(con, settings, ret_w, now), now.date())


def evaluate(trip: dict, settings: dict, now: datetime, channels: list[dict]) -> list[str]:
    """Guarda el histórico del viaje y avisa de sus chollos nuevos. Devuelve los errores de envío."""
    stamp = now.isoformat(timespec="seconds")
    with db.connect() as con:
        out_w, ret_w = legs(con, trip)
        best = best_per_day(options(con, settings, trip, now))
        if not best:
            return []
        base = db.trip_baseline(con, trip["id"], f"{now.date().isoformat()}T00:00:00", int(settings["min_samples"]))
        db.insert_trip_quotes(con, trip["id"], stamp, best)
        deals = sorted((q for q in best if deal_reason(trip, q["total"], base)),
                       key=lambda q: (q["total"], q["out_date"]))[:TOP_DEALS]
        new = [q for q in deals if not db.trip_already_alerted(con, trip["id"], q["out_date"], q["total"])]
    if not new:
        return []
    chans = [c for c in channels if c["id"] in trip["channel_ids"]]
    if not chans:  # sin marcar como avisados: se reenviarán cuando asigne algún canal
        log.info("Hay chollos en el viaje «%s» pero no tiene canales de aviso activos", trip["name"])
        return []
    sent, errors = notify.send_trip_deals(chans, trip, out_w, ret_w, new, base, settings.get("panel_url", ""))
    if sent:
        with db.connect() as con:
            db.add_trip_alerts(con, trip["id"], new, stamp)
    return errors
