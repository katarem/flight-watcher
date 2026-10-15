"""Avisos por Discord (webhook) y Telegram (bot).

Cada aviso se arma primero como un **mensaje estructurado** (`Message`: título, secciones con un elemento por fecha y
su enlace directo, enlaces generales e imagen) y cada tipo de canal lo pinta a su manera:

- **Discord**: `embeds` (uno de cabecera y uno por sección, con su color), un campo por fecha con el enlace y el
  calendario resumen como imagen adjunta.
- **Telegram**: texto en HTML con botones de enlace (inline keyboard) en lugar de enlaces en el texto, y el
  calendario como foto.

Para añadir un tipo de canal basta una entrada en `KINDS`: campos del formulario, validación y función de envío
(recibe la config y el `Message`).
"""
from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

import requests

from . import images
from .fmt import fmt_clock, fmt_day, fmt_nights, fmt_nights_range, fmt_price, fmt_short_day
from .providers import PROVIDERS

log = logging.getLogger("notify")

#: Color de los avisos que no son de un proveedor (el acento del panel) y de los de problemas.
ACCENT, WARN, DEAL = "#3b5bdb", "#8f5207", "#036b48"
IMAGE_NAME = "calendario.png"


# --------------------------------------------------------------- mensaje estructurado
@dataclass
class Item:
    """Una línea del aviso (una fecha): título, precio destacado, detalles y enlaces directos."""
    title: str               # «lun 03/11/2026»
    price: str = ""          # «30 €» (en negrita)
    detail: str = ""         # «directo · 06:35–08:10»
    #: Enlaces directos: (texto, url). El primero es el de la fecha; un viaje lleva uno por tramo.
    links: list[tuple[str, str]] = field(default_factory=list)
    #: Texto corto de los botones de Telegram (uno por enlace), p. ej. «03/11 · 30 €».
    buttons: list[str] = field(default_factory=list)


@dataclass
class Section:
    """Un bloque del aviso (un proveedor, o las combinaciones de un viaje), con su color."""
    title: str
    color: str = ACCENT
    note: str = ""           # «habitual ≈ 52 €»
    items: list[Item] = field(default_factory=list)
    more: str = ""           # «… y 3 fechas más en el panel»


@dataclass
class Message:
    title: str
    url: str = ""            # enlace del título (el panel)
    color: str = ACCENT
    summary: str = ""        # una línea bajo el título
    lines: list[str] = field(default_factory=list)  # texto libre (avisos de problemas, cambios de rutas…)
    sections: list[Section] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)  # enlaces generales: (texto, url)
    image: bytes | None = None
    footer: str = "Trip Watch"

    def text(self) -> str:
        """Todo el mensaje en texto plano (para los registros y los tests)."""
        out = [self.title, self.summary, *self.lines]
        for s in self.sections:
            out.append(f"{s.title} {s.note}".strip())
            for it in s.items:
                out.append(" ".join(p for p in (it.title, it.price, it.detail) if p)
                           + "".join(f" [{t}]({u})" for t, u in it.links))
            out.append(s.more)
        out += [f"[{t}]({u})" for t, u in self.links]
        return "\n".join(p for p in out if p)


# ------------------------------------------------------------------------- Discord
#: Límites de Discord: 10 embeds y 6000 caracteres por mensaje, 25 campos por embed, 256 en un título o en el nombre
#: de un campo, 1024 en su valor y 4096 en la descripción.
D_EMBEDS, D_CHARS, D_FIELDS, D_NAME, D_VALUE, D_DESC = 10, 5800, 25, 256, 1024, 4000


def _color(hex_color: str) -> int:
    try:
        return int(hex_color.lstrip("#")[:6], 16)
    except ValueError:
        return int(ACCENT[1:], 16)


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _md(text: str) -> str:
    """Escapa lo que Discord interpretaría como formato en un texto nuestro (nombres de vigilancias…)."""
    return re.sub(r"([\\*_~`|>\[\]])", r"\\\1", text)


def _embed_size(e: dict) -> int:
    return (len(e.get("title", "")) + len(e.get("description", "")) + len(e.get("footer", {}).get("text", ""))
            + sum(len(f["name"]) + len(f["value"]) for f in e.get("fields", [])))


