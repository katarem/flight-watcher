"""Viajes de ida y vuelta del usuario: CRUD, combinaciones actuales, histórico y avisos."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from .. import db, places, scheduler, trips
from .deps import Invalid, current_user, own_channel_ids, own_trip
from .watches import parse_dates, parse_number

router = APIRouter()


def _leg_view(w: dict) -> dict:
    return {k: w[k] for k in ("id", "name", "origin", "destination")} | {"enabled": bool(w["enabled"])}


def _warnings(out_w: dict, ret_w: dict) -> list[str]:
    """Avisos que no impiden guardar: tramos en pausa o que no encajan (p. ej. ida a TFN y vuelta desde TFS)."""
    out = []
    if not set(places.airports(out_w["destination"])) & set(places.airports(ret_w["origin"])):
        out.append(f"La vuelta sale de {ret_w['origin']} y la ida llega a {out_w['destination']}.")
    if not set(places.airports(ret_w["destination"])) & set(places.airports(out_w["origin"])):
        out.append(f"La vuelta llega a {ret_w['destination']} y la ida sale de {out_w['origin']}.")
    for label, w in (("ida", out_w), ("vuelta", ret_w)):
        if not w["enabled"]:
            out.append(f"La vigilancia de {label} («{w['name']}») está en pausa: sus precios no se actualizan.")
    return out


def trip_view(t: dict, out_w: dict, ret_w: dict) -> dict:
    return {k: t[k] for k in ("id", "name", "outbound_id", "return_id", "min_nights", "max_nights", "date_from",
                              "date_to", "max_total", "discount_pct", "channel_ids", "created_at")} | {
        "enabled": bool(t["enabled"]), "outbound": _leg_view(out_w), "return": _leg_view(ret_w),
        "warnings": _warnings(out_w, ret_w),
    }


def _price_view(r: dict) -> dict:
    return {k: r.get(k) for k in ("flight_date", "price", "provider", "route", "link", "orig_price", "stops",
                                  "checked_at")} | {"currency": r.get("currency") or "EUR"}


def combo_view(c: dict, trip: dict, base: float | None) -> dict:
    return {k: c[k] for k in ("out_date", "ret_date", "nights", "total")} | {
        "deal": trips.deal_reason(trip, c["total"], base), "out": _price_view(c["out"]), "ret": _price_view(c["ret"]),
    }


def _current(con, settings: dict, t: dict) -> tuple[list[dict], float | None]:
    """Combinaciones con los precios actuales de los tramos y el total habitual del viaje."""
    now = trips.local_now(settings)
    base = db.trip_baseline(con, t["id"], f"{now.date().isoformat()}T00:00:00", int(settings["min_samples"]))
    return trips.options(con, settings, t, now), base


# ------------------------------------------------------------------------- lista
@router.get("/trips")
def list_trips(user: dict = Depends(current_user)):
    s = db.get_settings()
    out = []
    with db.connect() as con:
        names = {c["id"]: c["name"] for c in db.list_channels(con, user["id"], only_enabled=True)}
        for t in db.list_trips(con, user["id"]):
            out_w, ret_w = trips.legs(con, t)
            combos, base = _current(con, s, t)
            best = min(combos, key=lambda c: (c["total"], c["out_date"], c["nights"]), default=None)
            out.append({**trip_view(t, out_w, ret_w), "base": base, "best": best and combo_view(best, t, base),
                        "n_dates": len({c["out_date"] for c in combos}), "trend": db.trip_trend(con, t["id"])[-30:],
                        "channels": [names[i] for i in t["channel_ids"] if i in names]})
    return {"trips": out}


# ------------------------------------------------------------------------- CRUD
class TripIn(BaseModel):
    name: str = ""
    outbound_id: int | str | None = None
    return_id: int | str | None = None
    min_nights: int | str | None = None
    max_nights: int | str | None = None
    date_from: str | None = None
    date_to: str | None = None
    max_total: float | str | None = None
    discount_pct: float | str | None = None
    enabled: bool = True
    channel_ids: list[int] = []


def parse_trip(body: TripIn, user: dict) -> dict:
    """Datos listos para guardar o `Invalid` con todos los errores encontrados."""
    errors: list[str] = []
    with db.connect() as con:
        mine = {w["id"]: w for w in db.list_watches(con, user["id"])}

    def leg(value, label):
        try:
            wid = int(str(value).strip())
        except ValueError:
            wid = 0
        if wid not in mine:
            errors.append(f"Elige la vigilancia de {label} entre las tuyas.")
            return None
        return wid

    out_id, ret_id = leg(body.outbound_id, "ida"), leg(body.return_id, "vuelta")
    if out_id and out_id == ret_id:
        errors.append("La ida y la vuelta tienen que ser vigilancias distintas.")

    def nights(value, label, default):
        text = str(value if value is not None else "").strip()
        if not text:
            return default
        if not text.isdigit() or not 1 <= int(text) <= trips.MAX_NIGHTS:
            errors.append(f"{label} deben ser un número entero entre 1 y {trips.MAX_NIGHTS}.")
            return default
        return int(text)

    lo = nights(body.min_nights, "Las noches mínimas", 1)
    hi = nights(body.max_nights, "Las noches máximas", lo)
    if lo > hi:
        errors.append("Las noches mínimas no pueden ser más que las máximas.")
    max_total = parse_number(body.max_total, "El precio total máximo", errors)
    disc = parse_number(body.discount_pct, "El descuento", errors, default=30.0, lo=-1.0, hi=95.0)
    d_from, d_to = parse_dates(body.date_from, body.date_to, errors)
    if errors:
        raise Invalid(errors)
    out_w, ret_w = mine[out_id], mine[ret_id]
    return {
        "name": body.name.strip()[:200] or f"{out_w['origin']} ⇄ {out_w['destination']}",
        "outbound_id": out_id, "return_id": ret_id, "min_nights": lo, "max_nights": hi,
        "date_from": d_from, "date_to": d_to, "max_total": max_total,
        "discount_pct": disc if disc is not None else 30.0, "enabled": body.enabled,
    }


def _saved(con, tid: int) -> dict:
    t = db.get_trip(con, tid)
    return {"trip": trip_view(t, *trips.legs(con, t))}


@router.post("/trips", status_code=201)
def create_trip(body: TripIn, user: dict = Depends(current_user)):
    data = parse_trip(body, user)
    channel_ids = own_channel_ids(user, body.channel_ids)
    with db.connect() as con:
        tid = db.create_trip(con, user["id"], data)
        db.set_trip_channels(con, tid, channel_ids)
        return _saved(con, tid)


@router.get("/trips/{tid}")
def get_trip(tid: int, user: dict = Depends(current_user)):
    """El viaje con la combinación más barata de cada fecha de ida, su evolución y los avisos enviados."""
    s = db.get_settings()
    with db.connect() as con:
        t = own_trip(con, tid, user)
        combos, base = _current(con, s, t)
        return {
            **_saved(con, tid), "base": base,
            "quotes": [combo_view(c, t, base) for c in trips.best_per_day(combos)],
            "trend": db.trip_trend(con, tid), "alerts": db.list_trip_alerts(con, tid),
        }


@router.get("/trips/{tid}/options")
def trip_options(tid: int, date: str, user: dict = Depends(current_user)):
    """Todas las noches posibles para una fecha de ida."""
    s = db.get_settings()
    with db.connect() as con:
        t = own_trip(con, tid, user)
        combos, base = _current(con, s, t)
    return {"options": [combo_view(c, t, base) for c in combos if c["out_date"] == date]}


@router.put("/trips/{tid}")
def update_trip(tid: int, body: TripIn, user: dict = Depends(current_user)):
    with db.connect() as con:
        own_trip(con, tid, user)
    data = parse_trip(body, user)
    channel_ids = own_channel_ids(user, body.channel_ids)
    with db.connect() as con:
        db.update_trip(con, tid, data)
        db.set_trip_channels(con, tid, channel_ids)
        return _saved(con, tid)


@router.delete("/trips/{tid}", status_code=204)
def delete_trip(tid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        own_trip(con, tid, user)
        db.delete_trip(con, tid)
    return Response(status_code=204)


@router.post("/trips/{tid}/toggle")
def toggle_trip(tid: int, user: dict = Depends(current_user)):
    with db.connect() as con:
        own_trip(con, tid, user)
        db.toggle_trip(con, tid)
        return _saved(con, tid)


@router.post("/trips/{tid}/run")
def run_trip(tid: int, user: dict = Depends(current_user)):
    """Comprueba ahora los dos tramos del viaje (aunque estén en pausa) y después el viaje."""
    with db.connect() as con:
        own_trip(con, tid, user)
    return {"started": scheduler.run_now(user_id=user["id"], trip_id=tid)}
