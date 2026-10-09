"""Formateadores compartidos por plantillas y notificaciones."""
from __future__ import annotations

from datetime import date, datetime

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


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


def fmt_price_short(value) -> str:
    """Precio redondeado al euro, para huecos estrechos (calendario)."""
    return "—" if value is None else f"{round(float(value))} €"


def fmt_dt(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime("%d/%m/%Y %H:%M")
