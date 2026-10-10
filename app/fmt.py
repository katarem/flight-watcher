"""Formateo de fechas y precios para los avisos (el panel usa el mismo criterio en `frontend/src/lib/format.ts`)."""
from __future__ import annotations

from datetime import date, datetime

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def to_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def fmt_day(value) -> str:
    d = to_date(value)
    return f"{DIAS[d.weekday()]} {d:%d/%m/%Y}"


def fmt_price(value) -> str:
    if value is None:
        return "—"
    p = float(value)
    if abs(p - round(p)) < 0.005:
        return f"{p:.0f} €"
    return f"{p:.2f}".replace(".", ",") + " €"
