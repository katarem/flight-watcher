"""Orquesta una ronda de comprobaciones: por cada vigilancia y proveedor consulta precios,
los guarda, aplica las reglas de aviso y notifica. Al final evalúa los viajes cuyos tramos se han comprobado."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db, fx, notify, places, trips
from .config import DEBUG_DIR
from .providers import PROVIDERS, DayPrice, ProviderBlocked, link_for, ordered

log = logging.getLogger("checker")

_lock = threading.Lock()
STATE = {"current": ""}


def is_running() -> bool:
    return _lock.locked()


def _tz(settings) -> ZoneInfo:
    try:
        return ZoneInfo(settings["timezone"])
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def deal_reason(watch: dict, price: float, base: float | None) -> str | None:
    """'fixed' si baja del precio máximo, 'relative' si baja X % de lo habitual."""
    if watch["max_price"] is not None and price <= watch["max_price"]:
        return "fixed"
    if base is not None and price <= base * (1 - watch["discount_pct"] / 100):
        return "relative"
    return None


@contextmanager
def browser_session(settings):
    """Chromium headless compartido por toda la ronda (solo se abre si algún proveedor lo necesita)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        kwargs = {"headless": settings["headless"] == "1"}
        if settings.get("proxy_url"):
            kwargs["proxy"] = {"server": settings["proxy_url"]}
        browser = pw.chromium.launch(**kwargs)
        try:
            yield browser
        finally:
            browser.close()


