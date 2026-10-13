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


def fmt_short_day(value) -> str:
    """«03/11», para los botones."""
    return f"{to_date(value):%d/%m}"


def fmt_clock(departs_at: str | None, arrives_at: str | None = None) -> str:
    """«06:35–08:10», «22:40–00:15 (+1)», «sale 06:35» o "" si no se sabe (ISO «AAAA-MM-DDTHH:MM»)."""
    if not departs_at:
        return f"llega {arrives_at[11:16]}" if arrives_at else ""
    out = departs_at[11:16]
    if not arrives_at:
        return f"sale {out}"
    days = (to_date(arrives_at) - to_date(departs_at)).days
    return f"{out}–{arrives_at[11:16]}" + (f" (+{days})" if days > 0 else "")


def fmt_price(value) -> str:
    if value is None:
        return "—"
    p = float(value)
    if abs(p - round(p)) < 0.005:
        return f"{p:.0f} €"
    return f"{p:.2f}".replace(".", ",") + " €"


def fmt_money(value, currency: str) -> str:
    """Importe en otra moneda: «12.990 HUF», «45,50 GBP»."""
    p = float(value)
    text = f"{p:,.0f}" if abs(p - round(p)) < 0.005 else f"{p:,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".") + f" {currency}"


def fmt_stops(stops) -> str:
    if stops is None:
        return ""
    return "directo" if stops == 0 else f"{stops} escala" + ("s" if stops > 1 else "")


def fmt_nights(n: int) -> str:
    return f"{n} noche" + ("s" if n != 1 else "")


def fmt_nights_range(lo: int, hi: int) -> str:
    """«4 noches» o «3–5 noches»."""
    return fmt_nights(lo) if lo == hi else f"{lo}–{hi} noches"
