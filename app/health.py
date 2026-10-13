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
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime

from . import db, fx
from .providers import PROVIDERS, ProviderBlocked, ProviderError, ProviderTimeout, ordered

#: Segundos sin ninguna señal de vida del proveedor (turno, petición, traza o `api.log`) para dar la prueba por
#: colgada; se le suma su pausa entre peticiones y no cuentan mientras una petición está dentro de su `timeout`. Cubre lo más largo que puede tardar una sola petición sin trazas
#: (abrir la portada en Chrome: hasta 45 s + 15 s). Un proveedor lento que sigue avanzando no se corta.
IDLE_TIMEOUT = 90.0
#: Tope de la prueba completa aunque siga avanzando (un script que no acaba nunca).
MAX_TIME = 600.0
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


class Progress:
    """Lo que lleva hecho una prueba, por si hay que cortarla: los pasos terminados y el que está en curso."""

    def __init__(self):
        self.steps: list[dict] = []
        self.current = "Prueba"
        self.started = time.monotonic()


def _step(name: str, fn, say=None, progress: Progress | None = None) -> dict:
    """Ejecuta un paso y lo clasifica. `fn` devuelve (estado, detalle). `say(nivel, texto)`: consola de la prueba."""
    started = time.monotonic()
    if progress is not None:
        progress.current = name
    http = None
    if say:
        say("step", name)
    try:
        status, detail = fn()
    except ProviderBlocked as exc:
        status, detail, http = "blocked", str(exc), exc.status
    except ProviderError as exc:
        timed_out = isinstance(exc, ProviderTimeout) or "tiempo agotado" in str(exc)  # también fetch() en Chrome
        status, detail = ("timeout" if timed_out else "error"), str(exc)
    except Exception as exc:  # noqa: BLE001 - la prueba informa de cualquier fallo
        status, detail = "error", f"{type(exc).__name__}: {exc}"[:300]
    ms = int((time.monotonic() - started) * 1000)
    if say:
        say(CONSOLE_LEVEL[status], f"{STATUS_LABELS[status]} ({ms / 1000:.1f} s): {detail}")
    step = {"name": name, "status": status, "detail": detail, "http_status": http, "ms": ms}
    if progress is not None:
        progress.steps.append(step)
    return step


def _secs(s: float) -> str:
    return f"{s / 60:g} min" if s >= 120 else f"{int(s)} s"


def _watch(tests: dict, idle_timeout: float, max_time: float) -> dict[str, dict]:
    """Espera a que acaben las pruebas `{clave: (futuro, proveedor o función que lo da, Progress)}`.

    Una prueba solo se corta si su proveedor lleva más de `idle_timeout` (más su pausa entre peticiones) sin dar
    señales de vida, o si pasa de `max_time` en total. Devuelve, de las cortadas, el paso «timeout» con lo que
    estaba haciendo (los pasos terminados siguen en su `Progress`).
    """
    stopped: dict[str, dict] = {}
    pending = dict(tests)
    while pending:
        now = time.monotonic()
        for k, (fut, prov, progress) in list(pending.items()):
            if fut.done():
                del pending[k]
                continue
            prov = prov() if callable(prov) else prov
            last = max(progress.started, getattr(prov, "last_activity", 0.0), getattr(prov, "busy_until", 0.0))
            limit = idle_timeout + (prov.min_interval + prov.jitter if prov is not None else 0)
            elapsed, quiet = now - progress.started, now - last
            if elapsed >= max_time:
                detail = f"No ha terminado en {_secs(max_time)} (tope de la prueba) aunque seguía avanzando."
            elif quiet >= limit:
                detail = f"Sin respuesta ni actividad durante {int(quiet)} s: parece colgado."
            else:
                continue
            stopped[k] = {"name": progress.current, "status": "timeout", "detail": detail,
                          "http_status": None, "ms": int(elapsed * 1000)}
            del pending[k]
        if pending:
            wait([f for f, _, _ in pending.values()], timeout=0.25, return_when=FIRST_COMPLETED)
    return stopped


def _coverage_step(prov, origin, destination, say=None, progress: Progress | None = None) -> dict:
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
    return _step("Cobertura", run, say, progress)


def _prices_step(prov, origin, destination, browser_factory=None, sink: list | None = None, say=None,
                 progress: Progress | None = None) -> dict:
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
    return _step("Precios (1 mes)", run, say, progress)


