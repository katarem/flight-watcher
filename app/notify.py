"""Notificaciones por Discord (webhook) y Telegram (bot). Cada aviso incluye enlace por fecha (y por tramo en los viajes)."""
from __future__ import annotations

import html
import logging
import re

import requests

from .fmt import fmt_day, fmt_money, fmt_nights, fmt_nights_range, fmt_price, fmt_stops
from .providers import PROVIDERS, ordered

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


# ---------------------------------------------------------------- tipos de canal
# Un canal es una fila de `channels` (kind + config en JSON). Para añadir un tipo nuevo basta una entrada
# en KINDS: campos del formulario, validación y función de envío (recibe la config y las líneas del mensaje).
_WEBHOOK = re.compile(r"^https://(?:[\w-]+\.)?discord(?:app)?\.com/api/webhooks/")
_TG_TOKEN = re.compile(r"^\d{5,}:[\w-]{20,}$")
_TG_CHAT = re.compile(r"^-?\d{1,20}$|^@[A-Za-z0-9_]{4,}$")


def _post_discord(config: dict, lines: list[str]):
    for chunk in _chunks(lines, 1900):
        r = requests.post(config["webhook"], json={"content": chunk}, timeout=20)
        r.raise_for_status()


def _post_telegram(config: dict, lines: list[str]):
    url = f"https://api.telegram.org/bot{config['token']}/sendMessage"
    for chunk in _chunks(lines, 3900):
        r = requests.post(
            url,
            json={"chat_id": config["chat_id"], "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=20,
        )
        r.raise_for_status()


# fields: (clave, etiqueta, secreto, ejemplo, validador, mensaje de error). Los secretos no vuelven al navegador.
KINDS = {
    "discord": {
        "label": "Discord", "markup": "markdown", "send": _post_discord,
        "fields": [("webhook", "Webhook de Discord", True, "https://discord.com/api/webhooks/…",
                    lambda v: bool(_WEBHOOK.match(v)) and len(v) <= 500, "La URL del webhook de Discord no es válida.")],
    },
    "telegram": {
        "label": "Telegram", "markup": "html", "send": _post_telegram,
        "fields": [
            ("token", "Token del bot de Telegram", True, "123456:ABC…",
             lambda v: bool(_TG_TOKEN.match(v)) and len(v) <= 200, "El token del bot de Telegram no tiene un formato válido (123456:ABC…)."),
            ("chat_id", "Chat ID de Telegram", False, "123456789",
             lambda v: bool(_TG_CHAT.match(v)), "El chat ID de Telegram debe ser un número (o @canal)."),
        ],
    },
}


def validate_config(kind: str, form: dict, current: dict | None = None) -> tuple[dict, list[str]]:
    """Config lista para guardar a partir del formulario. Un secreto vacío conserva el valor actual."""
    config, errors = {}, []
    for key, _label, secret, _ph, ok, msg in KINDS[kind]["fields"]:
        value = (form.get(key) or "").strip()
        if not value and secret and current and current.get(key):
            value = current[key]
        if not ok(value):
            errors.append(msg)
        config[key] = value
    return config, errors


def view_fields(kind: str, config: dict | None) -> list[dict]:
    """Campos para la plantilla: los secretos se enmascaran (solo se indica si hay uno guardado)."""
    config = config or {}
    return [{"key": key, "label": label, "secret": secret, "placeholder": ph,
             "value": "" if secret else config.get(key, ""), "saved": bool(secret and config.get(key))}
            for key, label, secret, ph, _ok, _msg in KINDS[kind]["fields"]]


def send(channels: list[dict], lines: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    """Envía a cada canal el mensaje en su formato (`lines` por `markup`). Devuelve (nombres_ok, errores)."""
    ok, errors = [], []
    for ch in channels:
        kind = KINDS.get(ch["kind"])
        if not kind:
            continue
        try:
            kind["send"](ch["config"], lines[kind["markup"]])
            ok.append(ch["name"])
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{ch['name']}: {type(exc).__name__}")
    return ok, errors


def send_text(channels: list[dict], text: str) -> tuple[list[str], list[str]]:
    return send(channels, {"markdown": text.split("\n"), "html": [html.escape(t) for t in text.split("\n")]})


def send_deals(channels: list[dict], watch: dict, deals: list[dict], baselines: dict,
               panel_url: str = "") -> tuple[list[str], list[str]]:
    """Un mensaje por vigilancia, agrupado por proveedor, con un enlace por cada fecha."""
    route = f"{watch['origin']}→{watch['destination']}"
    d_lines = [f"✈️ **{watch['name']}** ({route})"]
    t_lines = [f"✈️ <b>{html.escape(watch['name'])}</b> ({route})"]

    for key in ordered(watch["providers"]):
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
            if d.get("orig_price") and d.get("currency", "EUR") != "EUR":
                price += f" ({fmt_money(d['orig_price'], d['currency'])})"
            if d.get("stops"):
                price += f" · {fmt_stops(d['stops'])}"
            d_lines.append(f"• [{day} → **{price}**](<{d['link']}>)")
            t_lines.append(
                f'• <a href="{html.escape(d["link"], quote=True)}">{day} → <b>{price}</b></a>'
            )
        if len(mine) > MAX_DEALS_PER_PROVIDER:
            more = f"… y {len(mine) - MAX_DEALS_PER_PROVIDER} fecha(s) más en el panel"
            d_lines.append(more)
            t_lines.append(more)

    panel = (panel_url or "").rstrip("/")
    if panel:
        link = f"{panel}/watches/{watch['id']}"
        d_lines += ["", f"📊 [Historial y gráficas](<{link}>)"]
        t_lines += ["", f'📊 <a href="{html.escape(link, quote=True)}">Historial y gráficas</a>']
    return send(channels, {"markdown": d_lines, "html": t_lines})


def _leg_text(leg: dict) -> str:
    """«Vueling 40 €», con el par de aeropuertos real si difiere de la vigilancia («Ryanair 55 € (TFS→SVQ)»)."""
    prov = PROVIDERS.get(leg["provider"])
    text = f"{prov.label if prov else leg['provider']} {fmt_price(leg['price'])}"
    return text + (f" ({leg['route']})" if leg.get("route") else "")


def send_trip_deals(channels: list[dict], trip: dict, outbound: dict, ret: dict, deals: list[dict], base: float | None,
                    panel_url: str = "") -> tuple[list[str], list[str]]:
    """Un mensaje por viaje: cada combinación con su total, sus fechas y un enlace por tramo."""
    route = f"{outbound['origin']}⇄{outbound['destination']}"
    head = f"({route} · {fmt_nights_range(trip['min_nights'], trip['max_nights'])})"
    extra = f" · habitual ≈ {fmt_price(base)}" if base else ""
    d_lines = [f"🧳 **{trip['name']}** {head}{extra}"]
    t_lines = [f"🧳 <b>{html.escape(trip['name'])}</b> {head}{extra}"]
    for q in sorted(deals, key=lambda q: q["total"]):
        when = f"{fmt_day(q['out_date'])} → {fmt_day(q['ret_date'])} · {fmt_nights(q['nights'])}"
        total = fmt_price(q["total"])
        o, r = q["out"], q["ret"]
        d_lines += [f"• {when}: **{total}**",
                    f"  ida [{_leg_text(o)}](<{o['link']}>) · vuelta [{_leg_text(r)}](<{r['link']}>)"]
        t_lines += [f"• {when}: <b>{total}</b>",
                    f'  ida <a href="{html.escape(o["link"], quote=True)}">{html.escape(_leg_text(o))}</a> · '
                    f'vuelta <a href="{html.escape(r["link"], quote=True)}">{html.escape(_leg_text(r))}</a>']

    panel = (panel_url or "").rstrip("/")
    if panel:
        link = f"{panel}/trips/{trip['id']}"
        d_lines += ["", f"📊 [Todas las combinaciones](<{link}>)"]
        t_lines += ["", f'📊 <a href="{html.escape(link, quote=True)}">Todas las combinaciones</a>']
    return send(channels, {"markdown": d_lines, "html": t_lines})
