"""Medidas anti-bot de un proveedor (selector «Medidas anti-bot» en su editor, `provider_scripts.stealth`).

Tres niveles (`LEVELS`):

- **Ninguna** (`OFF`): `requests` con el User-Agent honesto de la app (`base.USER_AGENT`).
- **Huella de Chrome** (`FINGERPRINT`): las peticiones se hacen pasar por las de una persona con Chrome (abajo) y,
  si aun así chocan con un anti-bot, se repiten desde Chrome de verdad.
- **Siempre Chrome** (`BROWSER`): todas las peticiones van con `fetch()` desde Chrome de verdad, sin probar antes
  la huella. Para webs cuyo anti-bot exige algo que solo genera su JavaScript en cada petición (Imperva con su
  `x-d-token`, por ejemplo); más lento y con más memoria, pero es lo único que les vale.

Con la huella de Chrome:

- **Huella TLS y HTTP/2 de Chrome** con `curl_cffi` (`impersonate="chrome"`): Cloudflare, Akamai o DataDome miran
  cómo se negocia la conexión (JA3/JA4, ajustes de HTTP/2), no solo el User-Agent. Con ella van también el
  User-Agent y las cabeceras `sec-ch-ua*` de esa versión de Chrome, coherentes con la huella.
- **Cabeceras de navegador** en español: `Accept-Language`, `Sec-Fetch-*` y, en las llamadas a la API desde
  otro subdominio de la web, `Origin` y `Referer` de la portada, como las de la propia web.
- **Una sola sesión con cookies** por proveedor durante `SESSION_TTL` (como alguien que sigue en la web), en lugar
  de un cliente nuevo para cada ruta.
- **Visita previa a la portada** de cada web antes de su primera llamada a la API (de ahí salen las cookies de los
  anti-bot, como `__cf_bm` o `_abck`) y una pausa de «lectura».
- **Pausas más variables** entre peticiones (lo aplica `ScriptedProvider`: más `jitter`).
- **Chrome de verdad si aun así hay bloqueo**: si una respuesta parece de un anti-bot (403/429 o su página de
  reto), se repite con `fetch()` desde Chrome (`browser.BrowserFetch`, con patchright), que ejecuta los retos de
  JavaScript. A partir de ahí, ese proveedor sigue con Chrome mientras dure la sesión.

Chrome abre la página que el script pida en `BROWSER_PAGE` o, si no define ninguna, la portada del dominio de la
API (`site_of`). Hace falta la página buena cuando la API solo acepta peticiones (CORS) desde otro subdominio o el
anti-bot solo corre en ella (Air Europa: la API está en api-des.aireuropa.com y el anti-bot en
digital.aireuropa.com).

Lo que no hace: resolver CAPTCHA que piden intervención (imágenes, casillas) ni reutilizar cookies sacadas de otro
navegador. Sin `curl_cffi` instalado, la huella se queda en las cabeceras de Chrome con `requests` (la huella TLS
sería la de Python) y la consola de la prueba lo dice.
"""
from __future__ import annotations

import ipaddress
import random
import threading
import time
from urllib.parse import urlsplit

import requests

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests import exceptions as curl_exceptions
except ImportError:  # pragma: no cover - curl_cffi va en requirements.txt
    curl_requests = curl_exceptions = None

#: Navegador que se imita (el Chrome más reciente que conoce curl_cffi).
IMPERSONATE = "chrome"
#: Cuánto dura la sesión (cookies) de un proveedor antes de empezar otra, en segundos.
SESSION_TTL = 30 * 60
#: Pausa tras visitar la portada, como quien la mira antes de buscar (segundos, al azar entre los dos).
WARMUP_PAUSE = (1.0, 2.5)
ACCEPT_LANGUAGE = "es-ES,es;q=0.9,en;q=0.8"
#: Sin curl_cffi: cabeceras de un Chrome de escritorio (la huella TLS seguirá siendo la de Python).
FALLBACK_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/141.0.0.0 Safari/537.36"),
    "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
NAVIGATE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Sec-Fetch-Site": "none", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-User": "?1", "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
}

#: Errores de red de los dos clientes (`ApiProvider.request` los convierte en `ProviderError`).
TIMEOUT_ERRORS: tuple[type[BaseException], ...] = (requests.Timeout,)
NETWORK_ERRORS: tuple[type[BaseException], ...] = (requests.RequestException,)
if curl_exceptions is not None:
    TIMEOUT_ERRORS += (curl_exceptions.Timeout,)
    NETWORK_ERRORS += (curl_exceptions.RequestException,)

_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}

#: Niveles de «Medidas anti-bot» (valor de `provider_scripts.stealth`).
OFF, FINGERPRINT, BROWSER = 0, 1, 2
LEVELS = {OFF: "Ninguna", FINGERPRINT: "Huella de Chrome y, si bloquean, Chrome", BROWSER: "Siempre Chrome"}


def level(value) -> int | None:
    """Nivel de un valor guardado o recibido (los paquetes antiguos traen true/false); None si no es válido."""
    if isinstance(value, bool):
        return int(value)
    try:
        n = int(str(value).strip()) if value is not None and str(value).strip() else OFF
    except ValueError:
        return None
    return n if n in LEVELS else None


def available() -> bool:
    return curl_requests is not None


def make_client():
    """Cliente HTTP con la huella de Chrome (o `requests` con sus cabeceras si falta curl_cffi). Los tests lo cambian."""
    if curl_requests is not None:
        return curl_requests.Session(impersonate=IMPERSONATE)
    session = requests.Session()
    session.headers.update(FALLBACK_HEADERS)
    return session


