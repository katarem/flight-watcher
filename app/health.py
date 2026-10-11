"""Prueba de acceso a los proveedores (zona «Proveedores» del administrador), como un healthcheck.

Por cada proveedor se hacen, en su turno de peticiones y desde la IP del panel, los mismos pasos que en
una ronda pero sobre una sola ruta: la cobertura (red de rutas o pregunta directa) y los precios de un
mes. Cada paso dice si fue bien, si la web nos bloquea (403/429/anti-bot), si falló o si no respondió a
tiempo. El resultado se guarda en `provider_health`. También se prueba el cambio de divisas del BCE.

La prueba del editor (`check_draft`) hace lo mismo con el script del formulario, sin guardar nada, y cuenta cada
paso en la consola que ve el administrador mientras se ejecuta.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime

from . import db, fx
from .providers import PROVIDERS, ProviderBlocked, ProviderError, ordered

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


#: Nivel de la consola con el que se cuenta el final de cada paso.
CONSOLE_LEVEL = {"ok": "ok", "skipped": "info", "empty": "warn", "error": "error", "timeout": "error", "blocked": "error"}


def _step(name: str, fn, say=None) -> dict:
    """Ejecuta un paso y lo clasifica. `fn` devuelve (estado, detalle). `say(nivel, texto)`: consola de la prueba."""
    started = time.monotonic()
    http = None
    if say:
        say("step", name)
    try:
        status, detail = fn()
    except ProviderBlocked as exc:
        status, detail, http = "blocked", str(exc), exc.status
    except ProviderError as exc:
        status, detail = ("timeout" if "tiempo agotado" in str(exc) else "error"), str(exc)
    except Exception as exc:  # noqa: BLE001 - la prueba informa de cualquier fallo
        status, detail = "error", f"{type(exc).__name__}: {exc}"[:300]
    ms = int((time.monotonic() - started) * 1000)
    if say:
        say(CONSOLE_LEVEL[status], f"{STATUS_LABELS[status]} ({ms / 1000:.1f} s): {detail}")
    return {"name": name, "status": status, "detail": detail, "http_status": http, "ms": ms}


def _coverage_step(prov, origin, destination, say=None) -> dict:
    def run():
        with prov.new_session() as s:
            if say and prov.coverage != "universal":
                call = f"network(api, {origin!r})" if prov.coverage == "network" else f"probe(api, {origin!r}, {destination!r})"
                say("info", f"Llamo a {call}")
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
    return _step("Cobertura", run, say)


def _prices_step(prov, origin, destination, browser_factory=None, sink: list | None = None, say=None) -> dict:
    """Precios de un mes. Si se pasa `sink`, deja ahí los precios encontrados."""
    def run():
        kw = {"max_stops": 0} if prov.stops_filter else {}
        if say:
            say("info", f"Llamo a fetch_route(api, {origin!r}, {destination!r}, {date.today().isoformat()}, 1"
                + (", max_stops=0)" if kw else ")"))
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
    return _step("Precios (1 mes)", run, say)


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


def check_draft(build, origin: str, destination: str, say=None, timeout: float = TIMEOUT) -> dict:
    """Prueba del script del editor sin guardar nada (ni en `provider_health`): carga, cobertura y precios.

    `build(say)` crea el proveedor (así la carga también cuenta para el tiempo límite y sale en la consola).
    `say(nivel, texto)` recibe la traza de cada paso y de cada petición mientras ocurren. Devuelve además una
    muestra de los precios.
    """
    found: list = []
    started = time.monotonic()
    key = "borrador"

    def steps():
        nonlocal key
        made = []

        def load():
            prov = build(say)
            made.append(prov)
            extra = {"network": "network", "probe": "probe"}.get(prov.coverage)
            fns = ["fetch_route" + (" (con max_stops)" if prov.stops_filter else "")] + ([extra] if extra else [])
            return "ok", f"Define {' y '.join(fns)}."
        out = [_step("Carga del script", load, say)]
        if not made:
            return out
        prov = made[0]
        key = prov.key
        out.append(_coverage_step(prov, origin, destination, say))
        if out[-1]["status"] != "blocked":  # si ya nos bloquea, no insistir
            out.append(_prices_step(prov, origin, destination, sink=found, say=say))
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
        if say:
            say("error", result[0]["detail"])
    route = f"{origin}→{destination}"
    return {
        "key": key, "status": worst(result), "route": route, "steps": [{**s, "route": route} for s in result],
        "latency_ms": int((time.monotonic() - started) * 1000), "checked_at": _now(),
        "sample": [{"day": p.day.isoformat(), "price": p.price, "currency": p.currency, "origin": p.origin,
                    "destination": p.destination, "stops": p.stops} for p in sorted(found, key=lambda p: p.day)[:62]],
        "n_prices": len(found),
    }


def check_fx() -> dict:
    def run_fx():
        data = fx.fetch()
        return "ok", f"Tipos del BCE del {data['date']} ({len(data['rates'])} monedas)."
    return _step("Cambio de divisas (BCE)", run_fx)
