"""Dobles de prueba compartidos por el test de humo y el servidor de las pruebas del panel (e2e).

Importar **después** de fijar DATA_DIR (app.config lo lee al importarse). Sustituye el navegador, los
proveedores (precios y cobertura simulados, sin red ni pausas), el cambio de divisas del BCE y el envío
de avisos (se guardan en SENT/TARGETS).
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from app import checker, fx, health, notify, places
from app.providers import PROVIDERS, CalendarProvider, DayPrice

TODAY = date.today()


class FakePage:
    def set_default_timeout(self, _): ...
    def screenshot(self, **_): ...
    def title(self): return "Portada"
    def content(self): return "<html></html>"

    def goto(self, url, **_):
        class Resp:
            status, headers = 200, {}
        return Resp()


class FakeContext:
    def new_page(self):
        return FakePage()

    def close(self): ...


class FakeBrowser:
    def new_context(self, **_):
        return FakeContext()


@contextmanager
def fake_session(_settings):
    yield FakeBrowser()


class MockWebProvider(CalendarProvider):
    """Proveedor con navegador (como los que no tienen API) para cubrir esa rama del checker."""
    key, label, color = "mockweb", "MockWeb", "#9b59b6"


# 2.º día, el más barato. Wizz Air cobra en florines (HUF; 1 € = 400 HUF en el cambio simulado).
PRICES = {"vueling": [55, 30, 70], "ryanair": [60, 45, 80], "mockweb": [120, 95, 140],
          "wizzair": [24000, 12000, 30000], "google": [90, 70, 85]}
CURRENCY = {"wizzair": "HUF"}
# Con TCI el checker consulta TFN y TFS: Vueling solo opera TFN y Ryanair solo TFS (como en la realidad).
# Wizz Air solo vuela entre BCN y BUD. Google Flights y MockWeb, cualquier ruta.
OPERATES = {"vueling": {"TFN"}, "ryanair": {"TFS"}, "wizzair": {"BCN", "BUD"}}
RATES = {"date": "2026-10-09", "rates": {"USD": 1.1, "HUF": 400.0, "GBP": 0.85}}
#: Pares por los que se ha preguntado a cada proveedor (para comprobar la caché y el paralelismo).
ASKED: list = []
#: Proveedores que fingen bloquear (para la prueba de acceso).
BLOCKED: set = set()


def operates(key, origin, destination) -> bool:
    if key == "wizzair":
        return {origin, destination} <= OPERATES[key]
    return key not in OPERATES or bool(OPERATES[key] & {origin, destination})

SENT: list = []
TARGETS: list = []  # nombres de los canales a los que iba cada aviso


def _blocked(key):
    from app.providers import ProviderBlocked
    if key in BLOCKED:
        raise ProviderBlocked(f"{PROVIDERS[key].label} rechaza la consulta (HTTP 403, límite o anti-bot)", 403)


def make_fetch(key):
    def fetch(self, page, origin, destination, max_months, debug_dir=None, **_kw):
        _blocked(key)
        if not operates(key, origin, destination):
            return []
        return [DayPrice(TODAY + timedelta(days=10 + i), p, currency=CURRENCY.get(key, "EUR"), origin=origin,
                         destination=destination, stops=1 if key == "google" and i == 1 else 0)
                for i, p in enumerate(PRICES.get(key, [100, 90, 110]))]
    return fetch


def make_network(key):
    def network(self, session, origin):
        _blocked(key)
        ASKED.append((key, origin, "*"))
        return {c for c, p in places.catalog().items() if p.kind == "airport" and c != origin and operates(key, origin, c)}
    return network


def make_probe(key):
    def probe(self, session, origin, destination):
        _blocked(key)
        ASKED.append((key, origin, destination))
        return operates(key, origin, destination)
    return probe


def fake_send(channels, lines):
    SENT.append((list(lines["markdown"]), list(lines["html"])))
    TARGETS.append(tuple(c["name"] for c in channels))
    return [c["name"] for c in channels], []


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status_code, self.text, self.content = status, body, body.encode()
        self.headers, self.ok = headers or {}, status < 400


#: Portadas de las aerolíneas en estudio (por URL); el resto responde 200.
PAGES: dict = {"https://www.iberia.com/es/": FakeResponse(403, "<html>Access Denied</html>", {"Server": "AkamaiGHost"})}


def fake_fetch_page(url):
    return PAGES.get(url, FakeResponse(200, "<html>hola</html>", {"cf-ray": "1"}))


def fake_fx_fetch():
    return {**RATES, "fetched_at": datetime.now().isoformat(timespec="seconds")}


def install():
    checker.browser_session = fake_session
    PROVIDERS["mockweb"] = MockWebProvider()
    for k, prov in PROVIDERS.items():
        cls = type(prov)
        cls.fetch_prices = make_fetch(k)
        cls.network = make_network(k)
        cls.probe = make_probe(k)
        cls.min_interval = cls.jitter = 0
    fx.fetch = fake_fx_fetch
    health.fetch_page = fake_fetch_page
    notify.send = fake_send
