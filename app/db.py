"""Capa de acceso a datos con SQLAlchemy Core: ajustes, vigilancias, precios, alertas y ejecuciones.

El motor se elige con DB_ENGINE (sqlite, postgres, mysql, mariadb). Las consultas devuelven dicts,
así que el resto de la app no sabe qué base de datos hay debajo.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import (
    Column, Double, ForeignKey, Index, Integer, MetaData, String, Table, Text, create_engine, delete,
    event, exists, func, insert, inspect, select, text, update,
)
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import URL, Engine

from . import config

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

# ------------------------------------------------------------------------ esquema
# Fuente de verdad del esquema actual. Cualquier cambio aquí necesita su migración en
# app/migrations/versions (alembic revision --autogenerate); `alembic check` detecta si falta.
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
BASELINE_REVISION = "0001"  # esquema de las BD creadas antes de usar Alembic

# Fechas como texto ISO (como siempre) para que comparar y ordenar funcione igual en todos los motores.
# Double y no Float: en MySQL/MariaDB FLOAT es de precisión simple (29,99 → 29,9899997).
_TABLE_OPTS = {"mysql_charset": "utf8mb4"}  # los nombres llevan «→»
ISO = String(32)
IATA = String(3)

metadata = MetaData()

settings_t = Table(
    "settings", metadata,
    Column("key", String(100), primary_key=True),
    Column("value", Text, nullable=False),
    **_TABLE_OPTS,
)

watches = Table(
    "watches", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(200), nullable=False),
    Column("origin", IATA, nullable=False),
    Column("destination", IATA, nullable=False),
    Column("providers", String(200), nullable=False, server_default="vueling"),
    Column("max_price", Double),
    Column("discount_pct", Double, nullable=False, server_default="30"),
    Column("date_from", String(10)),
    Column("date_to", String(10)),
    Column("enabled", Integer, nullable=False, server_default="1"),
    Column("created_at", ISO, nullable=False),
    **_TABLE_OPTS,
)

prices = Table(
    "prices", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("watch_id", Integer, ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),
    Column("provider", String(50), nullable=False),
    Column("flight_date", String(10), nullable=False),
    Column("price", Double, nullable=False),
    Column("currency", String(3), nullable=False, server_default="EUR"),
    Column("checked_at", ISO, nullable=False),
    Column("origin", IATA),       # aeropuerto real (NULL = el de la vigilancia)
    Column("destination", IATA),
    Index("idx_prices_snap", "watch_id", "provider", "checked_at"),
    Index("idx_prices_date", "watch_id", "provider", "flight_date"),
    **_TABLE_OPTS,
)

alerts = Table(
    "alerts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("watch_id", Integer, ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),
    Column("provider", String(50), nullable=False),
    Column("flight_date", String(10), nullable=False),
    Column("price", Double, nullable=False),
    Column("link", Text),
    Column("sent_at", ISO, nullable=False),
    Index("idx_alerts", "watch_id", "provider", "flight_date"),
    **_TABLE_OPTS,
)

runs = Table(
    "runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("watch_id", Integer, ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),
    Column("provider", String(50), nullable=False),
    Column("trigger", String(20), nullable=False),
    Column("started_at", ISO, nullable=False),
    Column("finished_at", ISO),
    Column("ok", Integer),
    Column("n_prices", Integer, nullable=False, server_default="0"),
    Column("n_deals", Integer, nullable=False, server_default="0"),
    Column("error", Text),
    **_TABLE_OPTS,
)


# ---------------------------------------------------------------------- conexión
_DRIVERS = {"postgres": "postgresql+psycopg", "mysql": "mysql+pymysql", "mariadb": "mariadb+pymysql"}


def _url() -> URL:
    if config.DB_ENGINE == "sqlite":
        return URL.create("sqlite", database=str(config.DB_PATH))
    if config.DB_ENGINE not in _DRIVERS:
        raise RuntimeError(f"DB_ENGINE desconocido: {config.DB_ENGINE!r} (sqlite, postgres, mysql o mariadb)")
    return URL.create(
        _DRIVERS[config.DB_ENGINE],
        username=config.DB_USER or None, password=config.DB_PASSWORD or None,
        host=config.DB_HOST, port=config.DB_PORT, database=config.DB_NAME,
        query={"charset": "utf8mb4"} if config.DB_ENGINE != "postgres" else {},
    )


def _make_engine() -> Engine:
    if config.DB_ENGINE == "sqlite":
        eng = create_engine(_url(), connect_args={"timeout": 30, "check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_con, _):
            dbapi_con.execute("PRAGMA foreign_keys=ON")  # sin esto no hay ON DELETE CASCADE

        return eng
    # MySQL/MariaDB cierran conexiones inactivas y la ronda corre cada varias horas: comprobar antes de usar.
    return create_engine(_url(), pool_pre_ping=True, pool_recycle=3600)


engine = _make_engine()


@contextmanager
def connect():
    """Transacción: commit al salir, rollback si hay excepción."""
    with engine.begin() as con:
        yield con


def _all(con, stmt) -> list[dict]:
    return [dict(r) for r in con.execute(stmt).mappings()]


def _one(con, stmt) -> dict | None:
    row = con.execute(stmt).mappings().first()
    return dict(row) if row else None


def _alembic_config(con) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection"] = con
    return cfg


def init():
    """Aplica las migraciones pendientes de Alembic (crea las tablas en una BD vacía)."""
    if engine.dialect.name == "sqlite":
        with engine.connect() as con:
            con.execute(text("PRAGMA journal_mode=WAL"))
    with engine.begin() as con:
        cfg = _alembic_config(con)
        tables = set(inspect(con).get_table_names())
        if "watches" in tables and "alembic_version" not in tables:
            # BD anterior a Alembic: se completa hasta el esquema de la revisión base y se marca como tal.
            cols = {c["name"] for c in inspect(con).get_columns("prices")}
            for col in ("origin", "destination"):
                if col not in cols:
                    con.execute(text(f"ALTER TABLE prices ADD COLUMN {col} VARCHAR(3)"))
            command.stamp(cfg, BASELINE_REVISION)
        command.upgrade(cfg, "head")


def seed_defaults():
    """Crea las dos vigilancias iniciales si la base de datos está vacía.

    TCI es el código de ciudad de Tenerife: se consultan Tenerife Norte (Vueling) y Sur (Ryanair).
    """
    with connect() as con:
        if con.execute(select(func.count()).select_from(watches)).scalar():
            return
        now = datetime.now().isoformat(timespec="seconds")
        con.execute(insert(watches), [
            {"name": name, "origin": o, "destination": d, "providers": "vueling,ryanair",
             "max_price": 40, "discount_pct": 30, "created_at": now}
            for name, o, d in (("Sevilla → Tenerife", "SVQ", "TCI"), ("Tenerife → Sevilla", "TCI", "SVQ"))
        ])


# --------------------------------------------------------------------- ajustes
def get_settings() -> dict:
    with connect() as con:
        stored = {r["key"]: r["value"] for r in _all(con, select(settings_t))}
    return {**DEFAULT_SETTINGS, **stored}


def _upsert_settings():
    """INSERT … ON CONFLICT en SQLite/Postgres, ON DUPLICATE KEY UPDATE en MySQL/MariaDB."""
    if engine.dialect.name in ("mysql", "mariadb"):
        stmt = mysql_insert(settings_t)
        return stmt.on_duplicate_key_update(value=stmt.inserted.value)
    stmt = (pg_insert if engine.dialect.name == "postgresql" else sqlite_insert)(settings_t)
    return stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value})


def save_settings(values: dict):
    if not values:
        return
    with connect() as con:
        con.execute(_upsert_settings(), [{"key": k, "value": str(v)} for k, v in values.items()])


# ------------------------------------------------------------------ vigilancias
def _watch(row: dict | None) -> dict | None:
    if row is None:
        return None
    row["providers"] = [p for p in row["providers"].split(",") if p]
    return row


def _watch_values(data: dict) -> dict:
    return {
        "name": data["name"], "origin": data["origin"], "destination": data["destination"],
        "providers": ",".join(data["providers"]), "max_price": data["max_price"],
        "discount_pct": data["discount_pct"], "date_from": data["date_from"], "date_to": data["date_to"],
        "enabled": int(data["enabled"]),
    }


def list_watches(con) -> list[dict]:
    return [_watch(r) for r in _all(con, select(watches).order_by(watches.c.id))]


def get_watch(con, watch_id: int) -> dict | None:
    return _watch(_one(con, select(watches).where(watches.c.id == watch_id)))


def create_watch(con, data: dict) -> int:
    values = {**_watch_values(data), "created_at": datetime.now().isoformat(timespec="seconds")}
    return con.execute(insert(watches).values(**values)).inserted_primary_key[0]


def update_watch(con, watch_id: int, data: dict):
    con.execute(update(watches).where(watches.c.id == watch_id).values(**_watch_values(data)))


def delete_watch(con, watch_id: int):
    con.execute(delete(watches).where(watches.c.id == watch_id))


def toggle_watch(con, watch_id: int):
    con.execute(update(watches).where(watches.c.id == watch_id).values(enabled=1 - watches.c.enabled))


# ----------------------------------------------------------------------- precios
def insert_prices(con, watch_id, provider, checked_at, rows):
    if not rows:
        return
    con.execute(insert(prices), [
        {"watch_id": watch_id, "provider": provider, "flight_date": r.day.isoformat(), "price": r.price,
         "currency": r.currency, "checked_at": checked_at,
         "origin": r.origin or None, "destination": r.destination or None}
        for r in rows
    ])


def latest_snapshot(con, watch_id, provider) -> list[dict]:
    p = prices.c
    last = select(func.max(p.checked_at)).where(p.watch_id == watch_id, p.provider == provider).scalar_subquery()
    return _all(con, select(p.flight_date, p.price, p.checked_at, p.origin, p.destination)
                .where(p.watch_id == watch_id, p.provider == provider, p.checked_at == last)
                .order_by(p.price, p.flight_date))


def baseline(con, watch_id, provider, before_iso, min_samples):
    """Mediana de los precios vistos antes de `before_iso` (None si hay pocas muestras)."""
    p = prices.c
    values = con.execute(
        select(p.price).where(p.watch_id == watch_id, p.provider == provider, p.checked_at < before_iso)
        .order_by(p.checked_at.desc()).limit(20000)
    ).scalars().all()
    if len(values) < min_samples:
        return None
    return median(values)


def _min_per_day(watch_id, *where):
    p = prices.c
    day = func.substr(p.checked_at, 1, 10)
    return (select(p.provider, day.label("d"), func.min(p.price).label("p"))
            .where(p.watch_id == watch_id, *where).group_by(p.provider, day).order_by(day))


def chart_min_over_time(con, watch_id):
    return _all(con, _min_per_day(watch_id))


def date_history(con, watch_id, flight_date):
    return _all(con, _min_per_day(watch_id, prices.c.flight_date == flight_date))


def checks_summary(con, watch_id, limit=60):
    p = prices.c
    return _all(con, select(p.provider, p.checked_at, func.count().label("n"),
                            func.min(p.price).label("mn"), func.avg(p.price).label("av"))
                .where(p.watch_id == watch_id).group_by(p.provider, p.checked_at)
                .order_by(p.checked_at.desc()).limit(limit))


# ----------------------------------------------------------------------- alertas
def already_alerted(con, watch_id, provider, flight_date, price) -> bool:
    a = alerts.c
    return con.execute(select(exists().where(
        a.watch_id == watch_id, a.provider == provider, a.flight_date == flight_date, a.price <= price,
    ))).scalar()


def add_alerts(con, watch_id, deals, sent_at):
    if not deals:
        return
    con.execute(insert(alerts), [
        {"watch_id": watch_id, "provider": d["provider"], "flight_date": d["day"].isoformat(),
         "price": d["price"], "link": d["link"], "sent_at": sent_at}
        for d in deals
    ])


def list_alerts(con, limit=10, watch_id=None):
    stmt = select(alerts, watches.c.name.label("watch_name")).join(watches, watches.c.id == alerts.c.watch_id)
    if watch_id is not None:
        stmt = stmt.where(alerts.c.watch_id == watch_id)
    return _all(con, stmt.order_by(alerts.c.sent_at.desc(), alerts.c.id.desc()).limit(limit))


# ------------------------------------------------------------------ ejecuciones
def start_run(con, watch_id, provider, trigger, started_at) -> int:
    return con.execute(insert(runs).values(
        watch_id=watch_id, provider=provider, trigger=trigger, started_at=started_at,
    )).inserted_primary_key[0]


def finish_run(con, run_id, finished_at, ok, n_prices, n_deals, error):
    con.execute(update(runs).where(runs.c.id == run_id).values(
        finished_at=finished_at, ok=int(ok), n_prices=n_prices, n_deals=n_deals, error=error,
    ))


def last_run(con, watch_id, provider):
    r = runs.c
    return _one(con, select(runs).where(r.watch_id == watch_id, r.provider == provider, r.finished_at.is_not(None))
                .order_by(r.id.desc()).limit(1))


def list_runs(con, limit=50):
    return _all(con, select(runs, watches.c.name.label("watch_name"))
                .join(watches, watches.c.id == runs.c.watch_id).order_by(runs.c.id.desc()).limit(limit))


def purge(con, retention_days: int):
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat(timespec="seconds")
    con.execute(delete(prices).where(prices.c.checked_at < cutoff))
    con.execute(delete(runs).where(runs.c.started_at < cutoff))
    con.execute(delete(alerts).where(alerts.c.sent_at < cutoff))