def check_provider(key: str, origin: str | None = None, destination: str | None = None,
                   browser_factory=None, progress: Progress | None = None) -> dict:
    prov = PROVIDERS[key]
    o, d = origin or prov.health_route[0], destination or prov.health_route[1]
    started = time.monotonic()
    steps = [_coverage_step(prov, o, d, progress=progress)]
    if steps[0]["status"] != "blocked":  # si ya nos bloquea, no insistir
        steps.append(_prices_step(prov, o, d, browser_factory, progress=progress))
    status = worst(steps)
    result = {"key": key, "status": status, "route": f"{o}→{d}", "steps": steps,
              "latency_ms": int((time.monotonic() - started) * 1000), "checked_at": _now()}
    with db.connect() as con:
        db.save_health(con, key, status, [{**s, "route": result["route"]} for s in steps], result["latency_ms"],
                       result["checked_at"])
    return result


def run(keys=None, origin: str | None = None, destination: str | None = None, browser_factory=None,
        idle_timeout: float = IDLE_TIMEOUT, max_time: float = MAX_TIME) -> list[dict]:
    """Prueba varios proveedores a la vez (cada uno respeta su turno). Los colgados: «timeout» (ver `_watch`)."""
    keys = ordered(keys if keys is not None else PROVIDERS)
    if not keys:
        return []
    pool = ThreadPoolExecutor(max_workers=len(keys), thread_name_prefix="salud")
    tests = {}
    for k in keys:
        progress = Progress()
        tests[k] = (pool.submit(check_provider, k, origin, destination, browser_factory, progress), PROVIDERS[k], progress)
    stopped = _watch(tests, idle_timeout, max_time)
    pool.shutdown(wait=False)
    out = []
    for k, (fut, prov, progress) in tests.items():
        if k not in stopped:
            out.append(fut.result())
            continue
        # Sigue en segundo plano: si acaba, su resultado sustituye a este en `provider_health`.
        route = f"{origin or prov.health_route[0]}→{destination or prov.health_route[1]}"
        steps = [{**s, "route": route} for s in [*list(progress.steps), stopped[k]]]
        res = {"key": k, "status": worst(steps), "route": route, "steps": steps, "latency_ms": stopped[k]["ms"],
               "checked_at": _now()}
        with db.connect() as con:
            db.save_health(con, k, res["status"], steps, res["latency_ms"], res["checked_at"])
        out.append(res)
    return out


def check_draft(build, origin: str, destination: str, say=None, idle_timeout: float = IDLE_TIMEOUT,
                max_time: float = MAX_TIME) -> dict:
    """Prueba del script del editor sin guardar nada (ni en `provider_health`): carga, cobertura y precios.

    `build(say)` crea el proveedor (así la carga también cuenta para el tiempo límite y sale en la consola). Solo
    se corta si se queda sin dar señales de vida o pasa del tope (ver `_watch`); entonces el script deja de poder
    hacer peticiones.

    `say(nivel, texto)` recibe la traza de cada paso y de cada petición mientras ocurren. Devuelve además una
    muestra de los precios.
    """
    found: list = []
    started = time.monotonic()
    key = "borrador"
    made: list = []
    progress = Progress()

    def steps():
        nonlocal key

        def load():
            prov = build(say)
            made.append(prov)
            extra = {"network": "network", "probe": "probe"}.get(prov.coverage)
            fns = ["fetch_route" + (" (con max_stops)" if prov.stops_filter else "")] + ([extra] if extra else [])
            return "ok", f"Define {' y '.join(fns)}."
        out = [_step("Carga del script", load, say, progress)]
        if not made:
            return out
        prov = made[0]
        key = prov.key
        out.append(_coverage_step(prov, origin, destination, say, progress))
        if out[-1]["status"] != "blocked":  # si ya nos bloquea, no insistir
            out.append(_prices_step(prov, origin, destination, sink=found, say=say, progress=progress))
        return out

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="script")
    fut = pool.submit(steps)
    stopped = _watch({"script": (fut, lambda: made[0] if made else None, progress)}, idle_timeout, max_time)
    pool.shutdown(wait=False)
    if not stopped:
        result = fut.result()
    else:
        if made:
            made[0].stopped = True
        cut = stopped["script"]
        result = [*list(progress.steps), cut]
        if say:
            say("error", f"{cut['name']}: {cut['detail']}")
    route = f"{origin}→{destination}"
    return {
        "key": key, "status": worst(result), "route": route, "steps": [{**s, "route": route} for s in result],
        "latency_ms": int((time.monotonic() - started) * 1000), "checked_at": _now(),
        "sample": [{"day": p.day.isoformat(), "price": p.price, "currency": p.currency, "origin": p.origin,
                    "destination": p.destination, "stops": p.stops, "departs_at": db.minutes(p.departure),
                    "arrives_at": db.minutes(p.arrival)} for p in sorted(found, key=lambda p: p.day)[:62]],
        "n_prices": len(found),
    }


def check_fx() -> dict:
    def run_fx():
        data = fx.fetch()
        return "ok", f"Tipos del BCE del {data['date']} ({len(data['rates'])} monedas)."
    return _step("Cambio de divisas (BCE)", run_fx)
