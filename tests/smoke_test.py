"""Test de humo sin red ni navegador real: `python -m tests.smoke_test`

Sustituye el navegador y los proveedores por datos simulados y comprueba de extremo a extremo:
guardado de precios, reglas de aviso, enlaces con fecha, mensajes, panel, gráficas y ajustes.
"""
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="fw-test-")

from fastapi.testclient import TestClient  # noqa: E402

from app import checker, db, notify  # noqa: E402
from app.main import app  # noqa: E402
from app.providers import PROVIDERS, CalendarProvider, DayPrice  # noqa: E402
from app.providers.extract import JsonCollector, parse_day, parse_price, walk_json  # noqa: E402

TODAY = date.today()


# ------------------------------------------------------------- doble de navegador
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


checker.browser_session = fake_session

class MockWebProvider(CalendarProvider):
    """Proveedor con navegador (como los que no tienen API) para cubrir esa rama del checker."""
    key, label = "mockweb", "MockWeb"


PROVIDERS["mockweb"] = MockWebProvider()
PRICES = {"vueling": [55, 30, 70], "ryanair": [60, 45, 80], "mockweb": [120, 95, 140]}  # 2.º día, el más barato
# Con TCI el checker consulta TFN y TFS: Vueling solo opera TFN y Ryanair solo TFS (como en la realidad).
OPERATES = {"vueling": {"TFN"}, "ryanair": {"TFS"}}


def make_fetch(key):
    def fetch(self, page, origin, destination, max_months, debug_dir=None):
        if key in OPERATES and not OPERATES[key] & {origin, destination}:
            return []
        return [DayPrice(TODAY + timedelta(days=10 + i), p, origin=origin, destination=destination)
                for i, p in enumerate(PRICES[key])]
    return fetch


for k, prov in PROVIDERS.items():
    type(prov).fetch_prices = make_fetch(k)

SENT = []


def fake_send(settings, discord_lines, telegram_lines):
    SENT.append((list(discord_lines), list(telegram_lines)))
    return ["discord"], []


notify.send = fake_send


