"""Capa de acceso a SQLite: ajustes, vigilancias, precios, alertas y ejecuciones."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from statistics import median

from .config import DB_PATH

DEFAULT_SETTINGS = {
    "schedule_hours": "8",
    "schedule_minute": "0",
    "timezone": "Europe/Madrid",
    "max_months": "11",
    "min_samples": "30",
    "retention_days": "400",
    "headless": "1",
    "debug": "0",
    "proxy_url": "",
    "discord_webhook": "",
    "telegram_token": "",
    "telegram_chat_id": "",
    "panel_url": "",
    "notify_errors": "1",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    providers TEXT NOT NULL DEFAULT 'vueling',
    max_price REAL,
    discount_pct REAL NOT NULL DEFAULT 30,
    date_from TEXT,
    date_to TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    flight_date TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    checked_at TEXT NOT NULL,
    origin TEXT,        -- aeropuerto real (NULL = el de la vigilancia)
    destination TEXT
);
CREATE INDEX IF NOT EXISTS idx_prices_snap ON prices(watch_id, provider, checked_at);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(watch_id, provider, flight_date);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    flight_date TEXT NOT NULL,
    price REAL NOT NULL,
    link TEXT,
    sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts ON alerts(watch_id, provider, flight_date);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    trigger TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    n_prices INTEGER NOT NULL DEFAULT 0,
    n_deals INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
"""


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init():
    with connect() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
        # Migración de bases creadas antes de guardar el aeropuerto real (códigos de ciudad).
        cols = {r["name"] for r in con.execute("PRAGMA table_info(prices)")}
        for col in ("origin", "destination"):
            if col not in cols:
                con.execute(f"ALTER TABLE prices ADD COLUMN {col} TEXT")


def seed_defaults():
    """Crea las dos vigilancias iniciales si la base de datos está vacía.

    TCI es el código de ciudad de Tenerife: se consultan Tenerife Norte (Vueling) y Sur (Ryanair).
    """
    with connect() as con:
        if con.execute("SELECT COUNT(*) FROM watches").fetchone()[0]:
            return
        now = datetime.now().isoformat(timespec="seconds")
        for name, o, d in (
            ("Sevilla → Tenerife", "SVQ", "TCI"),
            ("Tenerife → Sevilla", "TCI", "SVQ"),
        ):
            con.execute(
                "INSERT INTO watches (name, origin, destination, providers, max_price,"
                " discount_pct, created_at) VALUES (?,?,?,?,?,?,?)",
                (name, o, d, "vueling,ryanair", 40, 30, now),
            )


# --------------------------------------------------------------------- ajustes
def get_settings() -> dict:
    with connect() as con:
        stored = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM settings")}
    return {**DEFAULT_SETTINGS, **stored}


def save_settings(values: dict):
    with connect() as con:
        con.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [(k, str(v)) for k, v in values.items()],
        )


# ------------------------------------------------------------------ vigilancias
def _watch(row) -> dict | None:
    if row is None:
        return None
    w = dict(row)
    w["providers"] = [p for p in w["providers"].split(",") if p]
    return w


def list_watches(con) -> list[dict]:
    return [_watch(r) for r in con.execute("SELECT * FROM watches ORDER BY id")]


def get_watch(con, watch_id: int) -> dict | None:
    return _watch(con.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone())


def create_watch(con, data: dict) -> int:
    cur = con.execute(
        "INSERT INTO watches (name, origin, destination, providers, max_price, discount_pct,"
        " date_from, date_to, enabled, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            data["name"], data["origin"], data["destination"], ",".join(data["providers"]),
            data["max_price"], data["discount_pct"], data["date_from"], data["date_to"],
            int(data["enabled"]), datetime.now().isoformat(timespec="seconds"),
        ),
    )
    return cur.lastrowid


def update_watch(con, watch_id: int, data: dict):
    con.execute(
        "UPDATE watches SET name=?, origin=?, destination=?, providers=?, max_price=?,"
        " discount_pct=?, date_from=?, date_to=?, enabled=? WHERE id=?",
        (
            data["name"], data["origin"], data["destination"], ",".join(data["providers"]),
            data["max_price"], data["discount_pct"], data["date_from"], data["date_to"],
            int(data["enabled"]), watch_id,
        ),
    )


def delete_watch(con, watch_id: int):
    con.execute("DELETE FROM watches WHERE id=?", (watch_id,))


def toggle_watch(con, watch_id: int):
    con.execute("UPDATE watches SET enabled = 1 - enabled WHERE id=?", (watch_id,))


