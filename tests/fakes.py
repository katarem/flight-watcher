"""Dobles de prueba compartidos por el test de humo y el servidor de las pruebas del panel (e2e).

Importar **después** de fijar DATA_DIR (app.config lo lee al importarse). Sustituye el navegador, los
proveedores (precios simulados, sin red) y el envío de avisos (se guardan en SENT/TARGETS).
"""
from contextlib import contextmanager
from datetime import date, timedelta

from app import checker, notify
from app.providers import PROVIDERS, CalendarProvider, DayPrice

TODAY = date.today()


class FakePage:
    def set_default_timeout(self, _): ...
    def screenshot(self, **_): ...


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


PRICES = {"vueling": [55, 30, 70], "ryanair": [60, 45, 80], "mockweb": [120, 95, 140]}  # 2.º día, el más barato
# Con TCI el checker consulta TFN y TFS: Vueling solo opera TFN y Ryanair solo TFS (como en la realidad).
OPERATES = {"vueling": {"TFN"}, "ryanair": {"TFS"}}

SENT: list = []
TARGETS: list = []  # nombres de los canales a los que iba cada aviso


def make_fetch(key):
    def fetch(self, page, origin, destination, max_months, debug_dir=None):
        if key in OPERATES and not OPERATES[key] & {origin, destination}:
            return []
        return [DayPrice(TODAY + timedelta(days=10 + i), p, origin=origin, destination=destination)
                for i, p in enumerate(PRICES[key])]
    return fetch


def fake_send(channels, lines):
    SENT.append((list(lines["markdown"]), list(lines["html"])))
    TARGETS.append(tuple(c["name"] for c in channels))
    return [c["name"] for c in channels], []


def install():
    checker.browser_session = fake_session
    PROVIDERS["mockweb"] = MockWebProvider()
    for k, prov in PROVIDERS.items():
        type(prov).fetch_prices = make_fetch(k)
    notify.send = fake_send
