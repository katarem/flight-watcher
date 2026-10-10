"""Cambio de divisas a euros con los tipos de referencia diarios del BCE.

Se descargan de `eurofxref-daily.xml` como mucho dos veces al día y se guardan en DATA_DIR para
sobrevivir a los reinicios. Si el BCE no responde se usan los últimos guardados (hasta 10 días).
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timedelta

import requests

from .config import DATA_DIR
from .providers.base import USER_AGENT

log = logging.getLogger("fx")

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
CACHE = DATA_DIR / "ecb_rates.json"
REFRESH = timedelta(hours=12)
MAX_AGE = timedelta(days=10)

_RATE = re.compile(r"currency=['\"]([A-Z]{3})['\"]\s+rate=['\"]([\d.]+)['\"]")
_DATE = re.compile(r"time=['\"](\d{4}-\d{2}-\d{2})['\"]")
_lock = threading.Lock()
_state: dict = {}


class FxError(RuntimeError):
    pass


def parse(xml: str) -> dict:
    rates = {c: float(r) for c, r in _RATE.findall(xml)}
    if not rates:
        raise FxError("El BCE devolvió un archivo sin tipos de cambio")
    m = _DATE.search(xml)
    return {"date": m[1] if m else "", "rates": rates}


def _load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fetch() -> dict:
    """Descarga los tipos del día y los guarda. Lanza FxError si no se puede."""
    try:
        r = requests.get(ECB_URL, headers={"User-Agent": USER_AGENT}, timeout=20)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise FxError(f"No se pudo descargar el cambio del BCE ({type(exc).__name__})") from exc
    data = {**parse(r.text), "fetched_at": datetime.now().isoformat(timespec="seconds")}
    try:
        CACHE.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
    return data


def rates() -> dict:
    """{"date", "rates", "fetched_at"} vigentes (de memoria, del archivo o del BCE)."""
    with _lock:
        data = _state.get("data") or _load_cache()
        fetched = datetime.fromisoformat(data["fetched_at"]) if data.get("fetched_at") else None
        if fetched is None or datetime.now() - fetched > REFRESH:
            try:
                data = fetch()
            except FxError as exc:
                if fetched is None or datetime.now() - fetched > MAX_AGE:
                    raise
                log.warning("%s: uso los tipos guardados del %s", exc, data.get("date"))
        _state["data"] = data
        return data


def to_eur(amount: float, currency: str) -> float:
    currency = (currency or "EUR").upper()
    if currency == "EUR":
        return amount
    rate = rates()["rates"].get(currency)
    if not rate:
        raise FxError(f"El BCE no publica cambio para {currency}")
    return round(amount / rate, 2)
