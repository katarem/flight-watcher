"""Navegador real: Chrome con patchright (Playwright parcheado para que no se note que está automatizado).

- `launch(pw, settings)`: Google Chrome si está instalado (`patchright install chrome`, como en la imagen Docker) o,
  si no, el Chromium de patchright (o el de `FW_CHROMIUM`). **Con ventana** si «Modo sin ventana» está desactivado
  en Ajustes y hay pantalla (`DISPLAY`; en Docker, la pantalla virtual de Xvfb, así que no hace falta monitor); si
  no hay pantalla, sin ventana. No se cambian el User-Agent ni las cabeceras: las del navegador cuadran con su huella.
- `BrowserFetch`: Chrome abierto en una página de la web (la portada o la `BROWSER_PAGE` del script); las peticiones
  de la API se hacen con `fetch()` desde ella, así llevan sus cookies, su huella TLS, los retos de JavaScript del
  anti-bot ya resueltos y lo que su script añada a cada petición. Si la API no admite cookies de otro origen (CORS
  sin `Access-Control-Allow-Credentials`), se repite sin ellas. Lo usan las medidas anti-bot (`stealth.py`): cuando
  la petición normal choca con un anti-bot o, con «Siempre Chrome», en todas. Las cookies se guardan en
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
#: Veces que se repite un fetch() cortado porque la página navegó (retos de anti-bot que recargan, redirecciones).
NAV_RETRIES = 3
#: Una página recién abierta se da por asentada cuando su URL no cambia en STABLE_CHECKS comprobaciones seguidas,
#: separadas STABLE_STEP segundos (como mucho STABLE_MAX): hay webs que, ya «cargadas», redirigen con JavaScript a
#: la página buena (la intermedia aún no tiene el script del anti-bot).
STABLE_CHECKS, STABLE_STEP, STABLE_MAX = 2, 1.0, 15.0

FETCH_JS = """async ({url, method, headers, body, timeoutMs}) => {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const call = (credentials) => fetch(url, {method, headers, body, credentials, signal: ctrl.signal});
  try {
    let r, credentials = 'include';
    try {
      r = await call(credentials);
    } catch (e) {
      if (e && e.name === 'AbortError') throw e;
      // CORS: la API no admite cookies desde este origen (sin Access-Control-Allow-Credentials): sin ellas.
      credentials = 'omit';
      r = await call(credentials);
    }
    const h = {};
    r.headers.forEach((v, k) => { h[k] = v; });
    return {status: r.status, url: r.url, headers: h, text: await r.text(), credentials};
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
    """Chrome abierto (al primer uso) en una página de cada web, para hacer las peticiones desde ella.

    Usa la API síncrona de patchright, que solo funciona en el hilo que la abrió: se crea y se cierra dentro del
    mismo `with` de la sesión del proveedor.
    """

    def __init__(self, key: str, trace=None):
        self.key = key
        self.trace = trace or (lambda level, text: None)
        self._pw = self._browser = self._ctx = None
        self._pages: dict = {}
        self._no_cookies: set[str] = set()

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

    def page_for(self, url: str):
        """Pestaña abierta en `url` (la portada «https://www.web.com/» o la página que pida el script)."""
        page = self._pages.get(url)
        if page is not None:
            return page
        if self._ctx is None:
            self._open()
        page = self._ctx.new_page()
        self.trace("info", f"  Chrome: abro {url} (resuelve los retos del anti-bot y guarda sus cookies)")
        resp = page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: BLE001 - hay webs que nunca dejan de pedir cosas
            pass
        self._wait_stable(page)
        time.sleep(random.uniform(*WARMUP_PAUSE))
        status = resp.status if resp is not None else "?"
        self.trace("ok" if resp is not None and resp.status < 400 else "warn",
                   f"  ← página {status} en Chrome, {len(self._ctx.cookies())} cookies")
        self._pages[url] = page
        return page

    def _wait_stable(self, page):
        """Espera a que la URL de la página deje de cambiar (redirecciones con JavaScript tras cargar)."""
        last, same, deadline = page.url, 0, time.monotonic() + STABLE_MAX
        while same < STABLE_CHECKS and time.monotonic() < deadline:
            # wait_for_timeout y no time.sleep: con la API síncrona, solo así llegan los eventos de navegación y
            # page.url se actualiza.
            page.wait_for_timeout(STABLE_STEP * 1000)
            if page.url == last:
                same += 1
                continue
            self.trace("info", f"  Chrome: la página ha seguido navegando ({page.url}); espero a que se asiente")
            _settle(page)
            last, same = page.url, 0

    def request(self, page_url: str, method: str, url: str, params=None, json=None, data=None, headers=None,
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
        page = self.page_for(page_url)
        args = {"url": url, "method": method.upper(), "headers": headers, "body": body,
                "timeoutMs": int((timeout or 30) * 1000)}
        for attempt in range(1, NAV_RETRIES + 1):
            try:
                # En el mundo de la página (patchright, por defecto, evalúa en uno aislado): así el fetch() pasa por
                # lo que su script le enganche, como el token que añade a cada petición el anti-bot (Imperva).
                result = page.evaluate(FETCH_JS, args, isolated_context=False)
                break
            except Exception as exc:  # noqa: BLE001 - solo se repite si la página navegó a mitad
                if attempt == NAV_RETRIES or not _navigated(exc):
                    raise
                # Hay páginas que siguen navegando tras cargar (el reto del anti-bot recarga, una redirección…).
                self.trace("warn", "  Chrome: la página ha navegado mientras pedía; espero a que se asiente y lo repito")
                _settle(page)
        if result.get("error"):
            raise BrowserError(f"fetch() en Chrome: {result['error']}")
        if result.get("credentials") == "omit" and page_url not in self._no_cookies:
            self._no_cookies.add(page_url)
            self.trace("info", "  Chrome: la API no admite cookies desde esta página (CORS); las peticiones van sin ellas")
        return BrowserResponse(result)

    def cookie(self, page_url: str, name: str) -> str | None:
        """Valor de la cookie `name` que Chrome manda a la página (que se abre si aún no lo está)."""
        page = self.page_for(page_url)
        for c in self._ctx.cookies(page.url):
            if c["name"] == name:
                return c["value"]
        return None

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


def _navigated(exc: BaseException) -> bool:
    """¿Se cortó la evaluación porque la página navegó? (patchright no tiene una excepción propia para esto)."""
    text = str(exc)
    return "Execution context was destroyed" in text or "navigation" in text.lower()


def _settle(page):
    """Espera a que la página termine de navegar (y de pedir cosas, hasta un límite)."""
    for state, ms in (("domcontentloaded", GOTO_TIMEOUT_MS), ("networkidle", 10_000)):
        try:
            page.wait_for_load_state(state, timeout=ms)
        except Exception:  # noqa: BLE001 - hay webs que nunca dejan de pedir cosas
            pass
    page.wait_for_timeout(1000)


class BrowserError(RuntimeError):
    """El navegador no ha podido hacer la petición (no arranca, no carga la portada, fetch() falla…)."""


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)
