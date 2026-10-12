"""Prueba la mecánica de Playwright de `CalendarProvider` contra una web simulada.

    python -m tests.browser_mock_test

Necesita un Chromium (el de `patchright install chromium`, o uno propio con FW_CHROMIUM=/ruta).
Valida: cookies, «solo ida», autocompletado de aeropuertos, apertura del calendario, captura de
respuestas JSON (XHR), lectura de celdas del DOM, avance de meses y volcado de diagnóstico. También las peticiones
desde Chrome de las medidas anti-bot (`browser.BrowserFetch`): abre la portada, coge su cookie (puesta con un reto
de JavaScript, como un anti-bot) y hace el GET y el POST de la API con `fetch()` desde la página.
NO valida los selectores de las webs reales de ninguna aerolínea.
"""
import json
import os
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="fw-browser-"))
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from patchright.sync_api import sync_playwright

from app.providers.base import CalendarProvider

TODAY = date.today()
D1, D2, D3 = (TODAY + timedelta(days=n) for n in (12, 13, 45))

PAGE = """<!doctype html><meta charset=utf-8><body>
<div id=cookie><button id=onetrust-accept-btn-handler onclick="this.parentElement.remove()">Aceptar todas</button></div>
<label><input type=radio name=t> Solo ida</label>
<div><input id=o placeholder="Introducir origen" autocomplete=off><ul id=ol></ul></div>
<div><input id=d placeholder="Introducir destino" autocomplete=off><ul id=dl></ul></div>
<input id=date placeholder="Fecha ida" readonly>
<div id=cal></div>
<script>
const airports = {SVQ: 'Sevilla (SVQ)', TFN: 'Tenerife Norte (TFN)'};
let sel = {};
function wire(id, listId) {
  const inp = document.getElementById(id), ul = document.getElementById(listId);
  inp.addEventListener('input', () => {
    ul.innerHTML = '';
    for (const [c, n] of Object.entries(airports))
      if (n.toLowerCase().includes(inp.value.toLowerCase()) || c.toLowerCase() === inp.value.toLowerCase()) {
        const li = document.createElement('li'); li.textContent = n;
        li.onclick = () => { sel[id] = c; inp.value = n; ul.innerHTML = ''; };
        ul.appendChild(li);
      }
  });
}
wire('o', 'ol'); wire('d', 'dl');
const MODE = '__MODE__';
let month = 0;
function renderMonth(days) {
  const cal = document.getElementById('cal'); cal.innerHTML = '';
  const shown = days.filter(x => x.m === month);
  for (const x of shown) {
    const c = document.createElement('div'); c.className = 'day';
    c.setAttribute('data-date', x.date); c.textContent = new Date(x.date).getDate() + ' ' + x.price + ' €';
    cal.appendChild(c);
  }
  const next = document.createElement('button'); next.setAttribute('aria-label', 'Mes siguiente'); next.textContent = '>';
  next.disabled = month >= 1; next.onclick = () => { month++; renderMonth(days); };
  cal.appendChild(next);
}
document.getElementById('date').addEventListener('click', async () => {
  const r = await fetch(`/api/flightcalendar?o=${sel.o}&d=${sel.d}`);
  const data = await r.json();
  if (MODE === 'dom') renderMonth(data.days);
});
</script>"""


