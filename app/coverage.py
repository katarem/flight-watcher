"""Cobertura de rutas: qué pares de aeropuertos opera cada proveedor.

Tres formas, declaradas por cada proveedor (`Provider.coverage`):
- «network»: publica su red de rutas; se descarga por aeropuerto de origen (en memoria 1 h).
- «probe»: se le pregunta por cada par (Vueling: un 404 es que no la opera).
- «universal»: cubre cualquier ruta (Google Flights), con un máximo de pares (`max_routes`).

Las respuestas se guardan en `provider_routes`. Al crear una vigilancia, `check_many` consulta los
proveedores en paralelo con un tiempo límite por proveedor; cada semana `revalidate` repasa las
vigilancias y avisa si una ruta (de temporada, normalmente) se abre o se cierra.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import db, notify, places
from .providers import PROVIDERS, ProviderBlocked, ProviderError, ordered

log = logging.getLogger("coverage")

#: Validez de lo guardado en provider_routes al comprobar una ruta desde el formulario.
CACHE_DAYS = 3
#: Tiempo máximo por proveedor al comprobar una ruta desde el formulario.
CHECK_TIMEOUT = 25.0
NETWORK_TTL = 3600

_networks: dict[tuple[str, str], tuple[float, set[str]]] = {}
_networks_lock = threading.Lock()
_revalidate_lock = threading.Lock()


@dataclass
class Result:
    """Cobertura de un proveedor para unos pares de aeropuertos."""
    key: str
    status: str  # ok | none | error | timeout | too_many
    routes: list[tuple[str, str]] = field(default_factory=list)
    reason: str = ""
    elapsed_ms: int = 0

    @property
    def definitive(self) -> bool:
        """True si se sabe la respuesta (opera o no); False si no se pudo comprobar."""
        return self.status in ("ok", "none", "too_many")

    def view(self) -> dict:
        prov = PROVIDERS[self.key]
        return {"key": self.key, "label": prov.label, "color": prov.color, "coverage": prov.coverage,
                "status": self.status, "ok": self.status == "ok", "routes": [db.pair_key(p) for p in self.routes],
                "reason": self.reason, "elapsed_ms": self.elapsed_ms}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _routes_text(pairs) -> str:
    pairs = list(pairs)
    shown = ", ".join(f"{o}→{d}" for o, d in pairs[:4])
    return shown + (f" y {len(pairs) - 4} más" if len(pairs) > 4 else "")


def _network(prov, session, origin: str, fresh: bool = False) -> set[str]:
    with _networks_lock:
        hit = _networks.get((prov.key, origin))
        if hit and not fresh and time.monotonic() - hit[0] < NETWORK_TTL:
            return hit[1]
    dests = prov.network(session, origin)
    with _networks_lock:
        _networks[(prov.key, origin)] = (time.monotonic(), dests)
    return dests


def forget(key: str):
    """Olvida la cobertura guardada de un proveedor (en BD y en memoria): al cambiar el script de uno propio."""
    with _networks_lock:
        for k in [k for k in _networks if k[0] == key]:
            del _networks[k]
    with db.connect() as con:
        db.forget_routes(con, key)


def check(key: str, pairs: list[tuple[str, str]], max_age_days: float | None = CACHE_DAYS) -> Result:
    """Qué pares opera el proveedor. `max_age_days=None` ignora la caché (revalidación semanal)."""
    started = time.monotonic()
    prov = PROVIDERS[key]
    res = _check(prov, pairs, max_age_days)
    res.elapsed_ms = int((time.monotonic() - started) * 1000)
    return res


def _check(prov, pairs, max_age_days) -> Result:
    if not pairs:
        return Result(prov.key, "none", reason="Origen y destino son el mismo aeropuerto.")
    limit = prov.max_routes or places.MAX_PAIRS
    if prov.coverage == "universal":
        if len(pairs) > limit:
            return Result(prov.key, "too_many", reason=f"{prov.label} admite como mucho {limit} pares de "
                          f"aeropuertos por vigilancia y esta ruta tiene {len(pairs)}: acota el origen o el destino.")
        return Result(prov.key, "ok", list(pairs), f"Busca en cualquier ruta: {_routes_text(pairs)}.")

    known: dict[tuple[str, str], bool] = {}
    if max_age_days is not None:
        since = (datetime.now() - timedelta(days=max_age_days)).isoformat(timespec="seconds")
        with db.connect() as con:
            known = db.cached_routes(con, prov.key, pairs, since)
    missing = [p for p in pairs if p not in known]
    found: dict[tuple[str, str], bool] = {}
    errors: list[str] = []
    blocked = False
    if missing:
        with prov.new_session() as session:
            if prov.coverage == "network":
                for origin in dict.fromkeys(o for o, _d in missing):
                    try:
                        dests = _network(prov, session, origin, fresh=max_age_days is None)
                    except ProviderError as exc:
                        blocked |= isinstance(exc, ProviderBlocked)
                        errors.append(str(exc))
                        continue
                    found.update({(o, d): d in dests for o, d in missing if o == origin})
            else:
                for o, d in missing:
                    try:
                        found[(o, d)] = bool(prov.probe(session, o, d))
                    except ProviderError as exc:
                        blocked |= isinstance(exc, ProviderBlocked)
                        errors.append(f"{o}→{d}: {exc}")
                        if blocked:  # si nos bloquea, no insistir con el resto de pares
                            break
        with db.connect() as con:
            db.save_routes(con, prov.key, found, _now())

    known.update(found)
    operated = [p for p in pairs if known.get(p)]
    unknown = [p for p in pairs if p not in known]
    if operated:
        reason = f"Opera {_routes_text(operated)}."
        if unknown:
            reason += f" No se pudo comprobar {_routes_text(unknown)}."
        return Result(prov.key, "ok", operated, reason)
    if unknown:
        detail = errors[0] if errors else "sin respuesta"
        return Result(prov.key, "error", [], f"No se ha podido comprobar: {detail}")
    if prov.coverage == "network":
        return Result(prov.key, "none", [], f"{prov.label} no tiene vuelos directos en esta ruta según su red de rutas.")
    return Result(prov.key, "none", [], f"{prov.label} no opera esta ruta.")


def check_many(keys, pairs, timeout: float = CHECK_TIMEOUT, max_age_days: float | None = CACHE_DAYS) -> list[Result]:
    """Comprueba varios proveedores en paralelo (cada uno con su turno de peticiones).

    El que no termina a tiempo sale como «timeout»; sigue en segundo plano y deja su respuesta en la caché.
    """
    keys = ordered(keys)
    if not keys:
        return []
    pool = ThreadPoolExecutor(max_workers=len(keys), thread_name_prefix="cobertura")
    futures = {k: pool.submit(check, k, pairs, max_age_days) for k in keys}
    wait(futures.values(), timeout=timeout)
    pool.shutdown(wait=False)
    out = []
    for k, fut in futures.items():
        if not fut.done():
            out.append(Result(k, "timeout", reason=f"{PROVIDERS[k].label} no ha respondido en {int(timeout)} s. "
                              "Vuelve a comprobarlo en un momento."))
            continue
        try:
            out.append(fut.result())
        except Exception as exc:  # noqa: BLE001 - un proveedor roto no tumba la comprobación
            out.append(Result(k, "error", reason=f"No se ha podido comprobar: {type(exc).__name__}: {exc}"[:300]))
    return out


def coverage_for(keys, origin: str, destination: str, current: dict | None = None,
                 timeout: float = CHECK_TIMEOUT) -> tuple[dict[str, dict], list[str]]:
    """Cobertura para guardar una vigilancia y errores de validación.

    Un proveedor que seguro no opera la ruta es un error, salvo que la vigilancia ya lo tuviera (ruta
    de temporada cerrada: se guarda inactivo). Si no se pudo comprobar, se guarda con todos los pares
    sin comprobar (la revalidación semanal lo pondrá al día).
    """
    current = current or {}
    pairs = places.routes(origin, destination)
    coverage, errors = {}, []
    now = _now()
    for res in check_many(keys, pairs, timeout):
        label = PROVIDERS[res.key].label
        if res.status == "ok":
            coverage[res.key] = {"routes": res.routes, "active": True, "checked_at": now}
        elif res.status in ("none", "too_many") and res.key in current:
            coverage[res.key] = {"routes": [], "active": False, "checked_at": now}
        elif res.status == "none":
            errors.append(f"{label} no opera esta ruta: quítalo o cambia el origen o el destino.")
        elif res.status == "too_many":
            errors.append(res.reason)
        else:
            coverage[res.key] = {"routes": pairs, "active": True, "checked_at": None}
    return coverage, errors


# -------------------------------------------------------------- revalidación semanal
def revalidate(trigger: str = "cron") -> dict:
    """Repasa la cobertura de todas las vigilancias activas y avisa de las rutas que se abren o cierran."""
    if not _revalidate_lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        with db.connect() as con:
            users = {u["id"]: u for u in db.list_users(con)}
            watches = [w for w in db.list_watches(con)
                       if w["enabled"] and users.get(w["user_id"], {}).get("enabled")]
        pairs_cache: dict[tuple[str, str, str], Result] = {}
        changes = 0
        for w in watches:
            pairs = places.routes(w["origin"], w["destination"])
            lines = []
            for key, cov in w["coverage"].items():
                if key not in PROVIDERS:
                    continue
                cache_key = (key, w["origin"], w["destination"])
                if cache_key not in pairs_cache:  # la ida y la vuelta de otro usuario no se repiten
                    pairs_cache[cache_key] = check(key, pairs, max_age_days=None if trigger == "cron" else 0.5)
                res = pairs_cache[cache_key]
                if not res.definitive:
                    log.warning("Cobertura de «%s» · %s sin comprobar: %s", w["name"], key, res.reason)
                    continue
                new = set(res.routes) if res.status == "ok" else set()
                old = set(cov["routes"]) if cov["active"] else set()
                with db.connect() as con:
                    db.update_watch_provider(con, w["id"], key, sorted(new), bool(new), _now())
                if cov["checked_at"] is None:  # primera comprobación (vigilancias anteriores): sin avisos
                    continue
                label = PROVIDERS[key].label
                lines += [f"• {label}: se abre {o}→{d}" for o, d in sorted(new - old)]
                lines += [f"• {label}: deja de operar {o}→{d}" for o, d in sorted(old - new)]
            if lines:
                changes += 1
                with db.connect() as con:
                    chans = [c for c in db.list_channels(con, w["user_id"], only_enabled=True)
                             if c["id"] in w["channel_ids"]]
                if chans:
                    notify.send_text(chans, f"🗓️ Flight Watcher · {w['name']}: cambios en las rutas\n" + "\n".join(lines))
        return {"status": "done", "watches": len(watches), "changed": changes}
    finally:
        _revalidate_lock.release()
