"""Prueba la mecánica de Playwright de `CalendarProvider` contra una web simulada.

    python -m tests.browser_mock_test

Necesita un Chromium (el de `playwright install chromium`, o uno propio con FW_CHROMIUM=/ruta).
Valida: cookies, «solo ida», autocompletado de aeropuertos, apertura del calendario, captura de
respuestas JSON (XHR), lectura de celdas del DOM, avance de meses y volcado de diagnóstico.
NO valida los selectores de las webs reales de ninguna aerolínea.
"""
import json
import os
import tempfile
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

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

    def do_GET(self):
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
    print("\nTodo correcto.")


if __name__ == "__main__":
    main()