def calendar_json():
    rows = [
        {"date": D1.isoformat(), "m": 0, "price": 52.0, "taxAmount": 9},
        {"date": D2.isoformat(), "m": 0, "price": 33.5, "taxAmount": 9},
        {"date": D3.isoformat(), "m": 1, "price": 71.0, "taxAmount": 9},
    ]
    return {"days": rows}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, status, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        """API «protegida»: sin la cookie del reto, 403 como un anti-bot."""
        size = int(self.headers.get("Content-Length") or 0)
        sent = json.loads(self.rfile.read(size) or b"null")
        if "reto=superado" not in (self.headers.get("Cookie") or ""):
            return self._send(403, b"<html>Access Denied</html>", "text/html")
        self._send(200, json.dumps({"recibido": sent, "metodo": "POST"}).encode(), "application/json")

    def do_OPTIONS(self):
        """Preflight CORS de la API de otro origen: admite el origen y la cabecera del token, pero no cookies."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
        self.send_header("Access-Control-Allow-Headers", "x-d-token, content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/cors"):
            # Como api-des.aireuropa.com: otro origen, exige el token que añade el script de la página y su CORS
            # no admite cookies (sin Access-Control-Allow-Credentials).
            ok = self.headers.get("x-d-token") == "ok"
            self.send_response(200 if ok else 403)
            self.send_header("Content-Type", "application/json" if ok else "text/html")
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
            self.end_headers()
            self.wfile.write(json.dumps({"cors": True}).encode() if ok else b"<html>Access Denied</html>")
            return
        if self.path.startswith("/con-token"):
            # Como digital.aireuropa.com: su script (el del anti-bot) engancha fetch() y añade un token a cada petición.
            page = ("<!doctype html><script>const f = window.fetch; window.fetch = (u, o = {}) => "
                    "f(u, {...o, headers: {...(o.headers || {}), 'x-d-token': 'ok'}});</script>Reservas")
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if self.path.startswith("/antibot"):
            # La portada pone la cookie con JavaScript (un cliente sin navegador no la tendría).
            page = "<!doctype html><script>document.cookie = 'reto=superado; path=/';</script>Portada"
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if self.path.startswith("/api/protegida"):
            if "reto=superado" not in (self.headers.get("Cookie") or ""):
                return self._send(403, b"<html>Access Denied</html>", "text/html")
            return self._send(200, json.dumps({"ruta": self.path}).encode(), "application/json")
        if self.path.startswith("/api/flightcalendar"):
            body, ctype = json.dumps(calendar_json()).encode(), "application/json"
        else:
            mode = "dom" if self.path.startswith("/dom") else "json"
            body, ctype = PAGE.replace("__MODE__", mode).encode(), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)


class MockAirline(CalendarProvider):
    key, label = "mock", "Mock"
    url_hints = ("flightcalendar",)
    sel_day = [".day"]


def run(page_path: str, debug_dir: Path | None = None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    prov = MockAirline()
    prov.home_url = f"http://127.0.0.1:{server.server_port}{page_path}"
    exe = os.getenv("FW_CHROMIUM")
    kwargs = {"executable_path": exe, "args": ["--no-sandbox", "--single-process", "--no-zygote", "--disable-gpu"]} if exe else {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, **kwargs)
            page = browser.new_context(locale="es-ES").new_page()
            page.set_default_timeout(10000)
            prices = prov.fetch_prices(page, "SVQ", "TFN", 3, debug_dir)
            browser.close()
    finally:
        server.shutdown()
    return {p.day: p.price for p in prices}


def check(cond, msg):
    print(("  OK  " if cond else " FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def browser_fetch():
    """Medidas anti-bot: Chrome resuelve el «reto» de la portada y hace las peticiones de la API desde ella."""
    from app import db
    from app.providers.browser import BrowserFetch

    db.init()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)  # otro puerto = otro origen
    threading.Thread(target=api_server.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{server.server_port}"
    other = f"http://localhost:{api_server.server_port}"
    lines = []
    fetcher = BrowserFetch("prueba", lambda level, text: lines.append(text))
    try:
        # La página que pone la cookie del reto es /antibot (como la `BROWSER_PAGE` de un script).
        r = fetcher.request(site + "/antibot", "GET", site + "/api/protegida", params={"o": "SVQ", "d": None})
        check(r.status_code == 200 and r.json() == {"ruta": "/api/protegida?o=SVQ"}
              and r.headers["content-type"] == "application/json", "GET desde Chrome con la cookie del reto")
        r = fetcher.request(site + "/antibot", "POST", site + "/api/protegida", json={"a": 1})
        check(r.status_code == 200 and r.json() == {"recibido": {"a": 1}, "metodo": "POST"}, "POST con cuerpo JSON desde Chrome")
        r = fetcher.request(site + "/con-token", "GET", other + "/api/cors")
        check(r.status_code == 200 and r.json() == {"cors": True}
              and any("CORS" in line for line in lines),
              "API de otro origen: lleva el token del script de la página y, sin cookies por CORS, se repite sin ellas")
    finally:
        fetcher.close()
        server.shutdown()
        api_server.shutdown()
    from app import config
    check((config.DATA_DIR / "navegador" / "prueba.json").is_file() and any("Chrome abierto" in line for line in lines),
          "las cookies del navegador se guardan para la próxima vez")


def main():
    dbg = Path(tempfile.mkdtemp(prefix="fw-dbg-"))
    # Variante A: el calendario no pinta celdas, los precios solo viajan por el XHR JSON
    got = run("/", dbg)
    check(got == {D1: 52.0, D2: 33.5, D3: 71.0}, f"captura de JSON de red (sin usar el DOM): {got}")
    check(any(dbg.glob("*-json-*.json")) and any(dbg.glob("*.html")) and any(dbg.glob("*.png")),
          "volcado de diagnóstico (json + html + capturas)")
    # Variante B: hay celdas en el DOM y botón «mes siguiente». Se anula la vía JSON para
    # demostrar que la lectura del DOM funciona por sí sola (incluido el cambio de mes).
    from app.providers.extract import JsonCollector

    original = JsonCollector.prices
    JsonCollector.prices = lambda self: {}
    try:
        got = run("/dom")
    finally:
        JsonCollector.prices = original
    check(got == {D1: 52.0, D2: 33.5, D3: 71.0}, f"lectura de celdas del DOM + avance de mes (sin JSON): {got}")
    browser_fetch()
    print("\nTodo correcto.")


if __name__ == "__main__":
    main()
