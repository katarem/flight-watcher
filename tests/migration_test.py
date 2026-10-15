"""Migraciones sobre una BD con datos: `python -m tests.migration_test`

Crea una BD SQLite en la revisión 0003 con usuarios, vigilancias (CSV de proveedores), canales, precios,
avisos y ejecuciones; aplica las migraciones pendientes como la app (`db.init`) y comprueba que no se
pierde nada (el ON DELETE CASCADE al recrear tablas en SQLite) y que los datos se convierten bien.
Crea los proveedores incluidos como al arrancar (`bundle.seed`, con la plantilla de enlace que había en Ajustes y
los del paquete sin verificar que ya usaba una vigilancia). Después crea un viaje (0005) y un proveedor (0006),
comprueba los tipos y las horas (0008), baja a 0007, a 0006, a 0005, a 0004 y a 0003 y vuelve a subir.

Aparte (en otro proceso, con su propia BD), una BD anterior a los usuarios (0001, vigilancias sin dueño): sube a
head y `bootstrap_admin` le da al administrador el viaje en que la 0009 envuelve cada vigilancia.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="fw-mig-")

from alembic import command  # noqa: E402

from app import config, db  # noqa: E402
from app.providers import bundle  # noqa: E402

TABLES = ("users", "watches", "channels", "watch_channels", "prices", "alerts", "runs")


def check(cond, msg):
    print(("  OK  " if cond else " FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def migrate(target: str, down: bool = False):
    with db.engine.connect() as con:
        con.exec_driver_sql("PRAGMA foreign_keys=OFF")  # como db.init: sin CASCADE al recrear tablas
        con.commit()
        with con.begin():
            (command.downgrade if down else command.upgrade)(db._alembic_config(con), target)


def main():
    migrate("0003")
    c = sqlite3.connect(config.DB_PATH)
    c.execute("INSERT INTO users(id, username, display_name, password_hash, role, enabled, notify_errors, created_at) "
              "VALUES (1, 'admin', 'Admin', 'x', 'admin', 1, 1, '2026-01-01T00:00:00')")
    c.execute("INSERT INTO watches(id, user_id, name, origin, destination, providers, discount_pct, enabled, created_at) "
              "VALUES (1, 1, 'Sevilla → Tenerife', 'SVQ', 'TCI', 'vueling,ryanair', 30, 1, '2026-01-01'), "
              "(2, 1, 'Madrid → Barcelona', 'MAD', 'BCN', 'vueling,wizzair', 30, 0, '2026-01-01')")
    c.execute("INSERT INTO settings(key, value) VALUES ('link_vueling', 'https://www.vueling.com/x?d={date}'), "
              "('link_ryanair', ''), ('schedule_hours', '9')")
    c.execute("INSERT INTO channels(id, user_id, kind, name, config, enabled, created_at) "
              "VALUES (1, 1, 'discord', 'Discord', '{}', 1, '2026-01-01')")
    c.execute("INSERT INTO watch_channels VALUES (1, 1), (2, 1)")
    for i in range(60):
        c.execute("INSERT INTO prices(watch_id, provider, flight_date, price, currency, checked_at, origin, destination) "
                  "VALUES (?, 'vueling', '2026-11-01', ?, 'EUR', '2026-10-01T08:00:00', 'SVQ', 'TFN')", (1 + i % 2, 30 + i))
    c.execute("INSERT INTO alerts(watch_id, provider, flight_date, price, link, sent_at) "
              "VALUES (1, 'vueling', '2026-11-01', 30, 'x', '2026-10-01')")
    c.execute("INSERT INTO runs(watch_id, provider, trigger, started_at, ok, n_prices, n_deals) "
              "VALUES (1, 'vueling', 'cron', '2026-10-01', 1, 3, 0)")
    c.commit()

    def counts():
        return {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}

    before = counts()
    db.init()
    check(counts() == before, f"0003 → head sin perder filas {before}")
    with db.connect() as con:
        w1, w2 = db.get_watch(con, 1), db.get_watch(con, 2)
    check(w1["providers"] == ["ryanair", "vueling"] and w1["coverage"]["vueling"]["routes"] == [("SVQ", "TFN"), ("SVQ", "TFS")]
          and w1["coverage"]["vueling"]["checked_at"] is None and w1["coverage"]["vueling"]["active"],
          "el CSV de proveedores pasa a watch_providers (todos los pares, sin comprobar)")
    check(w2["coverage"]["vueling"]["routes"] == [("MAD", "BCN")] and w1["max_stops"] == 0 == w2["max_stops"]
          and set(w2["coverage"]) == {"vueling", "wizzair"},
          "vigilancias sin ciudades y máximo de escalas 0 (como antes)")
    with db.connect() as con:
        check(db.latest_snapshot(con, 1, "vueling")[0]["orig_price"] is None, "los precios antiguos quedan en euros")
    check(c.execute("PRAGMA foreign_key_check").fetchall() == [] and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
          "claves foráneas e integridad")
    created = bundle.seed()
    with db.connect() as con:
        rows = {r["key"]: r for r in db.list_provider_scripts(con)}
    settings = dict(c.execute("SELECT key, value FROM settings").fetchall())
    check(created == ["vueling", "ryanair", "wizzair"] and set(rows) == {"vueling", "ryanair", "wizzair"}
          and rows["vueling"]["link_template"] == "https://www.vueling.com/x?d={date}"
          and rows["ryanair"]["link_template"].startswith("https://www.ryanair.com/")
          and not any(k.startswith("link_") for k in settings) and settings["schedule_hours"] == "9"
          and settings[bundle.SEED_FLAG] == "1" and bundle.seed() == [],
          "al arrancar: Vueling, Ryanair y el Wizz Air que ya se usaba, con la plantilla de Ajustes (una sola vez)")
    with db.connect() as con:
        wrapped = db.list_trips(con)
        roles = [set(db.trip_legs(con, t["id"])) for t in wrapped]
        w1 = db.get_watch(con, 1)
        check(len(wrapped) == 2 and roles == [{"outbound"}, {"outbound"}] and w1["trip_id"] == wrapped[0]["id"]
              and w1["role"] == "outbound" and wrapped[0]["max_total"] is None and counts() == before,
              "0009: cada vigilancia huérfana queda envuelta en un viaje de solo ida (sin perder filas)")
        db.save_provider_script(con, "propio", {"label": "Propio", "color": "#000000", "coverage": "universal",
                                                "max_routes": None, "health_origin": "SVQ", "health_destination": "TFN",
                                                "link_template": "", "notes": "", "min_interval": 1.5,
                                                "code": "def fetch_route(*a):\n    return {}\n", "enabled": 1}, "admin")
    with db.connect() as con:
        w1 = db.get_watch(con, 1)
        snap = db.latest_snapshot(con, 1, "vueling")
        kinds_ok = {r["kind"] for r in db.list_provider_scripts(con)} == {"flight"}
    check(w1["kind"] == "flight" and kinds_ok and snap[0]["departs_at"] is None and snap[0]["origin"] == "SVQ",
          "0008: lo que había es de vuelos y los precios antiguos no tienen horas")
    c.execute("UPDATE prices SET departs_at = '2026-11-01T06:35' WHERE id = 1")
    c.commit()
    migrate("0007", down=True)
    cols = {r[1] for r in c.execute("PRAGMA table_info(prices)")}
    check(counts() == before and not cols & {"departs_at", "arrives_at"}
          and "kind" not in {r[1] for r in c.execute("PRAGMA table_info(watches)")},
          "downgrade a 0007 quita tipos y horas sin perder filas")
    migrate("head")
    check(counts() == before and c.execute("PRAGMA foreign_key_check").fetchall() == [], "y vuelta a 0008")
    migrate("0006", down=True)
    cols = {r[1] for r in c.execute("PRAGMA table_info(provider_scripts)")}
    check(counts() == before and not cols & {"source", "stealth"} and c.execute("SELECT count(*) FROM provider_scripts").fetchone()[0] == 4,
          "downgrade a 0006 quita el origen de los proveedores sin perderlos")
    migrate("0005", down=True)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    check(counts() == before and "provider_scripts" not in tables and "trips" in tables,
          "downgrade a 0005 quita los proveedores propios sin tocar lo demás")
    migrate("head")
    migrate("0004", down=True)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    check(counts() == before and not tables & {"trips", "trip_channels", "trip_quotes", "trip_alerts"},
          "downgrade a 0004 quita los viajes sin tocar lo demás")
    migrate("0003", down=True)
    check(counts() == before and dict(c.execute("SELECT id, providers FROM watches").fetchall())
          == {1: "ryanair,vueling", 2: "vueling,wizzair"}, "downgrade a 0003 recupera el CSV sin perder filas")
    db.init()
    check(counts() == before, "y vuelta a head")
    check(subprocess.run([sys.executable, "-m", "tests.migration_test", "--sin-usuarios"]).returncode == 0,
          "BD anterior a los usuarios (en otro proceso)")
    print("\nTodo correcto.")


def without_users():
    """BD en 0001 (sin usuarios ni dueño en las vigilancias) → head → bootstrap_admin."""
    migrate("0001")
    c = sqlite3.connect(config.DB_PATH)
    c.execute("INSERT INTO watches(id, name, origin, destination, providers, discount_pct, enabled, created_at) "
              "VALUES (1, 'Sevilla → Tenerife', 'SVQ', 'TCI', 'vueling', 30, 1, '2026-01-01')")
    c.commit()
    db.init()
    check(c.execute("SELECT user_id, role FROM watches").fetchall() == [(None, "outbound")]
          and c.execute("SELECT user_id, name FROM trips").fetchall() == [(None, "Sevilla → Tenerife")],
          "0001 → head: la vigilancia sin dueño pasa a un viaje de solo ida sin dueño")
    uid, _ = db.bootstrap_admin("admin", "x")
    with db.connect() as con:
        trips = db.list_trips(con, uid)
        check([t["name"] for t in trips] == ["Sevilla → Tenerife"]
              and db.trip_legs(con, trips[0]["id"])["outbound"]["user_id"] == uid,
              "bootstrap_admin da al administrador el viaje y su tramo")


if __name__ == "__main__":
    without_users() if "--sin-usuarios" in sys.argv else main()