@contextmanager
def browser_page(browser, settings: dict | None = None):
    """Página nueva en un contexto propio (se cierra al salir)."""
    settings = settings or {}
    ctx = browser.new_context(locale="es-ES", timezone_id=settings.get("timezone", "Europe/Madrid"),
                              viewport={"width": 1366, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(20000)
    try:
        yield page
    finally:
        ctx.close()


def _save_failure(page, tag: str):
    try:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        page.screenshot(path=str(DEBUG_DIR / f"error-{tag}-{stamp}.png"))
    except Exception:  # noqa: BLE001
        pass


def _cleanup_debug(days: int = 7):
    limit = time.time() - days * 86400
    for f in DEBUG_DIR.glob("*"):
        try:
            if f.is_file() and f.stat().st_mtime < limit:
                f.unlink()
        except OSError:
            pass


def _fetch_one(browser, settings, watch, prov, origin, destination, debug_dir) -> list[DayPrice]:
    """Consulta una ruta concreta (hasta 2 intentos). Lanza la última excepción si fallan ambos."""
    months = int(settings["max_months"])
    kw = {"max_stops": watch.get("max_stops")} if prov.stops_filter else {}
    for attempt in (1, 2):
        if not prov.needs_browser:
            try:
                return prov.fetch_prices(None, origin, destination, months, debug_dir, **kw)
            except ProviderBlocked:
                raise  # si nos bloquea, reintentar solo empeora las cosas
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    raise
                log.warning("%s/%s %s-%s intento 1: %s", watch["name"], prov.key, origin, destination, exc)
                continue
        with browser_page(browser, settings) as page:
            try:
                return prov.fetch_prices(page, origin, destination, months, debug_dir, **kw)
            except Exception as exc:  # noqa: BLE001
                _save_failure(page, f"{prov.key}-{origin}-{destination}")
                if attempt == 2 or isinstance(exc, ProviderBlocked):
                    raise
                log.warning("%s/%s %s-%s intento 1: %s", watch["name"], prov.key, origin, destination, exc)
    return []


def _usable(watch, p: DayPrice) -> bool:
    """Convierte el precio a euros y dice si cumple el máximo de escalas de la vigilancia."""
    p.price_eur = fx.to_eur(p.price, p.currency)
    limit = watch.get("max_stops")
    return limit is None or p.stops is None or p.stops <= limit


def _fetch_all_routes(browser, settings, watch, prov, pairs, debug_dir) -> tuple[list[DayPrice], list[str]]:
    """Precio mínimo (en euros) por día entre los pares de aeropuertos que el proveedor cubre (TCI = TFN + TFS)."""
    best: dict = {}
    errors = []
    for origin, destination in pairs:
        try:
            found = _fetch_one(browser, settings, watch, prov, origin, destination, debug_dir)
            found = [p for p in found if _usable(watch, p)]
        except fx.FxError as exc:
            errors.append(f"{origin}-{destination}: sin cambio de divisa ({exc})")
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{origin}-{destination}: {type(exc).__name__}: {exc}".splitlines()[0][:300])
            continue
        for p in found:
            if p.day not in best or p.price_eur < best[p.day].price_eur:
                best[p.day] = p
    return [best[d] for d in sorted(best)], errors


def _check_one(browser, settings, tz, watch, prov, pairs, trigger) -> dict:
    now = datetime.now(tz).replace(tzinfo=None)
    started = now.isoformat(timespec="seconds")
    with db.connect() as con:
        run_id = db.start_run(con, watch["id"], prov.key, trigger, started)

    debug_dir = DEBUG_DIR if settings["debug"] == "1" else None
    prices, errors = _fetch_all_routes(browser, settings, watch, prov, pairs, debug_dir)
    # Solo es un fallo si no se pudo consultar ninguna ruta (p. ej. TCI: Vueling no vuela a TFS).
    error = "; ".join(errors) if errors and not prices else None
    if errors and prices:
        log.warning("%s/%s: rutas con error ignoradas: %s", watch["name"], prov.key, "; ".join(errors))

    today = datetime.now(tz).date()
    lo = max(today, date.fromisoformat(watch["date_from"])) if watch["date_from"] else today
    hi = date.fromisoformat(watch["date_to"]) if watch["date_to"] else None
    prices = [p for p in prices if p.day >= lo and (hi is None or p.day <= hi)]
    if not prices and error is None:
        error = "La web no devolvió ningún precio (¿ha cambiado o hay bloqueo?)"

    deals, base = [], None
    with db.connect() as con:
        if prices:
            base = db.baseline(con, watch["id"], prov.key, f"{today.isoformat()}T00:00:00",
                               int(settings["min_samples"]))
            db.insert_prices(con, watch["id"], prov.key, started, prices)
            for p in prices:
                reason = deal_reason(watch, p.price_eur, base)
                if reason and not db.already_alerted(con, watch["id"], prov.key, p.day.isoformat(), p.price_eur):
                    deals.append({
                        "provider": prov.key, "day": p.day, "price": p.price_eur, "reason": reason,
                        "origin": p.origin, "destination": p.destination, "stops": p.stops,
                        "currency": p.currency, "orig_price": p.price if p.currency != "EUR" else None,
                        "link": link_for(settings, prov.key, p.origin or watch["origin"],
                                         p.destination or watch["destination"], p.day),
                    })
        db.finish_run(con, run_id, datetime.now(tz).replace(tzinfo=None).isoformat(timespec="seconds"),
                      error is None, len(prices), len(deals), error)
    return {"deals": deals, "base": base, "error": error, "started": started}


def run_checks(watch_id: int | None = None, trigger: str = "cron", user_id: int | None = None,
               trip_id: int | None = None) -> str:
    """Ejecuta una ronda (de todos los usuarios, o solo de `user_id`; de una vigilancia o de los dos tramos
    de un viaje, aunque estén en pausa).

    Devuelve 'busy' si ya hay otra en marcha, 'empty' si no hay nada que hacer."""
    if not _lock.acquire(blocking=False):
        return "busy"
    try:
        settings = db.get_settings()
        tz = _tz(settings)
        with db.connect() as con:
            users = {u["id"]: u for u in db.list_users(con)}
            user_channels = {uid: db.list_channels(con, uid, only_enabled=True) for uid in users}
            trip = db.get_trip(con, trip_id) if trip_id else None
            if trip_id and not trip:
                return "empty"
            only = {trip["outbound_id"], trip["return_id"]} if trip else {watch_id} if watch_id else None
            # Las vigilancias de un usuario desactivado no se comprueban (ni se avisa a nadie).
            watches = [w for w in db.list_watches(con, user_id)
                       if users.get(w["user_id"], {}).get("enabled")
                       and (w["id"] in only if only else w["enabled"])]
            # Viajes: el pedido o los activos con algún tramo en esta ronda.
            checked = {w["id"] for w in watches}
            trip_list = [trip] if trip else [t for t in db.list_trips(con, user_id) if t["enabled"]
                                             and {t["outbound_id"], t["return_id"]} & checked]
            trip_list = [t for t in trip_list if users.get(t["user_id"], {}).get("enabled")]
        if not watches:
            return "empty"

        problems: dict[int, list[str]] = {}  # por usuario: cada uno recibe solo los suyos
        needs_browser = any(PROVIDERS[k].needs_browser for w in watches for k, c in w["coverage"].items()
                            if k in PROVIDERS and c["active"])
        with (browser_session(settings) if needs_browser else nullcontext()) as browser:
            for w in watches:
                owner = users[w["user_id"]]
                mine = problems.setdefault(owner["id"], [])
                all_deals, baselines, last_started = [], {}, None
                for key in ordered(w["providers"]):
                    prov, cov = PROVIDERS[key], w["coverage"][key]
                    if not cov["active"]:  # no opera la ruta ahora (p. ej. de temporada): ni se consulta
                        continue
                    pairs = cov["routes"] or places.routes(w["origin"], w["destination"])
                    STATE["current"] = f"{w['name']} · {prov.label}"
                    res = _check_one(browser, settings, tz, w, prov, pairs, trigger)
                    all_deals += res["deals"]
                    baselines[key] = res["base"]
                    last_started = res["started"]
                    if res["error"]:
                        mine.append(f"{w['name']} · {prov.label}: {res['error']}")

                if all_deals:
                    # Solo los canales que el usuario asignó a esta vigilancia (y siguen activos).
                    chans = [c for c in user_channels[owner["id"]] if c["id"] in w["channel_ids"]]
                    if not chans:  # sin marcar como avisados: se reenviarán cuando asigne algún canal
                        log.info("Hay chollos en «%s» pero no tiene canales de aviso activos", w["name"])
                        continue
                    sent, errs = notify.send_deals(chans, w, all_deals, baselines, settings.get("panel_url", ""))
                    mine += [f"{w['name']}: {e}" for e in errs]
                    if sent:  # solo se marcan como avisadas si llegaron a algún canal
                        with db.connect() as con:
                            db.add_alerts(con, w["id"], all_deals, last_started)

        for t in trip_list:
            STATE["current"] = f"Viaje {t['name']}"
            errs = trips.evaluate(t, settings, datetime.now(tz).replace(tzinfo=None), user_channels[t["user_id"]])
            problems.setdefault(t["user_id"], []).extend(f"{t['name']}: {e}" for e in errs)

        if trigger == "cron":
            for uid, items in problems.items():
                if items and users[uid]["notify_errors"]:
                    notify.send_text(user_channels[uid],
                                     "⚠️ Flight Watcher: hubo problemas\n" + "\n".join(f"• {p}" for p in items))

        with db.connect() as con:
            db.purge(con, int(settings["retention_days"]))
        _cleanup_debug()
        return "done"
    finally:
        STATE["current"] = ""
        _lock.release()