def discord_payloads(msg: Message) -> list[dict]:
    """Mensajes del webhook (normalmente uno): embeds respetando los límites de Discord. La imagen, si la hay, va en
    el primer embed como `attachment://calendario.png`."""
    head = {"title": _cut(msg.title, D_NAME), "color": _color(msg.color)}
    if msg.url:
        head["url"] = msg.url
    desc = "\n".join(p for p in (msg.summary, *msg.lines) if p)
    if msg.links:
        desc += ("\n\n" if desc else "") + " · ".join(f"[{_md(t)}]({u})" for t, u in msg.links)
    if desc:
        head["description"] = _cut(desc, D_DESC)
    if msg.image:
        head["image"] = {"url": f"attachment://{IMAGE_NAME}"}
    embeds = [head]
    for s in msg.sections:
        fields = []
        for it in s.items:
            if len(it.links) == 1:  # el precio lleva a la fecha en la web
                main, rest = f"[**{it.price or it.title}**]({it.links[0][1]})", ""
            else:  # un viaje: el total y un enlace por tramo
                main = f"**{it.price}**" if it.price else ""
                rest = " · ".join(f"[{_md(t)}]({u})" for t, u in it.links)
            value = " · ".join(p for p in (main, _md(it.detail) if it.detail else "", rest) if p) or "—"
            fields.append({"name": _cut(it.title, D_NAME), "value": _cut(value, D_VALUE), "inline": len(value) < 60})
        for i in range(0, max(len(fields), 1), D_FIELDS):
            e = {"title": _cut(f"{s.title} · {s.note}" if s.note else s.title, D_NAME), "color": _color(s.color),
                 "fields": fields[i:i + D_FIELDS]}
            if s.more and i + D_FIELDS >= len(fields):
                e["description"] = s.more
            embeds.append(e)
    embeds[-1]["footer"] = {"text": msg.footer}
    out, cur, size = [], [], 0
    for e in embeds:
        n = _embed_size(e)
        if cur and (len(cur) == D_EMBEDS or size + n > D_CHARS):
            out.append({"embeds": cur})
            cur, size = [], 0
        cur.append(e)
        size += n
    out.append({"embeds": cur})
    return out


def _post_discord(config: dict, msg: Message):
    for i, payload in enumerate(discord_payloads(msg)):
        if i == 0 and msg.image:
            r = requests.post(config["webhook"], data={"payload_json": json.dumps(payload)},
                              files={"files[0]": (IMAGE_NAME, msg.image, "image/png")}, timeout=30)
        else:
            r = requests.post(config["webhook"], json=payload, timeout=20)
        r.raise_for_status()


# ------------------------------------------------------------------------ Telegram
#: Límites de Telegram: 4096 caracteres por mensaje, 1024 en el pie de una foto; los botones, como mucho 100.
T_TEXT, T_CAPTION, T_BUTTONS = 3900, 1000, 90


def _valid_button_url(url: str) -> bool:
    """Telegram rechaza el mensaje entero si un botón lleva una URL que no admite (localhost, sin dominio…)."""
    m = re.match(r"^https?://([^/:?#]+)", url or "")
    return bool(m) and "." in m[1] and m[1] not in ("localhost",) and not m[1].endswith(".local")


