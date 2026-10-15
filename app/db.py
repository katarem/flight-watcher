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

from . import config, kinds, places

DEFAULT_SETTINGS = {
    "schedule_hours": "8",
    "schedule_minute": "0",
    "timezone": "Europe/Madrid",
    "max_months": "11",
    "min_samples": "30",
    "retention_days": "400",
    "headless": "0",  # con ventana (en Docker, la pantalla virtual de Xvfb); sin pantalla va sin ventana igualmente
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
NODE = String(places.NODE_MAX)  # lugar de un transporte: aeropuerto (IATA), estación, puerto o parada
PLACE = String(places.CODE_MAX)  # lugar de una vigilancia: también ciudad, país o grupo (ver app/places.py)
KIND = String(kinds.KEY_MAX)  # transporte de una vigilancia o tipo de un proveedor (ver app/kinds.py)

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

# Vigilancias = tramos internos de un viaje (ya no se gestionan sueltas desde el panel). Cada una pertenece a un
# único viaje (`trip_id`) con un papel (`role`: ida, vuelta y, en la 2.1, estancia). El viaje es el dueño: borrarlo
# borra sus tramos. Guardan la cobertura, el histórico de precios y la configuración de proveedores del tramo.
watches = Table(
    "watches", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # Nullable solo por las BD anteriores a los usuarios: bootstrap_admin() las asigna al administrador.
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE", name="fk_watches_user_id")),
    # Viaje al que pertenece el tramo. Nullable solo durante la migración 0009; después, NOT NULL.
    Column("trip_id", Integer, ForeignKey("trips.id", ondelete="CASCADE", name="fk_watches_trip_id"),
           nullable=False),
    Column("role", String(10), nullable=False, server_default="outbound"),  # outbound | return (| stay en la 2.1)
    Column("name", String(200), nullable=False),
    Column("origin", PLACE, nullable=False),
    Column("destination", PLACE, nullable=False),
    # max_price/discount_pct/date_from/date_to se conservan por el tramo, pero la lógica de chollo vive en el viaje.
    Column("max_price", Double),
    Column("discount_pct", Double, nullable=False, server_default="30"),
    Column("date_from", String(10)),
    Column("date_to", String(10)),
    Column("max_stops", Integer),  # escalas como máximo (0 = solo directos, NULL = sin límite)
    Column("enabled", Integer, nullable=False, server_default="1"),
    Column("created_at", ISO, nullable=False),
    Column("kind", KIND, nullable=False, server_default=kinds.DEFAULT),  # transporte: flight (ver app/kinds.py)
    Index("idx_watches_user", "user_id"),
    Index("idx_watches_trip", "trip_id"),
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

# Caché de cobertura: si un proveedor opera un par de lugares (red publicada o pregunta directa).
provider_routes = Table(
    "provider_routes", metadata,
    Column("provider", String(50), primary_key=True),
    Column("origin", NODE, primary_key=True),
    Column("destination", NODE, primary_key=True),
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

# Proveedores: cada uno es un script de Python (escrito o importado desde el panel por un administrador, o de los
# incluidos) que cumple el contrato de `app/providers/scripted.py`. La clave no cambia nunca (la usan precios,
# avisos y vigilancias).
provider_scripts = Table(
    "provider_scripts", metadata,
    Column("key", String(50), primary_key=True),
    Column("label", String(100), nullable=False),
    Column("color", String(7), nullable=False),
    Column("coverage", String(20), nullable=False),  # network | probe | universal
    Column("max_routes", Integer),
    Column("health_origin", NODE, nullable=False),
    Column("health_destination", NODE, nullable=False),
    Column("link_template", Text, nullable=False),
    Column("notes", Text, nullable=False),
    Column("min_interval", Double, nullable=False, server_default="1.5"),
    Column("code", Text, nullable=False),
    Column("enabled", Integer, nullable=False, server_default="1"),
    Column("created_at", ISO, nullable=False),
    Column("updated_at", ISO, nullable=False),
    Column("updated_by", String(32), nullable=False),  # usuario que lo guardó por última vez
    Column("source", String(500)),  # enlace del paquete del que se importó (NULL = escrito en el panel o archivo)
    Column("stealth", Integer, nullable=False, server_default="0"),  # «Medidas anti-bot» 0/1/2 (providers/stealth.py)
    Column("kind", KIND, nullable=False, server_default=kinds.DEFAULT),  # tipo: flight, train… (ver app/kinds.py)
    **_TABLE_OPTS,
)

# Canales de cada vigilancia antes de la 2.0: la 0009 los pasó a `trip_channels` (los avisos son del viaje). Ya no se
# escriben; se conservan por si se baja de revisión.
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
    Column("origin", NODE),       # lugar real: aeropuerto, estación… (NULL = el de la vigilancia)
    Column("destination", NODE),
    Column("orig_price", Double),  # precio en la moneda original (NULL = el mismo en euros)
    Column("stops", Integer),      # escalas (NULL = datos antiguos, directos)
    # Salida y llegada (hora local de cada lugar, «AAAA-MM-DDTHH:MM») si la web las da; NULL = no se sabe.
    Column("departs_at", String(16)),
    Column("arrives_at", String(16)),
    Index("idx_prices_snap", "watch_id", "provider", "checked_at"),
    Index("idx_prices_date", "watch_id", "provider", "flight_date"),
    **_TABLE_OPTS,
)

# Avisos por vigilancia de antes de la 2.0 (desde la 0009 se avisa por viaje: `trip_alerts`). Solo histórico, que
# se purga con `retention_days`.
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

# Viajes: la entidad principal. El usuario crea un viaje y este posee sus tramos (vigilancias internas, ver
# `watches`): un tramo de ida obligatorio, uno de vuelta opcional (solo ida = sin tramo de vuelta) y, en la 2.1,
# una estancia. El precio de un viaje es la suma del más barato de cada tramo para cada fecha de ida y cada
# número de noches permitido. El transporte (kind) se deriva del tramo de ida.
trips = Table(
    "trips", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # Nullable solo por las BD anteriores a los usuarios (la 0009 envuelve sus vigilancias sin dueño en viajes sin
    # dueño): bootstrap_admin() los asigna al administrador.
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE")),
    Column("name", String(200), nullable=False),
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
# ret_date/ret_price son NULL en los viajes de solo ida (sin tramo de vuelta).
trip_quotes = Table(
    "trip_quotes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("trip_id", Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
    Column("checked_at", ISO, nullable=False),
    Column("out_date", String(10), nullable=False),
    Column("ret_date", String(10)),  # NULL = viaje de solo ida
    Column("total", Double, nullable=False),
    Column("out_price", Double, nullable=False),
    Column("ret_price", Double),     # NULL = viaje de solo ida
    Index("idx_trip_quotes", "trip_id", "checked_at"),
    **_TABLE_OPTS,
)

trip_alerts = Table(
    "trip_alerts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("trip_id", Integer, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
    Column("out_date", String(10), nullable=False),
    Column("ret_date", String(10)),  # NULL = viaje de solo ida
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
    """Crea el viaje inicial (de ida y vuelta Sevilla ⇄ Tenerife, del usuario dado) si la BD no tiene ninguno.

    TCI es el código de ciudad de Tenerife: se consultan Tenerife Norte (Vueling) y Sur (Ryanair).
    """
    def leg(name, o, d):
        return {"name": name, "origin": o, "destination": d, "providers": ["vueling", "ryanair"], "max_price": None,
                "discount_pct": 30, "date_from": None, "date_to": None, "max_stops": 0, "enabled": True,
                "kind": kinds.DEFAULT}

    with connect() as con:
        if con.execute(select(func.count()).select_from(trips)).scalar():
            return
        create_trip(con, user_id, {
            "name": "Sevilla ⇄ Tenerife", "min_nights": 5, "max_nights": 10, "date_from": None, "date_to": None,
            "max_total": 80, "discount_pct": 30, "enabled": True,
            "outbound": leg("Sevilla → Tenerife", "SVQ", "TCI"), "return": leg("Tenerife → Sevilla", "TCI", "SVQ"),
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


def trip_counts(con) -> dict[int, int]:
    rows = con.execute(select(trips.c.user_id, func.count()).group_by(trips.c.user_id)).all()
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
        con.execute(update(trips).where(trips.c.user_id.is_(None)).values(user_id=admin["id"]))
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
                for t in list_trips(con, admin["id"]):
                    set_trip_channels(con, t["id"], ids)
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
        "kind": data.get("kind") or kinds.DEFAULT,
    }


def pair_key(pair) -> str:
    return f"{pair[0]}-{pair[1]}"


def parse_pair(key: str) -> tuple[str, str]:
    o, d = key.split("-", 1)
    return o, d


def default_coverage(origin: str, destination: str, keys, mode: str = kinds.DEFAULT) -> dict[str, dict]:
    """Cobertura sin comprobar: todos los pares de lugares (del transporte `mode`) del origen y el destino."""
    pairs = places.routes(origin, destination, mode)
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


def list_watches(con, user_id: int | None = None, kind: str | None = None) -> list[dict]:
    stmt = select(watches).order_by(watches.c.id)
    if user_id is not None:
        stmt = stmt.where(watches.c.user_id == user_id)
    if kind is not None:
        stmt = stmt.where(watches.c.kind == kind)
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
    return data.get("coverage") or default_coverage(data["origin"], data["destination"], data.get("providers", []),
                                                    data.get("kind") or kinds.DEFAULT)


def create_watch(con, user_id: int, data: dict, trip_id: int, role: str = "outbound") -> int:
    """Crea un tramo de un viaje. `data["coverage"]` con la cobertura comprobada o, si falta, `data["providers"]`
    (sin comprobar). Las vigilancias ya no se crean sueltas: siempre pertenecen a un viaje (`trip_id`)."""
    values = {**_watch_values(data), "user_id": user_id, "trip_id": trip_id, "role": role,
              "created_at": datetime.now().isoformat(timespec="seconds")}
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
         "origin": r.origin or None, "destination": r.destination or None,
         "departs_at": minutes(getattr(r, "departure", None)), "arrives_at": minutes(getattr(r, "arrival", None))}
        for r in rows
    ])


def minutes(value) -> str | None:
    """«AAAA-MM-DDTHH:MM» de una salida o llegada (`datetime`, ya normalizada por el proveedor) o None."""
    return value.isoformat(timespec="minutes")[:16] if isinstance(value, datetime) else None


def latest_snapshot(con, watch_id, provider) -> list[dict]:
    p = prices.c
    last = select(func.max(p.checked_at)).where(p.watch_id == watch_id, p.provider == provider).scalar_subquery()
    return _all(con, select(p.flight_date, p.price, p.checked_at, p.origin, p.destination, p.currency, p.orig_price,
                            p.stops, p.departs_at, p.arrives_at)
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


# ------------------------------------------------------------------------ viajes
def _trip_values(data: dict) -> dict:
    return {k: data[k] for k in ("name", "min_nights", "max_nights", "date_from", "date_to", "max_total",
                                 "discount_pct")} | {"enabled": int(data["enabled"])}


def trip_legs(con, trip_id: int) -> dict[str, dict]:
    """Tramos del viaje por su papel: {"outbound": vigilancia, "return": vigilancia?} (solo ida = sin "return")."""
    ws = _with_extras(con, _all(con, select(watches).where(watches.c.trip_id == trip_id).order_by(watches.c.id)))
    return {w["role"]: w for w in ws}


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


def list_trips(con, user_id: int | None = None) -> list[dict]:
    """Viajes (de un usuario) con `channel_ids`."""
    stmt = select(trips).order_by(trips.c.id)
    if user_id is not None:
        stmt = stmt.where(trips.c.user_id == user_id)
    return _with_trip_channels(con, _all(con, stmt))


def get_trip(con, trip_id: int) -> dict | None:
    t = _one(con, select(trips).where(trips.c.id == trip_id))
    return _with_trip_channels(con, [t])[0] if t else None


def create_trip(con, user_id: int, data: dict) -> int:
    """Crea el viaje y sus tramos: `data["outbound"]` (obligatorio) y `data["return"]` (opcional = solo ida).
    Cada tramo es una vigilancia con los datos de `create_watch`."""
    tid = con.execute(insert(trips).values(
        **_trip_values(data), user_id=user_id, created_at=datetime.now().isoformat(timespec="seconds"),
    )).inserted_primary_key[0]
    create_watch(con, user_id, data["outbound"], tid, "outbound")
    if data.get("return"):
        create_watch(con, user_id, data["return"], tid, "return")
    return tid


def update_trip(con, trip_id: int, data: dict):
    """Actualiza el viaje y reconcilia sus tramos: el de ida siempre se actualiza; el de vuelta se crea si se
    añade, se actualiza si sigue y se borra (con su histórico) si el viaje pasa a solo ida."""
    con.execute(update(trips).where(trips.c.id == trip_id).values(**_trip_values(data)))
    legs = trip_legs(con, trip_id)
    user_id = legs["outbound"]["user_id"]
    update_watch(con, legs["outbound"]["id"], data["outbound"])
    if data.get("return"):
        if "return" in legs:
            update_watch(con, legs["return"]["id"], data["return"])
        else:
            create_watch(con, user_id, data["return"], trip_id, "return")
    elif "return" in legs:
        delete_watch(con, legs["return"]["id"])


def delete_trip(con, trip_id: int):
    con.execute(delete(trips).where(trips.c.id == trip_id))


def toggle_trip(con, trip_id: int):
    """Pausa/reanuda el viaje y sus tramos a la vez (el cron comprueba los tramos por su `enabled`)."""
    con.execute(update(trips).where(trips.c.id == trip_id).values(enabled=1 - trips.c.enabled))
    enabled = con.execute(select(trips.c.enabled).where(trips.c.id == trip_id)).scalar()
    con.execute(update(watches).where(watches.c.trip_id == trip_id).values(enabled=enabled))


def set_trip_channels(con, trip_id: int, channel_ids: list[int]):
    """Sustituye los canales del viaje. El llamador garantiza que son del dueño."""
    con.execute(delete(trip_channels).where(trip_channels.c.trip_id == trip_id))
    if channel_ids:
        con.execute(insert(trip_channels), [{"trip_id": trip_id, "channel_id": c} for c in sorted(set(channel_ids))])


def insert_trip_quotes(con, trip_id: int, checked_at: str, quotes: list[dict]):
    if quotes:
        con.execute(insert(trip_quotes), [
            {"trip_id": trip_id, "checked_at": checked_at, "out_date": q["out_date"], "ret_date": q["ret_date"],
             "total": q["total"], "out_price": q["out"]["price"],
             "ret_price": q["ret"]["price"] if q["ret"] else None}  # None en los viajes de solo ida
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


def list_user_trip_alerts(con, user_id: int, limit: int = 10) -> list[dict]:
    """Últimos avisos de todos los viajes del usuario, con el nombre del viaje."""
    a = trip_alerts.c
    stmt = (select(trip_alerts, trips.c.name.label("trip_name")).join(trips, trips.c.id == a.trip_id)
            .where(trips.c.user_id == user_id).order_by(a.sent_at.desc(), a.id.desc()).limit(limit))
    return _all(con, stmt)


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
    stmt = (select(runs, watches.c.name.label("watch_name"), watches.c.kind.label("watch_kind"),
                   watches.c.trip_id, trips.c.name.label("trip_name"))
            .join(watches, watches.c.id == runs.c.watch_id).join(trips, trips.c.id == watches.c.trip_id))
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


# ------------------------------------------------------------------- proveedores
def list_provider_scripts(con) -> list[dict]:
    return _all(con, select(provider_scripts).order_by(provider_scripts.c.created_at, provider_scripts.c.key))


def get_provider_script(con, key: str) -> dict | None:
    return _one(con, select(provider_scripts).where(provider_scripts.c.key == key))


def save_provider_script(con, key: str, values: dict, username: str):
    """Crea o actualiza un proveedor (al actualizar, solo cambia las columnas de `values`)."""
    now = datetime.now().isoformat(timespec="seconds")
    values = {**values, "updated_at": now, "updated_by": username}
    if get_provider_script(con, key):
        con.execute(update(provider_scripts).where(provider_scripts.c.key == key).values(**values))
    else:
        con.execute(insert(provider_scripts).values(key=key, created_at=now, **values))


def replace_provider_source(con, old: str, new: str):
    """Cambia el enlace de origen guardado de los proveedores (sin tocar `updated_at`: no es un cambio suyo)."""
    con.execute(update(provider_scripts).where(provider_scripts.c.source == old).values(source=new))


def delete_provider_script(con, key: str):
    """Borra el proveedor y lo que lo ata a las vigilancias (cobertura, caché y prueba de acceso).

    Los precios y avisos ya guardados se conservan como histórico.
    """
    con.execute(delete(provider_scripts).where(provider_scripts.c.key == key))
    con.execute(delete(watch_providers).where(watch_providers.c.provider == key))
    forget_routes(con, key)
    con.execute(delete(provider_health).where(provider_health.c.provider == key))


def provider_usage_counts(con) -> dict[str, int]:
    """Vigilancias que tienen asignado cada proveedor."""
    rows = con.execute(select(watch_providers.c.provider, func.count()).group_by(watch_providers.c.provider)).all()
    return {k: n for k, n in rows}


def providers_in_use(con) -> set[str]:
    return set(provider_usage_counts(con))


def get_setting(con, key: str) -> str | None:
    return con.execute(select(settings_t.c.value).where(settings_t.c.key == key)).scalar()


def set_setting(con, key: str, value: str):
    con.execute(_upsert_settings(), [{"key": key, "value": value}])


def pop_link_settings(con) -> dict[str, str]:
    """Plantillas de enlace por proveedor que antes se editaban en Ajustes (`link_<clave>`): las devuelve y las
    borra (ahora son parte de cada proveedor)."""
    rows = _all(con, select(settings_t).where(settings_t.c.key.like("link\\_%", escape="\\")))
    con.execute(delete(settings_t).where(settings_t.c.key.in_([r["key"] for r in rows])))
    return {r["key"][5:]: r["value"].strip() for r in rows}