def check(cond, msg):
    print(("  OK  " if cond else " FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def main():
    with TestClient(app) as client:
        # --- páginas base
        for path in ("/", "/watches/new", "/settings", "/runs", "/debug"):
            check(client.get(path).status_code == 200, f"GET {path}")
        check("Sevilla → Tenerife" in client.get("/").text and "SVQ → TCI" in client.get("/").text,
              "vigilancias iniciales sembradas (SVQ ↔ TCI)")

        # --- ronda 1 (sin histórico): solo aplica el precio máximo
        db.save_settings({"discord_webhook": "https://discord.com/api/webhooks/1/x"})
        check(checker.run_checks(trigger="manual") == "done", "run_checks termina")
        check(len(SENT) == 2, f"un aviso por vigilancia ({len(SENT)})")
        discord = "\n".join(SENT[0][0])
        telegram = "\n".join(SENT[0][1])
        target_day = (TODAY + timedelta(days=11)).isoformat()
        check(f"dd={target_day}" in discord and "o=SVQ&d=TFN" in discord, "enlace Vueling con la fecha elegida")
        check("<a href=" in telegram and "&amp;dd=" in telegram, "enlace en HTML escapado para Telegram")
        check("30 €" in discord, "precio bajo incluido en el aviso")
        check("Ryanair" not in discord, "Ryanair (45 €) no supera el precio máximo de 40 €")
        with db.connect() as con:
            routes_saved = {(r[0], r[1], r[2]) for r in con.execute("SELECT provider, origin, destination FROM prices")}
        check(("vueling", "SVQ", "TFN") in routes_saved and ("ryanair", "SVQ", "TFS") in routes_saved
              and not any(o == "TCI" or d == "TCI" for _, o, d in routes_saved),
              "TCI se expande a TFN/TFS y se guarda el aeropuerto real")
        runs = client.get("/runs").text
        check("La web no devolvió" not in runs, "una ruta no operada dentro de TCI no cuenta como error")

        # --- no repite avisos de lo ya notificado
        SENT.clear()
        checker.run_checks(trigger="manual")
        check(not SENT, "no reenvía avisos ya enviados")

        # --- regla relativa: histórico caro previo + precio actual muy inferior
        with db.connect() as con:
            wid = db.create_watch(con, {
                "name": "Prueba relativa", "origin": "MAD", "destination": "BCN", "providers": ["mockweb"],
                "max_price": None, "discount_pct": 30, "date_from": None, "date_to": None, "enabled": True,
            })
            old = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
            db.insert_prices(con, wid, "mockweb", old, [DayPrice(TODAY + timedelta(days=20 + i), 200) for i in range(40)])
        SENT.clear()
        checker.run_checks(watch_id=wid, trigger="manual")
        check(len(SENT) == 1 and "habitual ≈ 200 €" in "\n".join(SENT[0][0]), "regla relativa sobre la mediana histórica")

        # --- panel, detalle y gráficas
        page = client.get(f"/watches/{wid}")
        check(page.status_code == 200 and "chart-min" in page.text, "detalle con gráficas")
        charts = client.get(f"/api/watches/{wid}/charts").json()
        check(charts["min_over_time"]["labels"] and "mockweb" in charts["min_over_time"]["series"], "API de gráficas")
        hist = client.get(f"/api/watches/{wid}/date-history", params={"date": (TODAY + timedelta(days=20)).isoformat()}).json()
        check(len(hist["labels"]) >= 1, "API del historial de una fecha")
        check(client.get("/watches/1?provider=vueling").status_code == 200, "filtro por proveedor")
        home = client.get("/").text
        check("tickets.vueling.com/booking" in home and "d=TFN" in home, "el panel muestra el enlace con fecha y aeropuerto real")
        check("originIata=SVQ&amp;destinationIata=TFS" in home and "SVQ→TFS" in home, "Ryanair enlaza a TFS dentro de TCI")

        # --- ajustes: plantilla de enlace personalizada y validaciones
        r = client.post("/settings", data={
            "schedule_hours": "8,20", "schedule_minute": "30", "timezone": "Europe/Madrid", "max_months": "11",
            "min_samples": "30", "retention_days": "400", "headless": "1", "notify_errors": "1",
            "link_ryanair": "https://www.ryanair.com/x?o={origin}&d={destination}&f={date_dmy}", "link_vueling": "",
        }, follow_redirects=False)
        check(r.status_code == 303, "guardar ajustes")
        s = db.get_settings()
        check(s["schedule_hours"] == "8,20" and s["discord_webhook"].startswith("https://discord"), "ajustes persistidos y secreto conservado")
        bad = client.post("/settings", data={"schedule_hours": "99", "schedule_minute": "0", "timezone": "Nope/Zone",
                                             "max_months": "11", "min_samples": "30", "retention_days": "400"})
        check("Las horas deben ser" in bad.text and "Zona horaria desconocida" in bad.text, "validación de ajustes")
        link = PROVIDERS["ryanair"].build_link(s["link_ryanair"], "SVQ", "TFN", date(2026, 10, 24))
        check(link.endswith("f=24/10/2026"), "plantilla de enlace personalizada")

        # --- CRUD de vigilancias
        bad = client.post("/watches", data={"origin": "SV", "destination": "TFN"})
        check("código IATA" in bad.text and "al menos un proveedor" in bad.text, "validación del formulario")
        r = client.post("/watches", data={"origin": "agp", "destination": "bcn", "providers": ["vueling"], "max_price": "25"},
                        follow_redirects=False)
        check(r.status_code == 303, "crear vigilancia")
        with db.connect() as con:
            new = [w for w in db.list_watches(con) if w["origin"] == "AGP"][0]
        check(new["destination"] == "BCN" and new["max_price"] == 25.0, "IATA normalizado a mayúsculas")
        check(client.post(f"/watches/{new['id']}/toggle", follow_redirects=False).status_code == 303, "pausar/reanudar")
        check(client.post(f"/watches/{new['id']}/delete", follow_redirects=False).status_code == 303, "eliminar")
        check(client.get("/api/status").json() == {"running": False, "current": ""}, "estado de ejecución")
        check(client.get("/runs").text.count("correcta") >= 2, "historial de ejecuciones")

    # --- extractor genérico
    out = {}
    walk_json({"data": {"calendar": [{"departureDate": "2026-10-24T06:00:00", "price": {"amount": 34.5, "currency": "EUR"}, "taxAmount": 9},
                                     {"date": "2026-10-25", "lowestPrice": 41}]}, "map": {"2026-11-02": 29, "2026-11-03": {"price": 33}}}, out)
    check(out[date(2026, 10, 24)] == 34.5 and out[date(2026, 10, 25)] == 41 and out[date(2026, 11, 2)] == 29
          and out[date(2026, 11, 3)] == 33, "walk_json: registros, precios anidados y mapas por fecha")
    check(parse_day("sábado, 24 de octubre de 2026") == date(2026, 10, 24) and parse_day("2026-10-24") == date(2026, 10, 24), "parse_day")
    check(parse_price("desde 45,50 €") == 45.5 and parse_price("24 45€") == 45.0 and parse_price("sin precio") is None, "parse_price")

    # --- la base de datos está consistente
    con = sqlite3.connect(db.DB_PATH)
    check(con.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "integridad SQLite")
    print("\nTodo correcto.")


if __name__ == "__main__":
    main()
