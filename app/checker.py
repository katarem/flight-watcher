"""Orquesta una ronda de comprobaciones: por cada vigilancia y proveedor consulta precios,
los guarda, aplica las reglas de aviso y notifica."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import db, notify
from .config import DEBUG_DIR
from .providers import PROVIDERS, DayPrice, link_for, routes

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
    for attempt in (1, 2):
        if not prov.needs_browser:
            try:
                return prov.fetch_prices(None, origin, destination, int(settings["max_months"]), debug_dir)
            except Exception as exc:  # noqa: BLE001
                if attempt == 2:
                    raise
                log.warning("%s/%s %s-%s intento 1: %s", watch["name"], prov.key, origin, destination, exc)
                continue
        ctx = browser.new_context(
            locale="es-ES", timezone_id=settings["timezone"], viewport={"width": 1366, "height": 900}
        )
        page = ctx.new_page()
        page.set_default_timeout(20000)
        try:
            return prov.fetch_prices(page, origin, destination, int(settings["max_months"]), debug_dir)
        except Exception as exc:  # noqa: BLE001
            _save_failure(page, f"{prov.key}-{origin}-{destination}")
            if attempt == 2:
                raise
            log.warning("%s/%s %s-%s intento 1: %s", watch["name"], prov.key, origin, destination, exc)
        finally:
            ctx.close()
    return []


def _fetch_all_routes(browser, settings, watch, prov, debug_dir) -> tuple[list[DayPrice], list[str]]:
    """Precio mínimo por día entre todos los aeropuertos que cubre la vigilancia (TCI = TFN + TFS)."""
    best: dict = {}
    errors = []
    for origin, destination in routes(watch["origin"], watch["destination"]):
        try:
            found = _fetch_one(browser, settings, watch, prov, origin, destination, debug_dir)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{origin}-{destination}: {type(exc).__name__}: {exc}".splitlines()[0][:300])
            continue
        for p in found:
            if p.day not in best or p.price < best[p.day].price:
                best[p.day] = p
    return [best[d] for d in sorted(best)], errors


def _check_one(browser, settings, tz, watch, prov, trigger) -> dict:
    now = datetime.now(tz).replace(tzinfo=None)
    started = now.isoformat(timespec="seconds")
    with db.connect() as con:
        run_id = db.start_run(con, watch["id"], prov.key, trigger, started)

    debug_dir = DEBUG_DIR if settings["debug"] == "1" else None
    prices, errors = _fetch_all_routes(browser, settings, watch, prov, debug_dir)
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
                reason = deal_reason(watch, p.price, base)
                if reason and not db.already_alerted(con, watch["id"], prov.key, p.day.isoformat(), p.price):
                    deals.append({
                        "provider": prov.key, "day": p.day, "price": p.price, "reason": reason,
                        "origin": p.origin, "destination": p.destination,
                        "link": link_for(settings, prov.key, p.origin or watch["origin"],
                                         p.destination or watch["destination"], p.day),
                    })
        db.finish_run(con, run_id, datetime.now(tz).replace(tzinfo=None).isoformat(timespec="seconds"),
                      error is None, len(prices), len(deals), error)
    return {"deals": deals, "base": base, "error": error, "started": started}


def run_checks(watch_id: int | None = None, trigger: str = "cron", user_id: int | None = None) -> str:
    """Ejecuta una ronda (de todos los usuarios, o solo de `user_id`).

    Devuelve 'busy' si ya hay otra en marcha, 'empty' si no hay nada que hacer."""
    if not _lock.acquire(blocking=False):
        return "busy"
    try:
        settings = db.get_settings()
        tz = _tz(settings)
        with db.connect() as con:
            users = {u["id"]: u for u in db.list_users(con)}
            user_channels = {uid: db.list_channels(con, uid, only_enabled=True) for uid in users}
            # Las vigilancias de un usuario desactivado no se comprueban (ni se avisa a nadie).
            watches = [w for w in db.list_watches(con, user_id)
                       if users.get(w["user_id"], {}).get("enabled")
                       and (w["id"] == watch_id if watch_id else w["enabled"])]
        if not watches:
            return "empty"

        problems: dict[int, list[str]] = {}  # por usuario: cada uno recibe solo los suyos
        needs_browser = any(PROVIDERS[k].needs_browser for w in watches for k in w["providers"] if k in PROVIDERS)
        with (browser_session(settings) if needs_browser else nullcontext()) as browser:
            for w in watches:
                owner = users[w["user_id"]]
                mine = problems.setdefault(owner["id"], [])
                all_deals, baselines, last_started = [], {}, None
                for key in w["providers"]:
                    prov = PROVIDERS.get(key)
                    if not prov:
                        continue
                    STATE["current"] = f"{w['name']} · {prov.label}"
                    res = _check_one(browser, settings, tz, w, prov, trigger)
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