def site_of(url: str) -> str:
    """Portada de la web a la que pertenece una URL: apiw.vueling.com → https://www.vueling.com."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    try:
        ipaddress.ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False
    if is_ip or "." not in host:
        return f"{parts.scheme or 'https'}://{parts.netloc}"
    labels = host.split(".")
    n = 3 if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2 else 2
    domain = ".".join(labels[-n:])
    if host in (domain, f"www.{domain}"):
        return f"{parts.scheme or 'https'}://{host}"
    return f"https://www.{domain}"


def looks_blocked(r) -> bool:
    """¿Respuesta de un anti-bot? (403/429, o su página de reto servida con 200/503)."""
    from .base import looks_blocked as page_of_antibot
    return r.status_code in (403, 429) or page_of_antibot(r)


class StealthClient:
    """Lo que dura entre rondas para un proveedor: el cliente con la huella de Chrome y sus cookies, qué portadas
    ya se visitaron y si hace falta Chrome de verdad. Caduca a los `SESSION_TTL` segundos."""

    def __init__(self, trace=None):
        self.client = make_client()
        self.headers = self.client.headers  # el script puede añadir las suyas (api.session.headers)
        self.created = time.monotonic()
        self.trace = trace or (lambda level, text: None)
        #: Tras un bloqueo, el proveedor va directo a Chrome mientras dure la sesión.
        self.prefer_browser = False
        self._visited: set[str] = set()
        self._lock = threading.Lock()

    def expired(self) -> bool:
        return time.monotonic() - self.created > SESSION_TTL

    def close(self):
        self.client.close()

    def _warm_up(self, site: str, timeout):
        self.trace("info", f"  Anti-bot: antes visito {site}/ como un navegador (para sus cookies)")
        try:
            r = self.client.request("GET", site + "/", timeout=timeout,
                                    headers={**NAVIGATE_HEADERS, "Accept-Language": ACCEPT_LANGUAGE})
            n = len(getattr(r, "cookies", None) or {})
            self.trace("ok" if r.status_code < 400 else "warn",
                       f"  ← portada {r.status_code}, {n} cookie{'s' if n != 1 else ''}")
        except NETWORK_ERRORS as exc:
            self.trace("warn", f"  ← la portada no responde ({type(exc).__name__}); sigo con la API")
        time.sleep(random.uniform(*WARMUP_PAUSE))

    def request(self, method: str, url: str, headers: dict | None = None, timeout=None, **kw):
        site = site_of(url)
        with self._lock:
            first = site not in self._visited
            self._visited.add(site)
        if first:
            self._warm_up(site, timeout)
        same_origin = url.startswith(site + "/") or url == site
        browser = {
            "Accept": "application/json, text/plain, */*", "Accept-Language": ACCEPT_LANGUAGE,
            "Sec-Fetch-Site": "same-origin" if same_origin else "same-site", "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty", "Referer": site + "/",
        }
        if not same_origin or method.upper() != "GET":
            browser["Origin"] = site
        return self.client.request(method, url, headers={**browser, **(headers or {})}, timeout=timeout, **kw)


class StealthSession:
    """Sesión de un `with prov.new_session()` con medidas anti-bot. Se usa como `requests.Session` (`request`,
    `headers`). Si choca con un anti-bot (o con `always_browser`, desde el principio), sigue con Chrome
    (`browser.BrowserFetch`) abierto en `page` o en la portada de la API, que se cierra al salir del `with` (la API
    síncrona del navegador no se puede compartir entre hilos)."""

    def __init__(self, shared: StealthClient, key: str, trace=None, page: str | None = None,
                 always_browser: bool = False):
        self.shared, self.key = shared, key
        self.headers = shared.headers
        self.trace = trace or (lambda level, text: None)
        #: Página que abre Chrome (`BROWSER_PAGE` del script); None = la portada de la web de cada URL.
        self.page = page
        self.always_browser = always_browser
        self._browser = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
        return False

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def request(self, method: str, url: str, headers: dict | None = None, timeout=None, **kw):
        if not (self.always_browser or self.shared.prefer_browser):
            r = self.shared.request(method, url, headers=headers, timeout=timeout, **kw)
            if not looks_blocked(r):
                return r
            self.trace("warn", f"  ← {r.status_code}: parece un anti-bot; lo repito desde Chrome de verdad")
            self.shared.prefer_browser = True
        from . import browser
        from .base import ProviderError
        try:
            if self._browser is None:
                self._browser = browser.BrowserFetch(self.key, self.trace)
            return self._browser.request(self.page or site_of(url) + "/", method, url, headers=headers,
                                         timeout=timeout, **kw)
        except ImportError as exc:
            raise ProviderError("Falta patchright para usar Chrome (pip install patchright)") from exc
        except Exception as exc:  # noqa: BLE001 - un fallo del navegador es un error del proveedor, no de la ronda
            raise ProviderError(f"Chrome no ha podido hacer la petición: {exc}"[:300]) from exc


def describe(lvl: int, page: str | None = None) -> str:
    """Qué medidas se aplican (para la consola de la prueba)."""
    where = page or "la portada de la web"
    if lvl == BROWSER:
        return (f"Medidas anti-bot: siempre Chrome (patchright). Cada petición se hace con fetch() desde {where}, "
                "con sus cookies y los retos de JavaScript del anti-bot resueltos; pausas más variables.")
    tls = ("huella TLS y HTTP/2 de Chrome (curl_cffi)" if available()
           else "SIN huella TLS de Chrome (falta curl_cffi: solo cabeceras)")
    return (f"Medidas anti-bot: {tls}, cabeceras de Chrome en español, una sesión con cookies, visita previa a la "
            f"portada, pausas más variables y, si hay bloqueo, Chrome de verdad (patchright) desde {where}.")
