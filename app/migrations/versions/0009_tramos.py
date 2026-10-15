"""2.0: el viaje es la entidad principal y las vigilancias son sus tramos internos.

Cambio de modelo (ver AGENTS.md): hasta ahora una vigilancia era una entidad suelta y un viaje juntaba dos
vigilancias existentes (`trips.outbound_id` / `trips.return_id`, FK → `watches`, borrar una vigilancia borraba el
viaje). A partir de aquí el **viaje posee sus tramos**: `watches.trip_id` (FK → `trips` ON DELETE CASCADE) y
`watches.role` (`outbound` / `return`; en la 2.1 también `stay`). Un «solo ida» es un viaje con solo tramo de ida,
por eso `trip_quotes.ret_date`/`ret_price` y `trip_alerts.ret_date` pasan a NULL-ables.

Migración de datos (todo o nada, con las FK desactivadas por db.init en SQLite):
- Cada viaje existente reclama sus vigilancias de ida/vuelta como tramos. Una vigilancia compartida por más de un
  viaje se **duplica** (con su cobertura, canales, precios, avisos y ejecuciones) para que cada viaje tenga el suyo.
- Cada vigilancia huérfana (sin viaje) se **envuelve** en un viaje de solo ida, sin perder su histórico.
- Los canales de los tramos (`watch_channels`) se suben al viaje (`trip_channels`): los avisos pasan a ser del viaje.

Orden importante: se leen los tramos de los viajes existentes ANTES de quitar `outbound_id`/`return_id`, pero los
viajes-envoltorio se crean DESPUÉS (si no, el INSERT chocaría con el NOT NULL de esas columnas). La FK y el NOT NULL
de `watches.trip_id`/`role` se tensan al final, cuando ya todas las vigilancias tienen dueño.

Revisión: 0009
Anterior: 0008
Creada: 2026-10-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

ISO = sa.String(32)

# Foto del esquema en esta revisión (no importar app.db: cada revisión es una foto congelada).
_meta = sa.MetaData()

# `watches` tras añadir trip_id/role (paso 1). Con PK para inserted_primary_key al duplicar.
watches_t = sa.Table(
    "watches", _meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Integer),
    sa.Column("trip_id", sa.Integer),
    sa.Column("role", sa.String(10)),
    sa.Column("name", sa.String(200)),
    sa.Column("origin", sa.String(40)),
    sa.Column("destination", sa.String(40)),
    sa.Column("max_price", sa.Double),
    sa.Column("discount_pct", sa.Double),
    sa.Column("date_from", sa.String(10)),
    sa.Column("date_to", sa.String(10)),
    sa.Column("max_stops", sa.Integer),
    sa.Column("enabled", sa.Integer),
    sa.Column("created_at", ISO),
    sa.Column("kind", sa.String(10)),
)
# Columnas que se copian al duplicar una vigilancia (todo menos id/trip_id/role, que se fijan aparte).
_WATCH_COPY = ("user_id", "name", "origin", "destination", "max_price", "discount_pct",
               "date_from", "date_to", "max_stops", "enabled", "created_at", "kind")

# `trips` con las columnas de tramo (para LEER los tramos de los viajes existentes antes de quitarlas).
trips_old = sa.Table(
    "trips", _meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("outbound_id", sa.Integer),
    sa.Column("return_id", sa.Integer),
)

watch_providers_t = sa.Table(
    "watch_providers", _meta,
    sa.Column("watch_id", sa.Integer, primary_key=True),
    sa.Column("provider", sa.String(50), primary_key=True),
    sa.Column("routes", sa.Text),
    sa.Column("active", sa.Integer),
    sa.Column("checked_at", ISO),
)
watch_channels_t = sa.Table(
    "watch_channels", _meta,
    sa.Column("watch_id", sa.Integer, primary_key=True),
    sa.Column("channel_id", sa.Integer, primary_key=True),
)
trip_channels_t = sa.Table(
    "trip_channels", _meta,
    sa.Column("trip_id", sa.Integer, primary_key=True),
    sa.Column("channel_id", sa.Integer, primary_key=True),
)
prices_t = sa.Table(
    "prices", _meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("watch_id", sa.Integer),
    sa.Column("provider", sa.String(50)),
    sa.Column("flight_date", sa.String(10)),
    sa.Column("price", sa.Double),
    sa.Column("currency", sa.String(3)),
    sa.Column("checked_at", ISO),
    sa.Column("origin", sa.String(10)),
    sa.Column("destination", sa.String(10)),
    sa.Column("orig_price", sa.Double),
    sa.Column("stops", sa.Integer),
    sa.Column("departs_at", sa.String(16)),
    sa.Column("arrives_at", sa.String(16)),
)
alerts_t = sa.Table(
    "alerts", _meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("watch_id", sa.Integer),
    sa.Column("provider", sa.String(50)),
    sa.Column("flight_date", sa.String(10)),
    sa.Column("price", sa.Double),
    sa.Column("link", sa.Text),
    sa.Column("sent_at", ISO),
)
runs_t = sa.Table(
    "runs", _meta,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("watch_id", sa.Integer),
    sa.Column("provider", sa.String(50)),
    sa.Column("trigger", sa.String(20)),
    sa.Column("started_at", ISO),
    sa.Column("finished_at", ISO),
    sa.Column("ok", sa.Integer),
    sa.Column("n_prices", sa.Integer),
    sa.Column("n_deals", sa.Integer),
    sa.Column("error", sa.Text),
)

# `trips` sin las columnas de tramo (para CREAR los viajes-envoltorio tras quitarlas).
_meta2 = sa.MetaData()
trips_new = sa.Table(
    "trips", _meta2,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("user_id", sa.Integer),
    sa.Column("name", sa.String(200)),
    sa.Column("min_nights", sa.Integer),
    sa.Column("max_nights", sa.Integer),
    sa.Column("date_from", sa.String(10)),
    sa.Column("date_to", sa.String(10)),
    sa.Column("max_total", sa.Double),
    sa.Column("discount_pct", sa.Double),
    sa.Column("enabled", sa.Integer),
    sa.Column("created_at", ISO),
)


def _copy_watch_children(bind, src_id: int, new_id: int) -> None:
    """Copia la cobertura, canales, precios, avisos y ejecuciones de una vigilancia a su duplicado."""
    for row in bind.execute(sa.select(watch_providers_t).where(watch_providers_t.c.watch_id == src_id)).mappings():
        bind.execute(sa.insert(watch_providers_t).values({**row, "watch_id": new_id}))
    for row in bind.execute(sa.select(watch_channels_t).where(watch_channels_t.c.watch_id == src_id)).mappings():
        bind.execute(sa.insert(watch_channels_t).values({**row, "watch_id": new_id}))
    for tbl in (prices_t, alerts_t, runs_t):
        for row in bind.execute(sa.select(tbl).where(tbl.c.watch_id == src_id)).mappings():
            vals = dict(row)
            vals.pop("id", None)  # id autoincrement: lo asigna el motor
            vals["watch_id"] = new_id
            bind.execute(sa.insert(tbl).values(vals))


def _add_trip_channel(bind, trip_id: int, channel_id: int) -> None:
    """Sube un canal de un tramo al viaje, sin duplicar si ya lo tiene."""
    exists = bind.execute(sa.select(trip_channels_t.c.trip_id).where(
        (trip_channels_t.c.trip_id == trip_id) & (trip_channels_t.c.channel_id == channel_id))).first()
    if not exists:
        bind.execute(sa.insert(trip_channels_t).values(trip_id=trip_id, channel_id=channel_id))


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Columnas nuevas (nullable de momento; se tensan en el paso 7).
    op.add_column("watches", sa.Column("trip_id", sa.Integer, nullable=True))
    op.add_column("watches", sa.Column("role", sa.String(10), nullable=True))

    # 2. Columnas de vuelta del histórico de viajes pasan a NULL-ables (viajes de solo ida).
    with op.batch_alter_table("trip_quotes") as batch:
        batch.alter_column("ret_date", existing_type=sa.String(10), nullable=True)
        batch.alter_column("ret_price", existing_type=sa.Double, nullable=True)
    with op.batch_alter_table("trip_alerts") as batch:
        batch.alter_column("ret_date", existing_type=sa.String(10), nullable=True)

    # 3. Cada viaje existente reclama sus vigilancias como tramos (ida/vuelta). Una vigilancia compartida por más
    #    de un viaje se duplica para que cada viaje tenga el suyo. Los canales de los tramos suben al viaje.
    claimed: set[int] = set()
    for trip in bind.execute(sa.select(trips_old).order_by(trips_old.c.id)).mappings():
        for watch_id, role in ((trip["outbound_id"], "outbound"), (trip["return_id"], "return")):
            if watch_id is None:
                continue
            if watch_id in claimed:
                dup = bind.execute(sa.insert(watches_t).values({
                    **{c: bind.execute(sa.select(watches_t.c[c]).where(watches_t.c.id == watch_id)).scalar()
                       for c in _WATCH_COPY},
                    "trip_id": trip["id"], "role": role,
                }))
                new_id = dup.inserted_primary_key[0]
                _copy_watch_children(bind, watch_id, new_id)
            else:
                bind.execute(sa.update(watches_t).where(watches_t.c.id == watch_id).values(
                    trip_id=trip["id"], role=role))
                claimed.add(watch_id)
            for ch in bind.execute(sa.select(watch_channels_t.c.channel_id).where(
                    watch_channels_t.c.watch_id == watch_id)).scalars():
                _add_trip_channel(bind, trip["id"], ch)

    # 4. Ya leídos los tramos: se quitan outbound_id/return_id del viaje (recrea la tabla en SQLite; las FK están
    #    desactivadas, así que trip_channels/trip_quotes/trip_alerts sobreviven). `user_id` admite NULL, como
    #    `watches.user_id`, solo por las BD anteriores a los usuarios: sus vigilancias (sin dueño) se envuelven en
    #    viajes sin dueño que `db.bootstrap_admin()` asigna al administrador al arrancar.
    with op.batch_alter_table("trips") as batch:
        batch.drop_column("outbound_id")
        batch.drop_column("return_id")
        batch.alter_column("user_id", existing_type=sa.Integer, nullable=True)

    # 5. Cada vigilancia huérfana (sin viaje) se envuelve en un viaje de solo ida. Se crea el viaje DESPUÉS de
    #    quitar las columnas de tramo (si no, chocaría con su NOT NULL). No se copian precios: el tramo los conserva.
    for w in bind.execute(sa.select(watches_t).where(watches_t.c.trip_id.is_(None))).mappings():
        trip = bind.execute(sa.insert(trips_new).values(
            user_id=w["user_id"], name=w["name"], min_nights=1, max_nights=1,
            date_from=w["date_from"], date_to=w["date_to"], max_total=w["max_price"],
            discount_pct=w["discount_pct"], enabled=w["enabled"], created_at=w["created_at"]))
        new_trip = trip.inserted_primary_key[0]
        bind.execute(sa.update(watches_t).where(watches_t.c.id == w["id"]).values(
            trip_id=new_trip, role="outbound"))
        for ch in bind.execute(sa.select(watch_channels_t.c.channel_id).where(
                watch_channels_t.c.watch_id == w["id"])).scalars():
            _add_trip_channel(bind, new_trip, ch)

    # 6. Comprobación de seguridad: ninguna vigilancia puede quedar sin viaje antes de tensar el NOT NULL.
    huerfanas = bind.execute(sa.select(sa.func.count()).select_from(watches_t).where(
        watches_t.c.trip_id.is_(None))).scalar()
    if huerfanas:
        raise RuntimeError(f"0009: {huerfanas} vigilancia(s) sin viaje; abortando para no perder datos")

    # 7. Tensar: trip_id/role a NOT NULL + FK ON DELETE CASCADE + índice (el viaje pasa a ser el dueño).
    with op.batch_alter_table("watches") as batch:
        batch.alter_column("trip_id", existing_type=sa.Integer, nullable=False)
        batch.alter_column("role", existing_type=sa.String(10), nullable=False, server_default="outbound")
        batch.create_foreign_key("fk_watches_trip_id", "trips", ["trip_id"], ["id"], ondelete="CASCADE")
        batch.create_index("idx_watches_trip", ["trip_id"])


def downgrade() -> None:
    """Reconstruye el modelo anterior (viaje → dos vigilancias). Asimetría documentada: los viajes de solo ida
    (vigilancias que se envolvieron al subir) no tienen tramo de vuelta para rellenar `return_id` NOT NULL, así que
    se borran dejando su vigilancia como huérfana otra vez (que es como estaba antes de la 0009)."""
    bind = op.get_bind()

    # 1. Leer el mapa viaje → (ida, vuelta) antes de tocar nada.
    legs: dict[int, dict[str, int]] = {}
    for w in bind.execute(sa.select(watches_t.c.id, watches_t.c.trip_id, watches_t.c.role).where(
            watches_t.c.trip_id.isnot(None))).mappings():
        legs.setdefault(w["trip_id"], {})[w["role"]] = w["id"]

    # 2. Quitar la FK/índice de watches (y dejar trip_id/role nullable) para que borrar viajes no arrastre tramos.
    with op.batch_alter_table("watches") as batch:
        batch.drop_index("idx_watches_trip")
        batch.drop_constraint("fk_watches_trip_id", type_="foreignkey")
        batch.alter_column("trip_id", existing_type=sa.Integer, nullable=True)
        batch.alter_column("role", existing_type=sa.String(10), nullable=True)

    # 3. Volver a añadir outbound_id/return_id al viaje (nullable mientras se rellenan).
    with op.batch_alter_table("trips") as batch:
        batch.add_column(sa.Column("outbound_id", sa.Integer, nullable=True))
        batch.add_column(sa.Column("return_id", sa.Integer, nullable=True))

    # 4. Rellenar los que tienen ida y vuelta; borrar los de solo ida (sin vuelta no caben en el modelo viejo).
    for trip_id, role_map in legs.items():
        if "return" in role_map:
            bind.execute(sa.update(trips_old).where(trips_old.c.id == trip_id).values(
                outbound_id=role_map.get("outbound"), return_id=role_map["return"]))
        else:
            bind.execute(sa.delete(trips_new).where(trips_new.c.id == trip_id))

    # 5. Tensar outbound_id/return_id a NOT NULL y quitar trip_id/role de watches.
    with op.batch_alter_table("trips") as batch:
        batch.alter_column("outbound_id", existing_type=sa.Integer, nullable=False)
        batch.alter_column("return_id", existing_type=sa.Integer, nullable=False)
        batch.alter_column("user_id", existing_type=sa.Integer, nullable=False)
    with op.batch_alter_table("watches") as batch:
        batch.drop_column("role")
        batch.drop_column("trip_id")
