"""Dobles de prueba compartidos por el test de humo y el servidor de las pruebas del panel (e2e).

Importar **después** de fijar DATA_DIR (app.config lo lee al importarse). Sustituye el navegador, los
proveedores conocidos (precios y cobertura simulados, sin red ni pausas: los scripts de Vueling, Ryanair, Wizz Air y
el Buscador de pruebas se cargan de verdad, pero sus llamadas a la web se cambian por las de aquí), las descargas de
paquetes de proveedores (sirve los incluidos desde el repositorio), el cambio de divisas del BCE y el envío de
avisos (se guardan en SENT/TARGETS). Los demás scripts (los que crean los tests) se ejecutan tal cual.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from app import checker, db, fx, notify, places
from app.providers import PROVIDERS, CalendarProvider, DayPrice, bundle, scripted

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
          "wizzair": [24000, 12000, 30000], "buscador": [90, 70, 85]}
CURRENCY = {"wizzair": "HUF"}
# Con TCI el checker consulta TFN y TFS: Vueling solo opera TFN y Ryanair solo TFS (como en la realidad).
# Wizz Air solo vuela entre BCN y BUD. El Buscador y MockWeb, cualquier ruta.
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


#: Precios a medida por proveedor (el servidor de e2e pone unos meses de precios variados).
FETCH: dict = {}
#: Proveedores cuyas llamadas a la web se simulan aquí.
FAKE_KEYS = {"vueling", "ryanair", "wizzair", "buscador", "mockweb"}


def make_fetch(key):
    def fetch(self, page, origin, destination, max_months, debug_dir=None, **_kw):
        if key in FETCH:
            return FETCH[key](self, page, origin, destination, max_months, debug_dir)
        _blocked(key)
        if not operates(key, origin, destination):
            return []
        return [DayPrice(TODAY + timedelta(days=10 + i), p, currency=CURRENCY.get(key, "EUR"), origin=origin,
                         destination=destination, stops=1 if key == "buscador" and i == 1 else 0)
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


def fake_download(url):
    """El catálogo, desde el repositorio (como si se descargara de GitHub); el resto, 404."""
    if url == bundle.CATALOG_URL + bundle.CATALOG.name:
        return bundle.CATALOG.read_text("utf-8")
    raise bundle.BundleError("El enlace no existe (HTTP 404).")


def fake_fx_fetch():
    return {**RATES, "fetched_at": datetime.now().isoformat(timespec="seconds")}


#: Buscador de pruebas: cubre cualquier ruta (como mucho 12 pares) y recibe el máximo de escalas, lo que no hace
#: ninguna aerolínea del catálogo. Solo existe en los tests; sus llamadas a la web se simulan como las de los demás.
BUSCADOR = bundle.dumps([{
    "key": "buscador", "label": "Buscador", "color": "#1a73e8", "coverage": "universal", "max_routes": 12,
    "health_origin": "SVQ", "health_destination": "TFN", "link_template": "https://buscador.test/{origin}/{destination}/{date}",
    "notes": "Solo para los tests.", "min_interval": 0, "stealth": 0,
    "code": "def fetch_route(api, origin, destination, start, max_months, max_stops=None):\n    return {}\n",
}])


def import_extra():
    """Wizz Air (del catálogo) y el Buscador directamente en la BD, como si se hubieran importado."""
    catalog = [p for p in bundle.loads(bundle.CATALOG.read_text("utf-8")) if p["key"] == "wizzair"]
    with db.connect() as con:
        for p in catalog + bundle.loads(BUSCADOR):
            if not db.get_provider_script(con, p["key"]):
                db.save_provider_script(con, p["key"], bundle.values(p) | {"enabled": 1}, "admin")
    scripted.reload()


def install():
    checker.browser_session = fake_session
    PROVIDERS["mockweb"] = MockWebProvider()
    MockWebProvider.fetch_prices = make_fetch("mockweb")
    MockWebProvider.network, MockWebProvider.probe = make_network("mockweb"), make_probe("mockweb")
    MockWebProvider.min_interval = MockWebProvider.jitter = 0
    for name, make in (("fetch_prices", make_fetch), ("network", make_network), ("probe", make_probe)):
        real = getattr(scripted.ScriptedProvider, name)

        def method(self, *args, _real=real, _make=make, **kw):
            if self.key in FAKE_KEYS:
                return _make(self.key)(self, *args, **kw)
            return _real(self, *args, **kw)
        setattr(scripted.ScriptedProvider, name, method)
    real_init = scripted.ScriptedProvider.__init__

    def init(self, row, *args, **kw):
        real_init(self, row, *args, **kw)
        if self.key in FAKE_KEYS:
            self.min_interval = self.jitter = 0
    scripted.ScriptedProvider.__init__ = init
    fx.fetch = fake_fx_fetch
    bundle.download = fake_download
    notify.send = fake_send
