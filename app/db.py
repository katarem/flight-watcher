"""Capa de acceso a datos con SQLAlchemy Core: ajustes, vigilancias, viajes, precios, alertas y ejecuciones.

El motor se elige con DB_ENGINE (sqlite, postgres, mysql, mariadb). Las consultas devuelven dicts,
así que el resto de la app no sabe qué base de datos hay debajo.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
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

from . import config, places

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
    "panel_url": "",
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
PLACE = String(places.CODE_MAX)  # aeropuerto, ciudad, país o grupo (ver app/places.py)

metadata = MetaData()

settings_t = Table(
    "settings", metadata,
    Column("key", String(100), primary_key=True),
    Column("value", Text, nullable=False),
    **_TABLE_OPTS,
)

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(50), nullable=False),  # siempre en minúsculas
    Column("display_name", String(100), nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(10), nullable=False, server_default="user"),  # admin | user
    Column("enabled", Integer, nullable=False, server_default="1"),
    Column("avatar", String(100)),  # archivo en DATA_DIR/avatars (NULL = iniciales)
    Column("notify_errors", Integer, nullable=False, server_default="1"),
    Column("created_at", ISO, nullable=False),
    Index("ux_users_username", "username", unique=True),
    **_TABLE_OPTS,
)

# Canales de aviso de un usuario (Discord, Telegram…). `config` es JSON con los campos del tipo
# (ver notify.KINDS); contiene secretos y nunca se devuelve al navegador.
channels = Table(
    "channels", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String(20), nullable=False),
    Column("name", String(100), nullable=False),
    Column("config", Text, nullable=False),
    Column("enabled", Integer, nullable=False, server_default="1"),
    Column("created_at", ISO, nullable=False),
    Index("idx_channels_user", "user_id"),
    **_TABLE_OPTS,
)

watches = Table(
    "watches", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # Nullable solo por las BD anteriores a los usuarios: bootstrap_admin() las asigna al administrador.
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE", name="fk_watches_user_id")),
    Column("name", String(200), nullable=False),
    Column("origin", PLACE, nullable=False),
    Column("destination", PLACE, nullable=False),
    Column("max_price", Double),
    Column("discount_pct", Double, nullable=False, server_default="30"),
    Column("date_from", String(10)),
    Column("date_to", String(10)),
    Column("max_stops", Integer),  # escalas como máximo (0 = solo directos, NULL = sin límite)
    Column("enabled", Integer, nullable=False, server_default="1"),
    Column("created_at", ISO, nullable=False),
    Index("idx_watches_user", "user_id"),
    **_TABLE_OPTS,
)

# Proveedores de cada vigilancia con su cobertura: pares de aeropuertos reales que opera
# (JSON ["SVQ-TFN", …]), si está activo (opera alguno ahora) y cuándo se comprobó (NULL = nunca).
watch_providers = Table(
    "watch_providers", metadata,
    Column("watch_id", Integer, ForeignKey("watches.id", ondelete="CASCADE"), primary_key=True),
    Column("provider", String(50), primary_key=True),
    Column("routes", Text, nullable=False),
    Column("active", Integer, nullable=False, server_default="1"),
    Column("checked_at", ISO),
    **_TABLE_OPTS,
)

# Caché de cobertura: si un proveedor opera un par de aeropuertos (red publicada o pregunta directa).
provider_routes = Table(
    "provider_routes", metadata,
    Column("provider", String(50), primary_key=True),
    Column("origin", IATA, primary_key=True),
    Column("destination", IATA, primary_key=True),
    Column("operated", Integer, nullable=False),
    Column("checked_at", ISO, nullable=False),
    **_TABLE_OPTS,
)

# Último resultado de la comprobación de acceso de cada proveedor (zona «Proveedores» del admin).
provider_health = Table(
    "provider_health", metadata,
    Column("provider", String(50), primary_key=True),
    Column("status", String(20), nullable=False),  # ok | empty | blocked | error | timeout
    Column("detail", Text, nullable=False),  # JSON con los pasos
    Column("latency_ms", Integer, nullable=False, server_default="0"),
    Column("checked_at", ISO, nullable=False),
    **_TABLE_OPTS,
)

# Proveedores propios: un script de Python escrito desde el panel (solo administradores) que cumple el
# contrato de `app/providers/scripted.py`. La clave no cambia nunca (la usan precios, avisos y vigilancias).
provider_scripts = Table(
    "provider_scripts", metadata,
    Column("key", String(50), primary_key=True),
    Column("label", String(100), nullable=False),
    Column("color", String(7), nullable=False),
    Column("coverage", String(20), nullable=False),  # network | probe | universal
    Column("max_routes", Integer),
    Column("health_origin", IATA, nullable=False),
    Column("health_destination", IATA, nullable=False),
    Column("link_template", Text, nullable=False),
    Column("notes", Text, nullable=False),
    Column("min_interval", Double, nullable=False, server_default="1.5"),
    Column("code", Text, nullable=False),
    Column("enabled", Integer, nullable=False, server_default="1"),
    Column("created_at", ISO, nullable=False),
    Column("updated_at", ISO, nullable=False),
    Column("updated_by", String(32), nullable=False),  # usuario que lo guardó por última vez
    **_TABLE_OPTS,
)

# Qué canales avisan por cada vigilancia (solo del dueño de la vigilancia).
watch_channels = Table(
    "watch_channels", metadata,
    Column("watch_id", Integer, ForeignKey("watches.id", ondelete="CASCADE"), primary_key=True),
    Column("channel_id", Integer, ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True),
    **_TABLE_OPTS,
)

prices = Table(
    "prices", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("watch_id", Integer, ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),
    Column("provider", String(50), nullable=False),
    Column("flight_date", String(10), nullable=False),
    Column("price", Double, nullable=False),  # en euros (convertido con el cambio del BCE)
    Column("currency", String(3), nullable=False, server_default="EUR"),  # moneda original
    Column("checked_at", ISO, nullable=False),
    Column("origin", IATA),       # aeropuerto real (NULL = el de la vigilancia)
    Column("destination", IATA),
    Column("orig_price", Double),  # precio en la moneda original (NULL = el mismo en euros)
    Column("stops", Integer),      # escalas (NULL = datos antiguos, directos)
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

# Viajes: ida y vuelta formados por dos vigilancias del mismo usuario (sus tramos). El precio de un viaje
# es la suma del más barato de cada tramo para cada fecha de ida y cada número de noches permitido.
trips = Table(
    "trips", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(200), nullable=False),
    Column("outbound_id", Integer, ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),  # vigilancia de ida
    Column("return_id", Integer, ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),    # vigilancia de vuelta
    Column("min_nights", Integer, nullable=False),
    Column("max_nights", Integer, nullable=False),
    Column("date_from", String(10)),  # ventana de fechas de ida (NULL = sin límite)
    Column("date_to", String(10)),
    Column("max_total", Double),      # precio total máximo (ida + vuelta, en euros)
    Column("discount_pct", Double, nullable=False, server_default="30"),
    Column("enabled", Integer, nullable=False, server_default="1"),
    Column("created_at", ISO, nullable=False),
    Index("idx_trips_user", "user_id"),
    **_TABLE_OPTS,
)

trip_channels = Table(
    "trip_channels", metadata,
    Column("trip_id", Integer, ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True),
    Column("channel_id", Integer, ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True),
    **_TABLE_OPTS,
)

# Histórico de un viaje: en cada comprobación, la combinación más barata de cada fecha de ida (en euros).
trip_quotes = Table(
    "trip_quotes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("trip_id", Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
    Column("checked_at", ISO, nullable=False),
    Column("out_date", String(10), nullable=False),
    Column("ret_date", String(10), nullable=False),
    Column("total", Double, nullable=False),
    Column("out_price", Double, nullable=False),
    Column("ret_price", Double, nullable=False),
    Index("idx_trip_quotes", "trip_id", "checked_at"),
    **_TABLE_OPTS,
)

trip_alerts = Table(
    "trip_alerts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("trip_id", Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
    Column("out_date", String(10), nullable=False),
    Column("ret_date", String(10), nullable=False),
    Column("total", Double, nullable=False),
    Column("sent_at", ISO, nullable=False),
    Index("idx_trip_alerts", "trip_id", "out_date"),
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
    sqlite = engine.dialect.name == "sqlite"
    if sqlite:
        with engine.connect() as con:
            con.execute(text("PRAGMA journal_mode=WAL"))
    with engine.connect() as con:
        if sqlite:
            # Alembic cambia columnas de SQLite recreando la tabla (DROP + copia): con las claves foráneas
            # activas, el ON DELETE CASCADE borraría los datos hijos (vigilancias, precios…).
            # El PRAGMA solo vale fuera de una transacción.
            con.exec_driver_sql("PRAGMA foreign_keys=OFF")
            con.commit()
        try:
            with con.begin():
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
        finally:
            if sqlite:
                con.exec_driver_sql("PRAGMA foreign_keys=ON")
                con.commit()


def seed_defaults(user_id: int):
    """Crea las dos vigilancias iniciales (del usuario dado) si la base de datos no tiene ninguna.

    TCI es el código de ciudad de Tenerife: se consultan Tenerife Norte (Vueling) y Sur (Ryanair).
    """
    with connect() as con:
        if con.execute(select(func.count()).select_from(watches)).scalar():
            return
        for name, o, d in (("Sevilla → Tenerife", "SVQ", "TCI"), ("Tenerife → Sevilla", "TCI", "SVQ")):
            create_watch(con, user_id, {
                "name": name, "origin": o, "destination": d, "providers": ["vueling", "ryanair"], "max_price": 40,
                "discount_pct": 30, "date_from": None, "date_to": None, "max_stops": 0, "enabled": True,
            })


# --------------------------------------------------------------------- usuarios
def list_users(con) -> list[dict]:
    return _all(con, select(users).order_by(users.c.id))


def get_user(con, user_id: int) -> dict | None:
    return _one(con, select(users).where(users.c.id == user_id))


def get_user_by_username(con, username: str) -> dict | None:
    return _one(con, select(users).where(users.c.username == username))


def create_user(con, username, display_name, password_hash, role="user", enabled=True) -> int:
    return con.execute(insert(users).values(
        username=username, display_name=display_name, password_hash=password_hash, role=role,
        enabled=int(enabled), created_at=datetime.now().isoformat(timespec="seconds"),
    )).inserted_primary_key[0]


def update_user(con, user_id: int, **values):
    if "enabled" in values:
        values["enabled"] = int(values["enabled"])
    if "notify_errors" in values:
        values["notify_errors"] = int(values["notify_errors"])
    con.execute(update(users).where(users.c.id == user_id).values(**values))


def delete_user(con, user_id: int):
    """Borra también sus vigilancias (y con ellas precios, avisos y ejecuciones) por ON DELETE CASCADE."""
    con.execute(delete(users).where(users.c.id == user_id))


def count_admins(con, exclude_id: int | None = None) -> int:
    """Administradores activos (opcionalmente sin contar a uno): sirve para no dejar el panel sin admin."""
    stmt = select(func.count()).select_from(users).where(users.c.role == "admin", users.c.enabled == 1)
    if exclude_id is not None:
        stmt = stmt.where(users.c.id != exclude_id)
    return con.execute(stmt).scalar()


def watch_counts(con) -> dict[int, int]:
    rows = con.execute(select(watches.c.user_id, func.count()).group_by(watches.c.user_id)).all()
    return {uid: n for uid, n in rows}


def bootstrap_admin(username: str, password_hash: str) -> tuple[int, bool]:
    """Garantiza que hay un administrador. Devuelve (id, creado_ahora).

    Si la BD es anterior a los usuarios, el nuevo administrador hereda las vigilancias huérfanas y los
    canales de aviso que antes eran ajustes globales (que se borran de `settings`).
    """
    with connect() as con:
        admin = _one(con, select(users).where(users.c.role == "admin").order_by(users.c.id).limit(1))
        created = admin is None
        if created:
            uid = create_user(con, username, username.capitalize(), password_hash, role="admin")
            admin = get_user(con, uid)
        con.execute(update(watches).where(watches.c.user_id.is_(None)).values(user_id=admin["id"]))
        legacy = {r["key"]: r["value"] for r in _all(con, select(settings_t))}
        old_keys = ("discord_webhook", "telegram_token", "telegram_chat_id", "notify_errors")
        moved = {k: legacy[k] for k in old_keys if k in legacy}
        if moved:
            if not list_channels(con, admin["id"]):
                if moved.get("discord_webhook"):
                    create_channel(con, admin["id"], "discord", "Discord", {"webhook": moved["discord_webhook"]})
                if moved.get("telegram_token") and moved.get("telegram_chat_id"):
                    create_channel(con, admin["id"], "telegram", "Telegram",
                                   {"token": moved["telegram_token"], "chat_id": moved["telegram_chat_id"]})
                ids = [c["id"] for c in list_channels(con, admin["id"])]
                for w in list_watches(con, admin["id"]):
                    set_watch_channels(con, w["id"], ids)
            if "notify_errors" in moved:
                update_user(con, admin["id"], notify_errors=moved["notify_errors"] == "1")
            con.execute(delete(settings_t).where(settings_t.c.key.in_(list(moved))))
        return admin["id"], created


# ---------------------------------------------------------------------- canales
def _channel(row: dict) -> dict:
    row["config"] = json.loads(row["config"])
    return row


def list_channels(con, user_id: int, only_enabled: bool = False) -> list[dict]:
    stmt = select(channels).where(channels.c.user_id == user_id).order_by(channels.c.id)
    if only_enabled:
        stmt = stmt.where(channels.c.enabled == 1)
    return [_channel(r) for r in _all(con, stmt)]


def get_channel(con, channel_id: int) -> dict | None:
    row = _one(con, select(channels).where(channels.c.id == channel_id))
    return _channel(row) if row else None


def create_channel(con, user_id: int, kind: str, name: str, config: dict, enabled: bool = True) -> int:
    return con.execute(insert(channels).values(
        user_id=user_id, kind=kind, name=name, config=json.dumps(config), enabled=int(enabled),
        created_at=datetime.now().isoformat(timespec="seconds"),
    )).inserted_primary_key[0]


def update_channel(con, channel_id: int, name: str, config: dict, enabled: bool):
    con.execute(update(channels).where(channels.c.id == channel_id)
                .values(name=name, config=json.dumps(config), enabled=int(enabled)))


def delete_channel(con, channel_id: int):
    con.execute(delete(channels).where(channels.c.id == channel_id))


def channel_counts(con) -> dict[int, int]:
    return {uid: n for uid, n in con.execute(select(channels.c.user_id, func.count()).group_by(channels.c.user_id)).all()}


def set_watch_channels(con, watch_id: int, channel_ids: list[int]):
    """Sustituye los canales de la vigilancia. El llamador garantiza que son del dueño."""
    con.execute(delete(watch_channels).where(watch_channels.c.watch_id == watch_id))
    if channel_ids:
        con.execute(insert(watch_channels), [{"watch_id": watch_id, "channel_id": c} for c in sorted(set(channel_ids))])


def _with_channel_ids(con, ws: list[dict]) -> list[dict]:
    ids: dict[int, list[int]] = {}
    if not ws:
        return ws
    for wid, cid in con.execute(select(watch_channels.c.watch_id, watch_channels.c.channel_id)
                                .where(watch_channels.c.watch_id.in_([w["id"] for w in ws]))
                                .order_by(watch_channels.c.channel_id)).all():
        ids.setdefault(wid, []).append(cid)
    for w in ws:
        w["channel_ids"] = ids.get(w["id"], [])
    return ws


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
def _watch_values(data: dict) -> dict:
    return {
        "name": data["name"], "origin": data["origin"], "destination": data["destination"],
        "max_price": data["max_price"], "discount_pct": data["discount_pct"], "date_from": data["date_from"],
        "date_to": data["date_to"], "max_stops": data.get("max_stops"), "enabled": int(data["enabled"]),
    }


def pair_key(pair) -> str:
    return f"{pair[0]}-{pair[1]}"


def parse_pair(key: str) -> tuple[str, str]:
    o, d = key.split("-", 1)
    return o, d


def default_coverage(origin: str, destination: str, keys) -> dict[str, dict]:
    """Cobertura sin comprobar: todos los pares de aeropuertos del origen y el destino."""
    pairs = places.routes(origin, destination)
    return {k: {"routes": pairs, "active": True, "checked_at": None} for k in keys}


def _with_extras(con, ws: list[dict]) -> list[dict]:
    """Añade a cada vigilancia `channel_ids`, `providers` (claves) y `coverage` (por proveedor)."""
    if not ws:
        return ws
    _with_channel_ids(con, ws)
    rows = _all(con, select(watch_providers).where(watch_providers.c.watch_id.in_([w["id"] for w in ws]))
                .order_by(watch_providers.c.provider))
    cov: dict[int, dict] = {}
    for r in rows:
        cov.setdefault(r["watch_id"], {})[r["provider"]] = {
            "routes": [parse_pair(p) for p in json.loads(r["routes"])], "active": bool(r["active"]),
            "checked_at": r["checked_at"],
        }
    for w in ws:
        w["coverage"] = cov.get(w["id"], {})
        w["providers"] = list(w["coverage"])
    return ws


def list_watches(con, user_id: int | None = None) -> list[dict]:
    stmt = select(watches).order_by(watches.c.id)
    if user_id is not None:
        stmt = stmt.where(watches.c.user_id == user_id)
    return _with_extras(con, _all(con, stmt))


def get_watch(con, watch_id: int) -> dict | None:
    w = _one(con, select(watches).where(watches.c.id == watch_id))
    return _with_extras(con, [w])[0] if w else None


def set_watch_providers(con, watch_id: int, coverage: dict[str, dict]):
    """Sustituye los proveedores de la vigilancia: {clave: {"routes": [(o, d)], "active", "checked_at"}}."""
    con.execute(delete(watch_providers).where(watch_providers.c.watch_id == watch_id))
    if coverage:
        con.execute(insert(watch_providers), [
            {"watch_id": watch_id, "provider": k, "routes": json.dumps([pair_key(p) for p in c["routes"]]),
             "active": int(c["active"]), "checked_at": c["checked_at"]}
            for k, c in coverage.items()
        ])


def update_watch_provider(con, watch_id: int, provider: str, routes, active: bool, checked_at: str | None):
    con.execute(update(watch_providers)
                .where(watch_providers.c.watch_id == watch_id, watch_providers.c.provider == provider)
                .values(routes=json.dumps([pair_key(p) for p in routes]), active=int(active), checked_at=checked_at))


def _coverage_of(data: dict) -> dict[str, dict]:
    return data.get("coverage") or default_coverage(data["origin"], data["destination"], data.get("providers", []))


def create_watch(con, user_id: int, data: dict) -> int:
    """`data["coverage"]` con la cobertura comprobada o, si falta, `data["providers"]` (sin comprobar)."""
    values = {**_watch_values(data), "user_id": user_id, "created_at": datetime.now().isoformat(timespec="seconds")}
    wid = con.execute(insert(watches).values(**values)).inserted_primary_key[0]
    set_watch_providers(con, wid, _coverage_of(data))
    return wid


def update_watch(con, watch_id: int, data: dict):
    con.execute(update(watches).where(watches.c.id == watch_id).values(**_watch_values(data)))
    set_watch_providers(con, watch_id, _coverage_of(data))


def delete_watch(con, watch_id: int):
    con.execute(delete(watches).where(watches.c.id == watch_id))


def toggle_watch(con, watch_id: int):
    con.execute(update(watches).where(watches.c.id == watch_id).values(enabled=1 - watches.c.enabled))


# ----------------------------------------------------------------------- precios
def insert_prices(con, watch_id, provider, checked_at, rows):
    """Filas `DayPrice`; `price_eur` (si lo tienen) es el precio en euros y `price` el de su moneda."""
    if not rows:
        return
    con.execute(insert(prices), [
        {"watch_id": watch_id, "provider": provider, "flight_date": r.day.isoformat(),
         "price": getattr(r, "price_eur", None) or r.price, "currency": r.currency, "checked_at": checked_at,
         "orig_price": r.price if r.currency != "EUR" else None, "stops": getattr(r, "stops", 0),
         "origin": r.origin or None, "destination": r.destination or None}
        for r in rows
    ])


def latest_snapshot(con, watch_id, provider) -> list[dict]:
    p = prices.c
    last = select(func.max(p.checked_at)).where(p.watch_id == watch_id, p.provider == provider).scalar_subquery()
    return _all(con, select(p.flight_date, p.price, p.checked_at, p.origin, p.destination, p.currency, p.orig_price,
                            p.stops)
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


def list_alerts(con, limit=10, watch_id=None, user_id=None):
    stmt = select(alerts, watches.c.name.label("watch_name")).join(watches, watches.c.id == alerts.c.watch_id)
    if watch_id is not None:
        stmt = stmt.where(alerts.c.watch_id == watch_id)
    if user_id is not None:
        stmt = stmt.where(watches.c.user_id == user_id)
    return _all(con, stmt.order_by(alerts.c.sent_at.desc(), alerts.c.id.desc()).limit(limit))


# ------------------------------------------------------------------------ viajes
def _trip_values(data: dict) -> dict:
    return {k: data[k] for k in ("name", "outbound_id", "return_id", "min_nights", "max_nights", "date_from",
                                 "date_to", "max_total", "discount_pct")} | {"enabled": int(data["enabled"])}


def _with_trip_channels(con, ts: list[dict]) -> list[dict]:
    ids: dict[int, list[int]] = {}
    if ts:
        for tid, cid in con.execute(select(trip_channels.c.trip_id, trip_channels.c.channel_id)
                                    .where(trip_channels.c.trip_id.in_([t["id"] for t in ts]))
                                    .order_by(trip_channels.c.channel_id)).all():
            ids.setdefault(tid, []).append(cid)
    for t in ts:
        t["channel_ids"] = ids.get(t["id"], [])
    return ts


def list_trips(con, user_id: int | None = None, watch_id: int | None = None) -> list[dict]:
    """Viajes (de un usuario y/o que usan una vigilancia como tramo) con `channel_ids`."""
    stmt = select(trips).order_by(trips.c.id)
    if user_id is not None:
        stmt = stmt.where(trips.c.user_id == user_id)
    if watch_id is not None:
        stmt = stmt.where((trips.c.outbound_id == watch_id) | (trips.c.return_id == watch_id))
    return _with_trip_channels(con, _all(con, stmt))


def get_trip(con, trip_id: int) -> dict | None:
    t = _one(con, select(trips).where(trips.c.id == trip_id))
    return _with_trip_channels(con, [t])[0] if t else None


def create_trip(con, user_id: int, data: dict) -> int:
    return con.execute(insert(trips).values(
        **_trip_values(data), user_id=user_id, created_at=datetime.now().isoformat(timespec="seconds"),
    )).inserted_primary_key[0]


def update_trip(con, trip_id: int, data: dict):
    con.execute(update(trips).where(trips.c.id == trip_id).values(**_trip_values(data)))


def delete_trip(con, trip_id: int):
    con.execute(delete(trips).where(trips.c.id == trip_id))


def toggle_trip(con, trip_id: int):
    con.execute(update(trips).where(trips.c.id == trip_id).values(enabled=1 - trips.c.enabled))


def set_trip_channels(con, trip_id: int, channel_ids: list[int]):
    """Sustituye los canales del viaje. El llamador garantiza que son del dueño."""
    con.execute(delete(trip_channels).where(trip_channels.c.trip_id == trip_id))
    if channel_ids:
        con.execute(insert(trip_channels), [{"trip_id": trip_id, "channel_id": c} for c in sorted(set(channel_ids))])


def insert_trip_quotes(con, trip_id: int, checked_at: str, quotes: list[dict]):
    if quotes:
        con.execute(insert(trip_quotes), [
            {"trip_id": trip_id, "checked_at": checked_at, "out_date": q["out_date"], "ret_date": q["ret_date"],
             "total": q["total"], "out_price": q["out"]["price"], "ret_price": q["ret"]["price"]}
            for q in quotes
        ])


def trip_baseline(con, trip_id: int, before_iso: str, min_samples: int) -> float | None:
    """Mediana de los totales guardados antes de `before_iso` (None si hay pocas muestras)."""
    q = trip_quotes.c
    values = con.execute(select(q.total).where(q.trip_id == trip_id, q.checked_at < before_iso)
                         .order_by(q.checked_at.desc()).limit(20000)).scalars().all()
    return median(values) if len(values) >= min_samples else None


def trip_trend(con, trip_id: int) -> list[dict]:
    """Total más barato de cada día de comprobación: [{"d", "p"}]."""
    q = trip_quotes.c
    day = func.substr(q.checked_at, 1, 10)
    return _all(con, select(day.label("d"), func.min(q.total).label("p"))
                .where(q.trip_id == trip_id).group_by(day).order_by(day))


def trip_already_alerted(con, trip_id: int, out_date: str, total: float) -> bool:
    """Ya se avisó de esa fecha de ida por un total igual o menor (sea cual sea la vuelta)."""
    a = trip_alerts.c
    return con.execute(select(exists().where(a.trip_id == trip_id, a.out_date == out_date, a.total <= total))).scalar()


def add_trip_alerts(con, trip_id: int, quotes: list[dict], sent_at: str):
    if quotes:
        con.execute(insert(trip_alerts), [
            {"trip_id": trip_id, "out_date": q["out_date"], "ret_date": q["ret_date"], "total": q["total"],
             "sent_at": sent_at} for q in quotes
        ])


def list_trip_alerts(con, trip_id: int, limit: int = 15) -> list[dict]:
    a = trip_alerts.c
    return _all(con, select(trip_alerts).where(a.trip_id == trip_id).order_by(a.sent_at.desc(), a.id.desc()).limit(limit))


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


def list_runs(con, limit=50, user_id=None):
    stmt = select(runs, watches.c.name.label("watch_name")).join(watches, watches.c.id == runs.c.watch_id)
    if user_id is not None:
        stmt = stmt.where(watches.c.user_id == user_id)
    return _all(con, stmt.order_by(runs.c.id.desc()).limit(limit))


def purge(con, retention_days: int):
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat(timespec="seconds")
    con.execute(delete(prices).where(prices.c.checked_at < cutoff))
    con.execute(delete(runs).where(runs.c.started_at < cutoff))
    con.execute(delete(alerts).where(alerts.c.sent_at < cutoff))
    con.execute(delete(trip_quotes).where(trip_quotes.c.checked_at < cutoff))
    con.execute(delete(trip_alerts).where(trip_alerts.c.sent_at < cutoff))


# ------------------------------------------------------------ cobertura de rutas
def cached_routes(con, provider: str, pairs, since_iso: str) -> dict[tuple[str, str], bool]:
    """Pares ya comprobados desde `since_iso`: {(o, d): opera}."""
    if not pairs:
        return {}
    r = provider_routes.c
    wanted = set(pairs)
    origins = sorted({o for o, _d in wanted})
    rows = con.execute(select(r.origin, r.destination, r.operated)
                       .where(r.provider == provider, r.checked_at >= since_iso, r.origin.in_(origins))).all()
    return {(o, d): bool(op) for o, d, op in rows if (o, d) in wanted}


def forget_routes(con, provider: str):
    con.execute(delete(provider_routes).where(provider_routes.c.provider == provider))


def save_routes(con, provider: str, results: dict[tuple[str, str], bool], checked_at: str):
    if not results:
        return
    r = provider_routes.c
    for o in {o for o, _d in results}:
        dests = [d for oo, d in results if oo == o]
        con.execute(delete(provider_routes).where(r.provider == provider, r.origin == o, r.destination.in_(dests)))
    con.execute(insert(provider_routes), [
        {"provider": provider, "origin": o, "destination": d, "operated": int(ok), "checked_at": checked_at}
        for (o, d), ok in results.items()
    ])


# ------------------------------------------------------ salud de los proveedores
def save_health(con, provider: str, status: str, detail: list[dict], latency_ms: int, checked_at: str):
    con.execute(delete(provider_health).where(provider_health.c.provider == provider))
    con.execute(insert(provider_health).values(provider=provider, status=status, detail=json.dumps(detail),
                                               latency_ms=latency_ms, checked_at=checked_at))


def list_health(con) -> dict[str, dict]:
    return {r["provider"]: {**r, "detail": json.loads(r["detail"])} for r in _all(con, select(provider_health))}


# ---------------------------------------------------------- proveedores propios
def list_provider_scripts(con) -> list[dict]:
    return _all(con, select(provider_scripts).order_by(provider_scripts.c.created_at, provider_scripts.c.key))


def get_provider_script(con, key: str) -> dict | None:
    return _one(con, select(provider_scripts).where(provider_scripts.c.key == key))


def save_provider_script(con, key: str, values: dict, username: str):
    """Crea o actualiza el script de un proveedor propio."""
    now = datetime.now().isoformat(timespec="seconds")
    values = {**values, "updated_at": now, "updated_by": username}
    if get_provider_script(con, key):
        con.execute(update(provider_scripts).where(provider_scripts.c.key == key).values(**values))
    else:
        con.execute(insert(provider_scripts).values(key=key, created_at=now, **values))


def delete_provider_script(con, key: str):
    """Borra el proveedor y lo que lo ata a las vigilancias (cobertura, caché, prueba y plantilla de enlace).

    Los precios y avisos ya guardados se conservan como histórico.
    """
    con.execute(delete(provider_scripts).where(provider_scripts.c.key == key))
    con.execute(delete(watch_providers).where(watch_providers.c.provider == key))
    forget_routes(con, key)
    con.execute(delete(provider_health).where(provider_health.c.provider == key))
    con.execute(delete(settings_t).where(settings_t.c.key == f"link_{key}"))


def provider_usage(con, key: str) -> int:
    """Vigilancias que tienen asignado el proveedor."""
    return con.execute(select(func.count()).select_from(watch_providers)
                       .where(watch_providers.c.provider == key)).scalar() or 0