# ----------------------------------------------------------------------- precios
def insert_prices(con, watch_id, provider, checked_at, rows):
    con.executemany(
        "INSERT INTO prices (watch_id, provider, flight_date, price, currency, checked_at, origin, destination)"
        " VALUES (?,?,?,?,?,?,?,?)",
        [(watch_id, provider, r.day.isoformat(), r.price, r.currency, checked_at,
          r.origin or None, r.destination or None) for r in rows],
    )


def latest_snapshot(con, watch_id, provider) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT flight_date, price, checked_at, origin, destination FROM prices"
        " WHERE watch_id=? AND provider=? AND checked_at ="
        "   (SELECT MAX(checked_at) FROM prices WHERE watch_id=? AND provider=?)"
        " ORDER BY price, flight_date",
        (watch_id, provider, watch_id, provider),
    ).fetchall()


def baseline(con, watch_id, provider, before_iso, min_samples):
    """Mediana de los precios vistos antes de `before_iso` (None si hay pocas muestras)."""
    rows = con.execute(
        "SELECT price FROM prices WHERE watch_id=? AND provider=? AND checked_at < ?"
        " ORDER BY checked_at DESC LIMIT 20000",
        (watch_id, provider, before_iso),
    ).fetchall()
    if len(rows) < min_samples:
        return None
    return median(r["price"] for r in rows)


def chart_min_over_time(con, watch_id):
    return con.execute(
        "SELECT provider, substr(checked_at,1,10) AS d, MIN(price) AS p FROM prices"
        " WHERE watch_id=? GROUP BY provider, d ORDER BY d",
        (watch_id,),
    ).fetchall()


def date_history(con, watch_id, flight_date):
    return con.execute(
        "SELECT provider, substr(checked_at,1,10) AS d, MIN(price) AS p FROM prices"
        " WHERE watch_id=? AND flight_date=? GROUP BY provider, d ORDER BY d",
        (watch_id, flight_date),
    ).fetchall()


def checks_summary(con, watch_id, limit=60):
    return con.execute(
        "SELECT provider, checked_at, COUNT(*) AS n, MIN(price) AS mn, AVG(price) AS av"
        " FROM prices WHERE watch_id=? GROUP BY provider, checked_at"
        " ORDER BY checked_at DESC LIMIT ?",
        (watch_id, limit),
    ).fetchall()


# ----------------------------------------------------------------------- alertas
def already_alerted(con, watch_id, provider, flight_date, price) -> bool:
    return con.execute(
        "SELECT 1 FROM alerts WHERE watch_id=? AND provider=? AND flight_date=? AND price<=?",
        (watch_id, provider, flight_date, price),
    ).fetchone() is not None


def add_alerts(con, watch_id, deals, sent_at):
    con.executemany(
        "INSERT INTO alerts (watch_id, provider, flight_date, price, link, sent_at)"
        " VALUES (?,?,?,?,?,?)",
        [(watch_id, d["provider"], d["day"].isoformat(), d["price"], d["link"], sent_at) for d in deals],
    )


def list_alerts(con, limit=10, watch_id=None):
    sql = "SELECT a.*, w.name AS watch_name FROM alerts a JOIN watches w ON w.id=a.watch_id"
    args: tuple = ()
    if watch_id is not None:
        sql += " WHERE a.watch_id=?"
        args = (watch_id,)
    return con.execute(sql + " ORDER BY a.sent_at DESC, a.id DESC LIMIT ?", (*args, limit)).fetchall()


# ------------------------------------------------------------------ ejecuciones
def start_run(con, watch_id, provider, trigger, started_at) -> int:
    return con.execute(
        "INSERT INTO runs (watch_id, provider, trigger, started_at) VALUES (?,?,?,?)",
        (watch_id, provider, trigger, started_at),
    ).lastrowid


def finish_run(con, run_id, finished_at, ok, n_prices, n_deals, error):
    con.execute(
        "UPDATE runs SET finished_at=?, ok=?, n_prices=?, n_deals=?, error=? WHERE id=?",
        (finished_at, int(ok), n_prices, n_deals, error, run_id),
    )


def last_run(con, watch_id, provider):
    return con.execute(
        "SELECT * FROM runs WHERE watch_id=? AND provider=? AND finished_at IS NOT NULL"
        " ORDER BY id DESC LIMIT 1",
        (watch_id, provider),
    ).fetchone()


def list_runs(con, limit=50):
    return con.execute(
        "SELECT r.*, w.name AS watch_name FROM runs r JOIN watches w ON w.id=r.watch_id"
        " ORDER BY r.id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def purge(con, retention_days: int):
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat(timespec="seconds")
    con.execute("DELETE FROM prices WHERE checked_at < ?", (cutoff,))
    con.execute("DELETE FROM runs WHERE started_at < ?", (cutoff,))
    con.execute("DELETE FROM alerts WHERE sent_at < ?", (cutoff,))
