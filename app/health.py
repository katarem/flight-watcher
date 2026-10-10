"""Prueba de acceso a los proveedores (zona «Proveedores» del administrador), como un healthcheck.

Por cada proveedor se hacen, en su turno de peticiones y desde la IP del panel, los mismos pasos que en
una ronda pero sobre una sola ruta: la cobertura (red de rutas o pregunta directa) y los precios de un
mes. Cada paso dice si fue bien, si la web nos bloquea (403/429/anti-bot), si falló o si no respondió a
tiempo. El resultado se guarda en `provider_health`. También se prueban el cambio de divisas del BCE y
las portadas de las aerolíneas en estudio (`providers/candidates.py`).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime

import requests

from . import db, fx
from .providers import PROVIDERS, ProviderBlocked, ProviderError, ordered
from .providers.base import USER_AGENT
from .providers.candidates import CANDIDATES, antibot

#: Tiempo máximo de la prueba de un proveedor.
TIMEOUT = 60.0
#: Gravedad de cada estado (el peor paso decide el estado del proveedor).
SEVERITY = {"ok": 0, "skipped": 0, "empty": 1, "error": 2, "timeout": 3, "blocked": 4}
STATUS_LABELS = {"ok": "Accesible", "empty": "Accesible, sin precios", "blocked": "Bloqueado",
                 "error": "Con errores", "timeout": "Sin respuesta", "skipped": "Omitido"}


def worst(steps: list[dict]) -> str:
    """Estado del conjunto: el peor de los pasos que se hicieron («omitido» solo si se omitieron todos)."""
    done = [s["status"] for s in steps if s["status"] != "skipped"]
    return max(done, key=lambda st: SEVERITY[st]) if done else "skipped"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _step(name: str, fn) -> dict:
    """Ejecuta un paso y lo clasifica. `fn` devuelve (estado, detalle)."""
    started = time.monotonic()
    http = None
    try:
        status, detail = fn()
    except ProviderBlocked as exc:
        status, detail, http = "blocked", str(exc), exc.status
    except ProviderError as exc:
        status, detail = ("timeout" if "tiempo agotado" in str(exc) else "error"), str(exc)
    except Exception as exc:  # noqa: BLE001 - la prueba informa de cualquier fallo
        status, detail = "error", f"{type(exc).__name__}: {exc}"[:300]
    return {"name": name, "status": status, "detail": detail, "http_status": http,
            "ms": int((time.monotonic() - started) * 1000)}


def _coverage_step(prov, origin, destination) -> dict:
    def run():
        with prov.new_session() as s:
            if prov.coverage == "network":
                dests = prov.network(s, origin)
                if not dests:
                    return "empty", f"La red de rutas no tiene destinos desde {origin}."
                where = "incluye" if destination in dests else "no incluye"
                n = len(dests)
                return "ok", f"{n} destino{'s' if n != 1 else ''} directo{'s' if n != 1 else ''} desde {origin} ({where} {destination})."
            if prov.coverage == "probe":
                ok = prov.probe(s, origin, destination)
                return "ok", f"Responde: {'opera' if ok else 'no opera'} {origin}→{destination}."
        return "skipped", "Cubre cualquier ruta: no hay red que consultar."
    return _step("Cobertura", run)


def _prices_step(prov, origin, destination, browser_factory=None, sink: list | None = None) -> dict:
    """Precios de un mes. Si se pasa `sink`, deja ahí los precios encontrados."""
    def run():
        kw = {"max_stops": 0} if prov.stops_filter else {}
        if prov.needs_browser:
            if browser_factory is None:
                return "skipped", "Necesita navegador: marca «Probar también con navegador»."
            from .checker import browser_page
            with browser_factory() as browser, browser_page(browser) as page:
                found = prov.fetch_prices(page, origin, destination, 1, None)
        else:
            found = prov.fetch_prices(None, origin, destination, 1, None, **kw)
        if sink is not None:
            sink.extend(found)
        if not found:
            return "empty", f"Sin precios para {origin}→{destination} en el próximo mes (¿ruta sin vuelos ahora?)."
        cheapest = min(found, key=lambda p: p.price)
        cur = {p.currency for p in found}
        return "ok", (f"{len(found)} días con precio para {origin}→{destination}; el más barato, "
                      f"{cheapest.price:g} {cheapest.currency} el {cheapest.day:%d/%m}"
                      + (f" (monedas: {', '.join(sorted(cur))})" if len(cur) > 1 else "") + ".")
    return _step("Precios (1 mes)", run)


def check_provider(key: str, origin: str | None = None, destination: str | None = None,
                   browser_factory=None) -> dict:
    prov = PROVIDERS[key]
    o, d = origin or prov.health_route[0], destination or prov.health_route[1]
    started = time.monotonic()
    steps = [_coverage_step(prov, o, d)]
    if steps[0]["status"] != "blocked":  # si ya nos bloquea, no insistir
        steps.append(_prices_step(prov, o, d, browser_factory))
    status = worst(steps)
    result = {"key": key, "status": status, "route": f"{o}→{d}", "steps": steps,
              "latency_ms": int((time.monotonic() - started) * 1000), "checked_at": _now()}
    with db.connect() as con:
        db.save_health(con, key, status, [{**s, "route": result["route"]} for s in steps], result["latency_ms"],
                       result["checked_at"])
    return result


def run(keys=None, origin: str | None = None, destination: str | None = None, browser_factory=None,
        timeout: float = TIMEOUT) -> list[dict]:
    """Prueba varios proveedores a la vez (cada uno respeta su turno). Los que no acaban: «timeout»."""
    keys = ordered(keys if keys is not None else PROVIDERS)
    if not keys:
        return []
    pool = ThreadPoolExecutor(max_workers=len(keys), thread_name_prefix="salud")
    futures = {k: pool.submit(check_provider, k, origin, destination, browser_factory) for k in keys}
    wait(futures.values(), timeout=timeout)
    pool.shutdown(wait=False)
    out = []
    for k, fut in futures.items():
        if fut.done():
            out.append(fut.result())
            continue
        prov = PROVIDERS[k]
        route = f"{origin or prov.health_route[0]}→{destination or prov.health_route[1]}"
        step = {"name": "Prueba", "status": "timeout", "detail": f"No ha terminado en {int(timeout)} s.",
                "http_status": None, "ms": int(timeout * 1000), "route": route}
        res = {"key": k, "status": "timeout", "route": route, "steps": [step], "latency_ms": int(timeout * 1000),
               "checked_at": _now()}
        with db.connect() as con:
            db.save_health(con, k, "timeout", [step], res["latency_ms"], res["checked_at"])
        out.append(res)
    return out


def check_draft(prov, origin: str, destination: str, timeout: float = TIMEOUT) -> dict:
    """Prueba de un proveedor propio sin guardar (editor de scripts): mismos pasos, sin tocar `provider_health`.

    Devuelve además una muestra de los precios y los mensajes de `api.log` del script.
    """
    found: list = []
    prov.logs = []
    started = time.monotonic()

    def steps():
        out = [_coverage_step(prov, origin, destination)]
        if out[0]["status"] != "blocked":
            out.append(_prices_step(prov, origin, destination, sink=found))
        return out

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="script")
    fut = pool.submit(steps)
    wait([fut], timeout=timeout)
    pool.shutdown(wait=False)
    if fut.done():
        result = fut.result()
    else:
        result = [{"name": "Prueba", "status": "timeout", "detail": f"El script no ha terminado en {int(timeout)} s.",
                   "http_status": None, "ms": int(timeout * 1000)}]
    route = f"{origin}→{destination}"
    return {
        "key": prov.key, "status": worst(result), "route": route, "steps": [{**s, "route": route} for s in result],
        "latency_ms": int((time.monotonic() - started) * 1000), "checked_at": _now(),
        "sample": [{"day": p.day.isoformat(), "price": p.price, "currency": p.currency, "origin": p.origin,
                    "destination": p.destination, "stops": p.stops} for p in sorted(found, key=lambda p: p.day)[:62]],
        "n_prices": len(found), "logs": list(prov.logs),
    }


def check_fx() -> dict:
    def run_fx():
        data = fx.fetch()
        return "ok", f"Tipos del BCE del {data['date']} ({len(data['rates'])} monedas)."
    return _step("Cambio de divisas (BCE)", run_fx)


def fetch_page(url: str) -> requests.Response:
    """Portada de una web con nuestro User-Agent honesto (los tests la sustituyen)."""
    return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, allow_redirects=True)


def check_candidate(key: str, browser_factory=None) -> dict:
    """Portada de una aerolínea en estudio: sin navegador y, si se pide, con Chromium headless."""
    cand = CANDIDATES[key]

    def plain():
        r = fetch_page(cand["url"])
        marks = antibot(dict(r.headers), r.text)
        seen = f" Detectado: {', '.join(marks)}." if marks else ""
        if r.status_code in (403, 429) or (r.status_code == 503 and marks):
            raise ProviderBlocked(f"HTTP {r.status_code}: rechaza a un cliente sin navegador.{seen}", r.status_code)
        if not r.ok:
            raise ProviderError(f"HTTP {r.status_code}.{seen}")
        return "ok", f"HTTP {r.status_code}, {len(r.content) // 1024} KB.{seen}"

    def headless():
        from .checker import browser_page
        with browser_factory() as browser, browser_page(browser) as page:
            resp = page.goto(cand["url"], wait_until="domcontentloaded")
            code = resp.status if resp else None
            title = (page.title() or "")[:80]
            marks = antibot(dict(resp.headers) if resp else {}, page.content())
            seen = f" Detectado: {', '.join(marks)}." if marks else ""
            if code in (403, 429):
                raise ProviderBlocked(f"HTTP {code} a Chromium headless («{title}»).{seen}", code)
            return "ok", f"HTTP {code}, título «{title}».{seen}"

    steps = [_step("Portada sin navegador", plain)]
    if browser_factory is not None:
        steps.append(_step("Portada con Chromium headless", headless))
    status = worst(steps)
    return {"key": key, "label": cand["label"], "url": cand["url"], "notes": cand["notes"], "status": status,
            "steps": steps, "checked_at": _now()}
