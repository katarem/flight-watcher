"""Viajes: poseen sus tramos (ida, vuelta y estancia, cada uno opcional) y los juntan en un precio total por fecha y
noches.

No consultan ninguna web: usan la última comprobación de cada tramo. Para cada fecha de ida `d` y cada
número de noches `n` permitido, total = transporte de ida más barato del día `d` + vuelta más barata del día `d + n`
+ alojamiento más barato con entrada `d` y `n` noches (en euros, entre todas las webs activas de cada tramo y para
todos los viajeros). Un viaje de solo ida no tiene noches (salvo que lleve estancia); uno de solo estancia, sin
transporte, va por fecha de entrada.

En cada ronda que comprueba alguno de sus tramos se guarda en `trip_quotes` la combinación más barata de
cada fecha de ida, y se aplican las reglas de aviso del viaje sobre el total: fijo (≤ `max_total`, o ≤
`max_per_person` por viajero) o relativo (≥ `discount_pct` % por debajo de la mediana histórica de esos totales).
Para no inundar los canales, solo se avisa de las `TOP_DEALS` fechas de ida más baratas que cumplen una regla, y de
cada una una sola vez (salvo que baje más).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db, fmt, notify, party, stays
from .providers import link_for, ordered, stay_link_for

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
        r["link"] = link_for(r["provider"], o, d, fmt.to_date(day))
        r["route"] = f"{o}→{d}" if (o, d) != (watch["origin"], watch["destination"]) else None
    return best


def stays_by_combo(con, settings: dict, trip: dict, watch: dict, now: datetime) -> dict[tuple[str, int], dict]:
    """Alojamiento más barato de cada combinación ((entrada ISO, noches) → fila de `prices`) entre las webs activas
    de la estancia, consultado hace menos de `STALE_DAYS`. Cada fila lleva `provider`, `link` y `offer`."""
    since = (now - timedelta(days=STALE_DAYS)).isoformat(timespec="seconds")
    today = now.date().isoformat()
    group, rooms = party.load(trip.get("party")), stays.load(watch.get("filters")).rooms
    best: dict[tuple[str, int], dict] = {}
    for key in ordered(watch["providers"]):
        if not watch["coverage"][key]["active"]:
            continue
        for r in db.latest_stays(con, watch["id"], key, since):
            k = (r["flight_date"], r["nights"])
            if r["flight_date"] >= today and (k not in best or r["price"] < best[k]["price"]):
                best[k] = {**r, "provider": key}
    for (day, n), r in best.items():
        r["link"] = (r["offer"] or {}).get("url") or stay_link_for(r["provider"], watch["destination"],
                                                                   fmt.to_date(day), n, group, rooms)
        r["route"] = None
    return best


def combinations(trip: dict, out_legs: dict[str, dict] | None, ret_legs: dict[str, dict] | None, today: date,
                 stay_legs: dict[tuple[str, int], dict] | None = None) -> list[dict]:
    """Combinaciones de un viaje, en orden de ida y noches. Cada tramo que el viaje no tiene llega como None; uno que
    tiene pero aún sin precios, vacío ({}: sin combinaciones).

    - Solo ida (sin vuelta ni estancia): una combinación por fecha de ida, sin noches.
    - Con vuelta y/o estancia: cada fecha de ida × noches con precio en todos sus tramos (vuelta el día `d + n`,
      alojamiento con entrada `d` y `n` noches).
    - Solo estancia (`out_legs` None): cada entrada × noches con alojamiento; `out_date` es la entrada.
    """
    lo = max(today.isoformat(), trip["date_from"] or "")
    hi = trip["date_to"]
    nights = range(trip["min_nights"], trip["max_nights"] + 1)
    out = []

    def add(day, n, o, r, st):
        total = sum(x["price"] for x in (o, r, st) if x)
        back = (date.fromisoformat(day) + timedelta(days=n)).isoformat() if n else None
        out.append({"out_date": day, "ret_date": back, "nights": n, "total": round(total, 2), "out": o, "ret": r,
                    "stay": st})

    if out_legs is None:
        for day, n in sorted(stay_legs or {}):
            if lo <= day and not (hi and day > hi) and n in nights:
                add(day, n, None, None, stay_legs[(day, n)])
        return out
    for day in sorted(out_legs):
        if day < lo or (hi and day > hi):
            continue
        o = out_legs[day]
        if ret_legs is None and stay_legs is None:
            add(day, None, o, None, None)
            continue
        start = date.fromisoformat(day)
        for n in nights:
            back = (start + timedelta(days=n)).isoformat()
            if ret_legs is not None and back not in ret_legs:
                continue
            if stay_legs is not None and (day, n) not in stay_legs:
                continue
            add(day, n, o, ret_legs[back] if ret_legs is not None else None,
                stay_legs[(day, n)] if stay_legs is not None else None)
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
    """'fixed' si el total baja del máximo (o del máximo por viajero), 'relative' si baja X % de lo habitual."""
    if trip["max_total"] is not None and total <= trip["max_total"]:
        return "fixed"
    per_person = trip.get("max_per_person")
    if per_person is not None and total / party.load(trip.get("party")).size <= per_person:
        return "fixed"
    if base is not None and total <= base * (1 - trip["discount_pct"] / 100):
        return "relative"
    return None


def legs(con, trip: dict) -> tuple[dict | None, dict | None, dict | None]:
    """La ida, la vuelta y la estancia del viaje (None la que no tenga: solo ida, solo estancia…)."""
    legs = db.trip_legs(con, trip["id"])
    return legs.get("outbound"), legs.get("return"), legs.get("stay")


def options(con, settings: dict, trip: dict, now: datetime) -> list[dict]:
    """Combinaciones del viaje con los precios actuales de sus tramos."""
    out_w, ret_w, stay_w = legs(con, trip)
    return combinations(
        trip, legs_by_day(con, settings, out_w, now) if out_w else None,
        legs_by_day(con, settings, ret_w, now) if ret_w else None, now.date(),
        stays_by_combo(con, settings, trip, stay_w, now) if stay_w else None)


def evaluate(trip: dict, settings: dict, now: datetime, channels: list[dict]) -> list[str]:
    """Guarda el histórico del viaje y avisa de sus chollos nuevos. Devuelve los errores de envío."""
    stamp = now.isoformat(timespec="seconds")
    with db.connect() as con:
        out_w, ret_w, stay_w = legs(con, trip)
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
    totals = {date.fromisoformat(q["out_date"]): q["total"] for q in best}
    sent, errors = notify.send_trip_deals(chans, trip, out_w, ret_w, new, base, settings.get("panel_url", ""), totals,
                                          stay_w)
    if sent:
        with db.connect() as con:
            db.add_trip_alerts(con, trip["id"], new, stamp)
    return errors
