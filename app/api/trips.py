"""Viajes: la entidad principal. CRUD con sus tramos inline (ida; vuelta, solo con ida; y estancia: al menos la ida
o la estancia), sus viajeros, combinaciones actuales, histórico y avisos. Un viaje posee sus tramos (vigilancias
internas)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from .. import db, kinds, party, places, scheduler, stays, trips
from ..providers import PROVIDERS, ordered
from .deps import Invalid, current_user, own_channel_ids, own_trip
from .watches import LegIn, parse_dates, parse_leg, parse_number, price_extras, watch_view, with_coverage

router = APIRouter()


def _leg_view(w: dict | None) -> dict | None:
    """El tramo con todo lo que el panel necesita para pintarlo y para editarlo dentro del viaje."""
    if w is None:
        return None
    v = watch_view(w)
    return {k: v[k] for k in ("id", "name", "kind", "origin", "destination", "origin_place",
                              "destination_place", "providers", "coverage", "max_stops", "enabled")}


def _stay_view(w: dict | None) -> dict | None:
    """La estancia: destino (texto), webs y filtros."""
    if w is None:
        return None
    f = stays.load(w.get("filters"))
    return {"id": w["id"], "name": w["name"], "kind": w["kind"], "destination": w["destination"],
            "providers": ordered(w["providers"]), "enabled": bool(w["enabled"]), "filters": f.view(), "filters_label": f.describe()}


def _warnings(out_w: dict, ret_w: dict) -> list[str]:
    """Avisos que no impiden guardar: tramos que no encajan (p. ej. ida a TFN y vuelta desde TFS)."""
    out = []
    if out_w["kind"] != ret_w["kind"]:
        out.append("La ida y la vuelta son de transportes distintos.")

    def nodes(code: str, w: dict) -> set[str]:
        return set(places.nodes(code, w["kind"]))

    if not nodes(out_w["destination"], out_w) & nodes(ret_w["origin"], ret_w):
        out.append(f"La vuelta sale de {ret_w['origin']} y la ida llega a {out_w['destination']}.")
    if not nodes(ret_w["destination"], ret_w) & nodes(out_w["origin"], out_w):
        out.append(f"La vuelta llega a {ret_w['destination']} y la ida sale de {out_w['origin']}.")
    return out


def trip_view(t: dict, out_w: dict | None, ret_w: dict | None, stay_w: dict | None = None) -> dict:
    """El viaje con sus tramos (None el que no tenga) y sus viajeros. El transporte (`kind`) se deriva del tramo de
    ida (en uno de solo estancia, el del alojamiento)."""
    return {k: t[k] for k in ("id", "name", "min_nights", "max_nights", "date_from", "date_to", "max_total",
                              "discount_pct", "channel_ids", "created_at")} | {
        "enabled": bool(t["enabled"]), "kind": out_w["kind"] if out_w else kinds.STAY,
        "outbound": _leg_view(out_w), "return": _leg_view(ret_w), "stay": _stay_view(stay_w),
        "party": party.load(t.get("party")).view(), "max_per_person": t.get("max_per_person"),
        "warnings": _warnings(out_w, ret_w) if out_w and ret_w else [],
    }


def _price_view(r: dict | None) -> dict | None:
    if r is None:
        return None
    return {k: r.get(k) for k in ("flight_date", "price", "provider", "route", "link", "checked_at", "nights",
                                  "offer")} | price_extras(r)


def combo_view(c: dict, trip: dict, base: float | None) -> dict:
    size = party.load(trip.get("party")).size
    return {k: c[k] for k in ("out_date", "ret_date", "nights", "total")} | {
        "deal": trips.deal_reason(trip, c["total"], base), "per_person": round(c["total"] / size, 2),
        "out": _price_view(c["out"]), "ret": _price_view(c["ret"]),  # None si el viaje no tiene ese tramo
        "stay": _price_view(c.get("stay")),
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
            combos, base = _current(con, s, t)
            best = min(combos, key=lambda c: (c["total"], c["out_date"], c["nights"] or 0), default=None)
            out.append({**trip_view(t, *trips.legs(con, t)), "base": base, "best": best and combo_view(best, t, base),
                        "n_dates": len({c["out_date"] for c in combos}), "trend": db.trip_trend(con, t["id"])[-30:],
                        "channels": [names[i] for i in t["channel_ids"] if i in names]})
    return {"trips": out}


# ------------------------------------------------------------------------- CRUD
class StayIn(BaseModel):
    """La estancia de un viaje: destino en texto libre, webs de alojamiento y filtros (ver app/stays.py)."""
    name: str = ""
    destination: str = ""
    providers: list[str] = []
    filters: dict | None = None


class TripIn(BaseModel):
    model_config = {"populate_by_name": True}
    name: str = ""
    outbound: LegIn | None = None               # tramo de ida (sin ida = solo estancia)
    inbound: LegIn | None = Field(default=None, alias="return")  # tramo de vuelta (opcional = solo ida)
    stay: StayIn | None = None                  # estancia (opcional)
    #: Viajeros: {"travelers": [{"age": None | 0–17, "resident": "" | "canarias"…}], "large_family": ""}.
    party: dict | None = None
    max_per_person: float | str | None = None
    min_nights: int | str | None = None
    max_nights: int | str | None = None
    date_from: str | None = None
    date_to: str | None = None
    max_total: float | str | None = None
    discount_pct: float | str | None = None
    enabled: bool = True
    channel_ids: list[int] = []


def parse_trip(body: TripIn, current_legs: dict | None = None) -> dict:
    """Datos listos para guardar (con la cobertura de cada tramo) o `Invalid` con todos los errores.

    `current_legs` ({role: vigilancia}) al editar: conserva la cobertura de un tramo si no cambia su ruta."""
    errors: list[str] = []

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
    per_person = parse_number(body.max_per_person, "El precio máximo por persona", errors)
    disc = parse_number(body.discount_pct, "El descuento", errors, default=30.0, lo=-1.0, hi=95.0)
    d_from, d_to = parse_dates(body.date_from, body.date_to, errors)
    group = party.parse(body.party, errors)
    if body.outbound is None and body.stay is None:
        errors.append("Un viaje necesita el tramo de ida, la estancia o los dos.")
        raise Invalid(errors)
    if body.outbound is None and body.inbound is not None:
        errors.append("Un viaje con vuelta necesita también la ida.")
    out_data = parse_leg(body.outbound, errors, body.enabled) if body.outbound is not None else None
    ret_data = parse_leg(body.inbound, errors, body.enabled) if body.inbound is not None else None
    stay_data = parse_stay(body.stay, errors, body.enabled) if body.stay is not None else None
    if errors:
        raise Invalid(errors)
    current_legs = current_legs or {}
    out_cov = with_coverage(out_data, current_legs.get("outbound")) if out_data else None
    ret_cov = with_coverage(ret_data, current_legs.get("return")) if ret_data else None
    if stay_data:
        # Como en los transportes: las webs que ahora no están cargadas (desactivadas o rotas) se conservan.
        keep = (current_legs.get("stay") or {}).get("coverage", {})
        stay_data["coverage"] = {k: {"routes": [], "active": True, "checked_at": None} for k in stay_data["providers"]}
        stay_data["coverage"] |= {k: c for k, c in keep.items() if k not in PROVIDERS}
    if out_data:
        name = f"{out_data['origin']} {'⇄' if ret_data else '→'} {out_data['destination']}"
        name += f" · {stay_data['destination']}" if stay_data else ""
    else:
        name = f"Estancia en {stay_data['destination']}"
    return {
        "name": body.name.strip()[:200] or name[:200],
        "min_nights": lo, "max_nights": hi, "date_from": d_from, "date_to": d_to, "max_total": max_total,
        "max_per_person": per_person, "party": group.to_json(),
        "discount_pct": disc if disc is not None else 30.0, "enabled": body.enabled,
        "outbound": out_cov, "return": ret_cov, "stay": stay_data,
    }


def parse_stay(body: StayIn, errors: list[str], enabled: bool) -> dict:
    """Valida la estancia y devuelve los datos para `db.create_watch` (los errores se acumulan en `errors`)."""
    destination = " ".join(body.destination.split())
    if len(destination) < 2:
        errors.append("Indica el destino del alojamiento (una ciudad, una isla, una zona…).")
    elif len(destination) > stays.PLACE_MAX:
        errors.append(f"El destino del alojamiento es demasiado largo (como mucho {stays.PLACE_MAX} caracteres).")
        destination = destination[:stays.PLACE_MAX]
    chosen = [k for k in dict.fromkeys(body.providers) if k in PROVIDERS]
    providers = [k for k in chosen if PROVIDERS[k].kind == kinds.STAY]
    if len(providers) < len(chosen):
        errors.append("Para el alojamiento solo se pueden elegir webs de alojamiento.")
    elif not providers:
        errors.append("Elige al menos una web de alojamiento.")
    filters = stays.parse(body.filters, errors)
    return {
        "name": body.name.strip()[:200] or f"Alojamiento en {destination}"[:200], "kind": kinds.STAY,
        "origin": "", "destination": destination, "providers": providers, "filters": filters.to_json(),
        "max_price": None, "discount_pct": 30.0, "date_from": None, "date_to": None, "max_stops": None,
        "enabled": enabled,
    }


def _saved(con, tid: int) -> dict:
    t = db.get_trip(con, tid)
    return {"trip": trip_view(t, *trips.legs(con, t))}


@router.post("/trips", status_code=201)
def create_trip(body: TripIn, user: dict = Depends(current_user)):
    data = parse_trip(body)
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
        current_legs = db.trip_legs(con, tid)
    data = parse_trip(body, current_legs)
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
    """Comprueba ahora los tramos del viaje (aunque esté en pausa) y después el viaje."""
    with db.connect() as con:
        own_trip(con, tid, user)
    return {"started": scheduler.run_now(user_id=user["id"], trip_id=tid)}
