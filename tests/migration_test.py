"""Migraciones sobre una BD con datos: `python -m tests.migration_test`

Crea una BD SQLite en la revisión 0003 con usuarios, vigilancias (CSV de proveedores), canales, precios,
avisos y ejecuciones; aplica las migraciones pendientes como la app (`db.init`) y comprueba que no se
pierde nada (el ON DELETE CASCADE al recrear tablas en SQLite) y que los datos se convierten bien.
Después crea un viaje (0005), baja a 0003 y vuelve a subir.
"""
import os
import sqlite3
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="fw-mig-")

from alembic import command  # noqa: E402

from app import config, db  # noqa: E402

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
              "(2, 1, 'Madrid → Barcelona', 'MAD', 'BCN', 'vueling', 30, 0, '2026-01-01')")
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
    check(w2["coverage"]["vueling"]["routes"] == [("MAD", "BCN")] and w1["max_stops"] == 0 == w2["max_stops"],
          "vigilancias sin ciudades y máximo de escalas 0 (como antes)")
    with db.connect() as con:
        check(db.latest_snapshot(con, 1, "vueling")[0]["orig_price"] is None, "los precios antiguos quedan en euros")
    check(c.execute("PRAGMA foreign_key_check").fetchall() == [] and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok",
          "claves foráneas e integridad")
    with db.connect() as con:
        tid = db.create_trip(con, 1, {"name": "Viaje", "outbound_id": 1, "return_id": 2, "min_nights": 2, "max_nights": 4,
                                      "date_from": None, "date_to": None, "max_total": None, "discount_pct": 30,
                                      "enabled": True})
        check(db.get_trip(con, tid)["outbound_id"] == 1 and counts() == before, "0005: viajes sobre las vigilancias existentes")

    migrate("0004", down=True)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    check(counts() == before and not tables & {"trips", "trip_channels", "trip_quotes", "trip_alerts"},
          "downgrade a 0004 quita los viajes sin tocar lo demás")
    migrate("0003", down=True)
    check(counts() == before and dict(c.execute("SELECT id, providers FROM watches").fetchall())
          == {1: "ryanair,vueling", 2: "vueling"}, "downgrade a 0003 recupera el CSV sin perder filas")
    db.init()
    check(counts() == before, "y vuelta a head")
    print("\nTodo correcto.")


if __name__ == "__main__":
    main()