def telegram_parts(msg: Message, buttons: bool = True) -> tuple[list[str], list[list[dict]]]:
    """(textos en HTML, teclado). Con `buttons=False` los enlaces van en el texto (si Telegram rechaza un botón)."""
    e = html.escape
    title = f'<a href="{e(msg.url, quote=True)}">{e(msg.title)}</a>' if msg.url and not buttons else e(msg.title)
    lines = [f"<b>{title}</b>"]
    lines += [e(p) for p in (msg.summary, *msg.lines) if p]
    keyboard: list[list[dict]] = []
    for s in msg.sections:
        lines += ["", f"<b>{e(s.title)}</b>" + (f" · {e(s.note)}" if s.note else "")]
        for it in s.items:
            price = f" — <b>{e(it.price)}</b>" if it.price else ""
            detail = f" · {e(it.detail)}" if it.detail else ""
            if buttons:
                lines.append(f"• {e(it.title)}{price}{detail}")
                row = [{"text": _cut(label, 60), "url": url} for (_t, url), label
                       in zip(it.links, it.buttons or [t for t, _u in it.links]) if _valid_button_url(url)]
                if row:
                    keyboard.append(row)
            else:
                links = " · ".join(f'<a href="{e(u, quote=True)}">{e(t)}</a>' for t, u in it.links)
                lines.append(f"• {e(it.title)}{price}{detail}" + (f" · {links}" if links else ""))
        if s.more:
            lines.append(e(s.more))
    general = [(t, u) for t, u in ([("📊 Abrir en el panel", msg.url)] if msg.url else []) + msg.links]
    if buttons:
        row = [{"text": t, "url": u} for t, u in general if _valid_button_url(u)]
        if row:
            keyboard.append(row)
    elif msg.links:
        lines += [""] + [f'<a href="{e(u, quote=True)}">{e(t)}</a>' for t, u in msg.links]
    # Si hay más botones de los que admite, se quedan los primeros (las fechas más baratas) y el del panel.
    if sum(len(r) for r in keyboard) > T_BUTTONS:
        keyboard = keyboard[: T_BUTTONS // 2 - 1] + keyboard[-1:]
    return list(_chunks(lines, T_TEXT)), keyboard


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


def _tg(config: dict, method: str, data: dict, files: dict | None = None):
    url = f"https://api.telegram.org/bot{config['token']}/{method}"
    if files:
        return requests.post(url, data=data, files=files, timeout=30)
    return requests.post(url, json=data, timeout=20)


def _post_telegram(config: dict, msg: Message, buttons: bool = True):
    texts, keyboard = telegram_parts(msg, buttons)
    markup = {"reply_markup": {"inline_keyboard": keyboard}} if keyboard else {}
    chat = {"chat_id": config["chat_id"], "parse_mode": "HTML"}

    def check(r, sent_photo: bool) -> bool:
        """True si hay que repetir sin botones: algún enlace no le vale como botón (p. ej. el del panel en la red
        local). Se repite lo que falta, con los enlaces en el texto."""
        if r.status_code == 400 and buttons and "button" in (r.text or "").lower():
            log.warning("Telegram no admite algún botón (%s); se envía con los enlaces en el texto", r.text[:200])
            _post_telegram(config, replace(msg, image=None) if sent_photo else msg, buttons=False)
            return True
        r.raise_for_status()
        return False

    if msg.image:
        # La foto con el texto de pie (y los botones) si cabe; si no, con el título y el texto aparte.
        alone = len(texts) == 1 and len(texts[0]) <= T_CAPTION
        data = {**chat, "caption": texts[0] if alone else f"<b>{html.escape(msg.title)}</b>"}
        if alone and markup:
            data["reply_markup"] = json.dumps(markup["reply_markup"])
        if check(_tg(config, "sendPhoto", data, {"photo": (IMAGE_NAME, msg.image, "image/png")}), False) or alone:
            return
    for i, text in enumerate(texts):
        last = i == len(texts) - 1
        data = {**chat, "text": text, "disable_web_page_preview": True, **(markup if last else {})}
        r = _tg(config, "sendMessage", data)
        if check(r, bool(msg.image)):
            return


# ---------------------------------------------------------------- tipos de canal
# Un canal es una fila de `channels` (kind + config en JSON). Para añadir un tipo nuevo basta una entrada
# en KINDS: campos del formulario, validación y función de envío (recibe la config y el `Message`).
_WEBHOOK = re.compile(r"^https://(?:[\w-]+\.)?discord(?:app)?\.com/api/webhooks/")
_TG_TOKEN = re.compile(r"^\d{5,}:[\w-]{20,}$")
_TG_CHAT = re.compile(r"^-?\d{1,20}$|^@[A-Za-z0-9_]{4,}$")

# fields: (clave, etiqueta, secreto, ejemplo, validador, mensaje de error). Los secretos no vuelven al navegador.
KINDS = {
    "discord": {
        "label": "Discord", "send": _post_discord,
        "fields": [("webhook", "Webhook de Discord", True, "https://discord.com/api/webhooks/…",
                    lambda v: bool(_WEBHOOK.match(v)) and len(v) <= 500, "La URL del webhook de Discord no es válida.")],
    },
    "telegram": {
        "label": "Telegram", "send": _post_telegram,
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


def send(channels: list[dict], msg: Message) -> tuple[list[str], list[str]]:
    """Envía el mensaje a cada canal en su formato. Devuelve (nombres_ok, errores)."""
    ok, errors = [], []
    for ch in channels:
        kind = KINDS.get(ch["kind"])
        if not kind:
            continue
        try:
            kind["send"](ch["config"], msg)
            ok.append(ch["name"])
        except Exception as exc:  # noqa: BLE001
            log.warning("Aviso a «%s» fallido: %s", ch["name"], exc)
            errors.append(f"{ch['name']}: {type(exc).__name__}")
    return ok, errors


def send_text(channels: list[dict], title: str, lines: list[str] | None = None, color: str = ACCENT,
              url: str = "") -> tuple[list[str], list[str]]:
    """Aviso sencillo: título y unas líneas (problemas de la ronda, cambios de rutas, prueba del canal)."""
    return send(channels, Message(title, url=url, color=color, lines=list(lines or [])))


# ------------------------------------------------------------------------ avisos
def _panel(panel_url: str, path: str) -> str:
    panel = (panel_url or "").rstrip("/")
    return f"{panel}{path}" if panel else ""


def _times(d: dict) -> str:
    return fmt_clock(d.get("departs_at"), d.get("arrives_at"))


def _leg_text(leg: dict) -> str:
    """«Vueling 40 €», con el par de lugares real si difiere de la vigilancia («Ryanair 55 € (TFS→SVQ)»)."""
    prov = PROVIDERS.get(leg["provider"])
    text = f"{prov.label if prov else leg['provider']} {fmt_price(leg['price'])}"
    return text + (f" ({leg['route']})" if leg.get("route") else "")


def trip_message(trip: dict, outbound: dict, ret: dict | None, deals: list[dict], base: float | None,
                 panel_url: str = "", day_totals: dict | None = None) -> Message:
    """Un mensaje por viaje: cada combinación (fecha de ida) con su total y un enlace por tramo. En un viaje de
    solo ida (`ret` es None) cada combinación es solo la ida. `day_totals` ({fecha de ida: total más barato}) da
    el calendario resumen de la imagen."""
    one_way = ret is None
    route = f"{outbound['origin']}{'→' if one_way else '⇄'}{outbound['destination']}"
    url = _panel(panel_url, f"/trips/{trip['id']}")
    nights = "" if one_way else f" · {fmt_nights_range(trip['min_nights'], trip['max_nights'])}"
    msg = Message(f"🧳 {trip['name']}", url=url, color=DEAL,
                  summary=f"{route}{nights}" + (f" · habitual ≈ {fmt_price(base)}" if base else ""))
    sec = Section("Más baratas" if one_way else "Ida y vuelta más baratas", DEAL)
    for q in sorted(deals, key=lambda q: q["total"]):
        o, r = q["out"], q["ret"]
        if one_way:
            times = _times(o)
            links = [(_leg_text(o), o["link"])] if o["link"] else []
            buttons = [f"{fmt_short_day(q['out_date'])} · {_leg_text(o)}"] if o["link"] else []
            sec.items.append(Item(fmt_day(q["out_date"]), fmt_price(q["total"]),
                                  _leg_text(o) + (f" ({times})" if times else ""), links, buttons))
            continue
        title = f"{fmt_day(q['out_date'])} → {fmt_day(q['ret_date'])} · {fmt_nights(q['nights'])}"
        detail = []
        for label, leg in (("ida", o), ("vuelta", r)):
            times = _times(leg)
            detail.append(f"{label} {_leg_text(leg)}" + (f" ({times})" if times else ""))
        links = [(f"Ida: {_leg_text(o)}", o["link"]), (f"Vuelta: {_leg_text(r)}", r["link"])]
        buttons = [f"Ida {fmt_short_day(q['out_date'])} · {_leg_text(o)}",
                   f"Vuelta {fmt_short_day(q['ret_date'])} · {_leg_text(r)}"]
        keep = [(lk, b) for lk, b in zip(links, buttons) if lk[1]]
        sec.items.append(Item(title, fmt_price(q["total"]), " · ".join(detail), [lk for lk, _b in keep],
                              [b for _lk, b in keep]))
    msg.sections.append(sec)
    if url:
        msg.links.append(("📊 Todas las combinaciones", url))
    if day_totals:
        subtitle = ("Precio más bajo por fecha de ida" if one_way else "Total más barato por fecha de ida") \
            + " · con borde, las del aviso"
        msg.image = images.calendar_png(day_totals, {date.fromisoformat(q["out_date"]) for q in deals},
                                        f"{trip['name']} ({route})", subtitle)
    return msg


def send_trip_deals(channels: list[dict], trip: dict, outbound: dict, ret: dict, deals: list[dict], base: float | None,
                    panel_url: str = "", day_totals: dict | None = None) -> tuple[list[str], list[str]]:
    return send(channels, trip_message(trip, outbound, ret, deals, base, panel_url, day_totals))


def sample_message(panel_url: str = "") -> Message:
    """Aviso de ejemplo para «Enviar prueba» de un canal: el mismo formato que uno de verdad, con datos inventados."""
    today = date.today()
    days = {today + timedelta(days=d): 45 + (d * 37) % 60 for d in range(5, 60) if d % 3}
    cheap = sorted(days, key=days.get)[:3]
    msg = Message("✅ Trip Watch: las notificaciones funcionan", url=_panel(panel_url, "/"), color=DEAL,
                  summary="Así se verá un aviso (precios de ejemplo, no son reales).")
    sec = Section("Aerolínea de ejemplo", ACCENT, "habitual ≈ 75 €")
    for d in sorted(cheap):
        price = fmt_price(days[d])
        sec.items.append(Item(fmt_day(d), price, "directo · 07:05–08:55", [(fmt_day(d), "https://example.com/")],
                              [f"{fmt_short_day(d)} · {price}"]))
    msg.sections.append(sec)
    msg.image = images.calendar_png(days, set(cheap), "Sevilla → Tenerife (ejemplo)",
                                    "Precio más bajo de cada día · con borde, los del aviso")
    return msg
