"""Navegador real: Chrome con patchright (Playwright parcheado para que no se note que está automatizado).

- `launch(pw, settings)`: Google Chrome si está instalado (`patchright install chrome`, como en la imagen Docker) o,
  si no, el Chromium de patchright (o el de `FW_CHROMIUM`). **Con ventana** si «Modo sin ventana» está desactivado
  en Ajustes y hay pantalla (`DISPLAY`; en Docker, la pantalla virtual de Xvfb, así que no hace falta monitor); si
  no hay pantalla, sin ventana. No se cambian el User-Agent ni las cabeceras: las del navegador cuadran con su huella.
- `BrowserFetch`: Chrome abierto en la portada de una web; las peticiones de la API se hacen con `fetch()` desde la
  propia página, así llevan sus cookies, su huella TLS y los retos de JavaScript del anti-bot ya resueltos. Lo usan
  las medidas anti-bot (`stealth.py`) cuando la petición normal choca con un anti-bot. Las cookies se guardan en
  `DATA_DIR/navegador/<clave>.json` para la próxima vez, como haría un navegador de verdad.

Lo usa también `CalendarProvider` (proveedores que recorren la web) a través de `checker.browser_session`.
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from urllib.parse import urlencode

log = logging.getLogger("browser")

#: Pausa tras abrir la portada, como quien la mira antes de buscar (segundos, al azar entre los dos).
WARMUP_PAUSE = (1.5, 3.5)
GOTO_TIMEOUT_MS = 45_000

FETCH_JS = """async ({url, method, headers, body, timeoutMs}) => {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, {method, headers, body, credentials: 'include', signal: ctrl.signal});
    const h = {};
    r.headers.forEach((v, k) => { h[k] = v; });
    return {status: r.status, url: r.url, headers: h, text: await r.text()};
  } catch (e) {
    return {error: String(e && e.name === 'AbortError' ? 'tiempo agotado' : e)};
  } finally {
    clearTimeout(timer);
  }
}"""


def sync_playwright():
    from patchright.sync_api import sync_playwright as start
    return start()


def has_display() -> bool:
    return bool(os.getenv("DISPLAY"))


def launch(pw, settings: dict, trace=None):
    """Abre el navegador según los Ajustes (ver la cabecera del módulo)."""
    say = trace or (lambda level, text: None)
    want_window = str(settings.get("headless", "1")) != "1"
    headless = not (want_window and has_display())
    if want_window and headless:
        say("warn", "  No hay pantalla (DISPLAY): el navegador va sin ventana")
        log.info("Sin DISPLAY: el navegador se abre sin ventana aunque Ajustes pida ventana")
    kw: dict = {"headless": headless}
    if settings.get("proxy_url"):
        kw["proxy"] = {"server": settings["proxy_url"]}
    exe = os.getenv("FW_CHROMIUM")
    if exe:
        return pw.chromium.launch(executable_path=exe, args=["--no-sandbox"], **kw)
    try:
        return pw.chromium.launch(channel="chrome", **kw)
    except Exception:  # noqa: BLE001 - sin Google Chrome instalado: el Chromium de patchright
        log.info("Google Chrome no está instalado: se usa Chromium")
        return pw.chromium.launch(**kw)


class BrowserResponse:
    """Respuesta de un `fetch()` hecho en la página, con lo que usa `ApiProvider` de `requests.Response`."""

    def __init__(self, data: dict):
        self.status_code = int(data["status"])
        self.url = data.get("url") or ""
        self.headers = {k.lower(): v for k, v in (data.get("headers") or {}).items()}
        self.text = data.get("text") or ""
        self.content = self.text.encode()
        self.ok = self.status_code < 400
        self.cookies: dict = {}

    def json(self):
        return json.loads(self.text)


class BrowserFetch:
    """Chrome abierto (al primer uso) en la portada de cada web, para hacer las peticiones desde ella.

    Usa la API síncrona de patchright, que solo funciona en el hilo que la abrió: se crea y se cierra dentro del
    mismo `with` de la sesión del proveedor.
    """

    def __init__(self, key: str, trace=None):
        self.key = key
        self.trace = trace or (lambda level, text: None)
        self._pw = self._browser = self._ctx = None
        self._pages: dict = {}

    def _state_path(self):
        from .. import config
        return config.DATA_DIR / "navegador" / f"{self.key}.json"

    def _open(self):
        from .. import db
        settings = db.get_settings()
        self._pw = sync_playwright().start()
        self._browser = launch(self._pw, settings, self.trace)
        state = self._state_path()
        self._ctx = self._browser.new_context(
            locale="es-ES", timezone_id=settings.get("timezone") or "Europe/Madrid", no_viewport=True,
            storage_state=str(state) if state.is_file() else None,
        )
        self.trace("info", f"  Chrome abierto ({'sin ventana' if not has_display() or settings.get('headless', '1') == '1' else 'con ventana'})")

    def page_for(self, site: str):
        page = self._pages.get(site)
        if page is not None:
            return page
        if self._ctx is None:
            self._open()
        page = self._ctx.new_page()
        self.trace("info", f"  Chrome: abro {site}/ (resuelve los retos del anti-bot y guarda sus cookies)")
        resp = page.goto(site + "/", wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: BLE001 - hay webs que nunca dejan de pedir cosas
            pass
        time.sleep(random.uniform(*WARMUP_PAUSE))
        status = resp.status if resp is not None else "?"
        self.trace("ok" if resp is not None and resp.status < 400 else "warn",
                   f"  ← portada {status} en Chrome, {len(self._ctx.cookies())} cookies")
        self._pages[site] = page
        return page

    def request(self, site: str, method: str, url: str, params=None, json=None, data=None, headers=None,
                timeout=None, **_kw) -> BrowserResponse:
        if params:
            url += ("&" if "?" in url else "?") + urlencode({k: v for k, v in params.items() if v is not None})
        headers = dict(headers or {})
        body = None
        if json is not None:
            body = _json_dumps(json)
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(data, dict):
            body = urlencode(data)
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8")
        elif data is not None:
            body = data if isinstance(data, str) else data.decode()
        page = self.page_for(site)
        result = page.evaluate(FETCH_JS, {"url": url, "method": method.upper(), "headers": headers, "body": body,
                                          "timeoutMs": int((timeout or 30) * 1000)})
        if result.get("error"):
            raise BrowserError(f"fetch() en Chrome: {result['error']}")
        return BrowserResponse(result)

    def close(self):
        try:
            if self._ctx is not None:
                path = self._state_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                self._ctx.storage_state(path=str(path))
                self._ctx.close()
        except Exception as exc:  # noqa: BLE001 - cerrar nunca debe tumbar la ronda
            log.warning("No se guardaron las cookies del navegador de %s: %s", self.key, exc)
        for obj, method in ((self._browser, "close"), (self._pw, "stop")):
            try:
                if obj is not None:
                    getattr(obj, method)()
            except Exception:  # noqa: BLE001
                pass
        self._pw = self._browser = self._ctx = None
        self._pages = {}


class BrowserError(RuntimeError):
    """El navegador no ha podido hacer la petición (no arranca, no carga la portada, fetch() falla…)."""


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)
