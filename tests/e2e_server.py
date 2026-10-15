"""Servidor para las pruebas del panel en navegador (`frontend/e2e`): `python -m tests.e2e_server [puerto]`

Arranca la app de verdad (API + panel compilado en app/web) sobre una BD temporal, con los proveedores
y los avisos simulados de `tests.fakes`, y con precios ya cargados para que haya calendario y gráficas.
Usuario: admin / clave-de-prueba-1.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="fw-e2e-")
os.environ["PANEL_USER"], os.environ["PANEL_PASSWORD"] = "admin", "clave-de-prueba-1"

import uvicorn  # noqa: E402

from app import checker, db  # noqa: E402
from app.main import _bootstrap_admin, app  # noqa: E402
from app.providers import DayPrice, bundle, scripted  # noqa: E402

from . import fakes  # noqa: E402

fakes.install()


def rich_fetch(key, base, operates):
    """Unos meses de precios variados (con algún día muy barato) para que el calendario tenga chicha."""
    def fetch(self, page, origin, destination, max_months, debug_dir=None, **_kw):
        if not operates & {origin, destination}:
            return []
        out = []
        for d in range(3, 120):
            day = fakes.TODAY + timedelta(days=d)
            price = base + (d * 37 + len(key) * 11) % 70 + (25 if day.weekday() >= 4 else 0)
            if d % 23 == 0:
                price = base - 25 + d % 5
            if key == "ryanair" and d % 3:
                continue
            out.append(DayPrice(day, float(price), origin=origin, destination=destination))
        return out
    return fetch


fakes.FETCH["vueling"] = rich_fetch("vueling", 55, {"TFN"})
fakes.FETCH["ryanair"] = rich_fetch("ryanair", 45, {"TFS"})


def seed():
    """Histórico de unos días (para que haya «habitual» y gráficas) en los tramos del viaje sembrado
    (SVQ ⇄ TCI), con un canal asignado, y una ronda simulada."""
    with db.connect() as con:
        admin = db.get_user_by_username(con, "admin")
        chan = db.create_channel(con, admin["id"], "discord", "Discord de casa", {"webhook": "https://discord.com/api/webhooks/1/x"})
        trip = db.list_trips(con, admin["id"])[0]  # el viaje inicial de ida y vuelta
        db.set_trip_channels(con, trip["id"], [chan])
        for w in db.trip_legs(con, trip["id"]).values():
            o, d = ("SVQ", "TFN") if w["role"] == "outbound" else ("TFN", "SVQ")
            for back in range(6, 0, -1):
                when = (datetime.now() - timedelta(days=back)).isoformat(timespec="seconds")
                rows = [DayPrice(fakes.TODAY + timedelta(days=day), 60 + (day * 7 + back * 3) % 50, origin=o, destination=d)
                        for day in range(10, 70)]
                db.insert_prices(con, w["id"], "vueling", when, rows)
    checker.run_checks(trigger="manual")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    # Lo mismo que hace el arranque de la app (idempotente), y después los precios, antes de aceptar peticiones.
    db.init()
    bundle.seed()
    scripted.reload()
    fakes.import_extra()  # Wizz Air y el Buscador de pruebas, para tener los cuatro proveedores
    db.seed_defaults(_bootstrap_admin())
    seed()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
