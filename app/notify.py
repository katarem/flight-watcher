"""Notificaciones por Discord (webhook) y Telegram (bot). Cada aviso incluye enlace por fecha."""
from __future__ import annotations

import html
import logging

import requests

from .fmt import fmt_day, fmt_price
from .providers import PROVIDERS

log = logging.getLogger("notify")

MAX_DEALS_PER_PROVIDER = 8


def _chunks(lines: list[str], limit: int):
    cur: list[str] = []
    size = 0
    for line in lines:
        if cur and size + len(line) + 1 > limit:
            yield "\n".join(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        yield "\n".join(cur)


def channels(settings: dict) -> list[str]:
    out = []
    if settings.get("discord_webhook"):
        out.append("discord")
    if settings.get("telegram_token") and settings.get("telegram_chat_id"):
        out.append("telegram")
    return out


def _post_discord(settings, lines):
    for chunk in _chunks(lines, 1900):
        r = requests.post(settings["discord_webhook"], json={"content": chunk}, timeout=20)
        r.raise_for_status()


def _post_telegram(settings, lines):
    url = f"https://api.telegram.org/bot{settings['telegram_token']}/sendMessage"
    for chunk in _chunks(lines, 3900):
        r = requests.post(
            url,
            json={
                "chat_id": settings["telegram_chat_id"],
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        r.raise_for_status()


def send(settings: dict, discord_lines: list[str], telegram_lines: list[str]) -> tuple[list[str], list[str]]:
    """Devuelve (canales_ok, errores)."""
    ok, errors = [], []
    if "discord" in channels(settings):
        try:
            _post_discord(settings, discord_lines)
            ok.append("discord")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Discord: {type(exc).__name__}")
    if "telegram" in channels(settings):
        try:
            _post_telegram(settings, telegram_lines)
            ok.append("telegram")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Telegram: {type(exc).__name__}")
    return ok, errors


def send_text(settings: dict, text: str) -> tuple[list[str], list[str]]:
    return send(settings, text.split("\n"), [html.escape(t) for t in text.split("\n")])


def send_deals(settings: dict, watch: dict, deals: list[dict], baselines: dict) -> tuple[list[str], list[str]]:
    """Un mensaje por vigilancia, agrupado por proveedor, con un enlace por cada fecha."""
    route = f"{watch['origin']}→{watch['destination']}"
    d_lines = [f"✈️ **{watch['name']}** ({route})"]
    t_lines = [f"✈️ <b>{html.escape(watch['name'])}</b> ({route})"]

    for key in watch["providers"]:
        mine = sorted((d for d in deals if d["provider"] == key), key=lambda d: d["price"])
        if not mine:
            continue
        label = PROVIDERS[key].label
        base = baselines.get(key)
        extra = f" · habitual ≈ {fmt_price(base)}" if base else ""
        d_lines += ["", f"**{label}**{extra}"]
        t_lines += ["", f"<b>{html.escape(label)}</b>{extra}"]
        for d in mine[:MAX_DEALS_PER_PROVIDER]:
            day, price = fmt_day(d["day"]), fmt_price(d["price"])
            if d.get("origin") and (d["origin"], d["destination"]) != (watch["origin"], watch["destination"]):
                day += f" ({d['origin']}→{d['destination']})"
            d_lines.append(f"• [{day} → **{price}**](<{d['link']}>)")
            t_lines.append(
                f'• <a href="{html.escape(d["link"], quote=True)}">{day} → <b>{price}</b></a>'
            )
        if len(mine) > MAX_DEALS_PER_PROVIDER:
            more = f"… y {len(mine) - MAX_DEALS_PER_PROVIDER} fecha(s) más en el panel"
            d_lines.append(more)
            t_lines.append(more)

    panel = (settings.get("panel_url") or "").rstrip("/")
    if panel:
        link = f"{panel}/watches/{watch['id']}"
        d_lines += ["", f"📊 [Historial y gráficas](<{link}>)"]
        t_lines += ["", f'📊 <a href="{html.escape(link, quote=True)}">Historial y gráficas</a>']
    return send(settings, d_lines, t_lines)
