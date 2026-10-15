"""2.1: alojamiento (la estancia como tramo del viaje) y viajeros.

- `watches.filters`: filtros de una estancia (JSON); `watches.destination` pasa de 40 a 120 caracteres (el destino
  de una estancia es texto libre). Una estancia es un tramo con `role = "stay"` y transporte `hotel`.
- `provider_scripts.health_origin` pasa a 120 caracteres: en un proveedor de alojamiento es el destino de prueba.
- `prices.nights` y `prices.offer` (estancias: noches y alojamiento) y `prices.estimated` (precio de un adulto ×
  plazas, de una web que no admite varios viajeros).
- `trips.party` (viajeros, JSON; NULL = un adulto) y `trips.max_per_person`.
- `trip_quotes.stay_price`, y `trip_quotes.out_price` admite NULL (viajes de solo estancia).
- `stay_queries`: última consulta de cada combinación (entrada, noches) de una estancia en cada web.

Nada que migrar: los viajes anteriores son de un adulto y sin estancia.

Revisión: 0010
Anterior: 0009
Creada: 2026-10-15
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

PLACE, TEXT_PLACE, NODE = sa.String(40), sa.String(120), sa.String(10)


def upgrade() -> None:
    op.create_table(
        "stay_queries",
        sa.Column("watch_id", sa.Integer(), sa.ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("checkin", sa.String(10), nullable=False),
        sa.Column("nights", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("watch_id", "provider", "checkin", "nights"),
        mysql_charset="utf8mb4",
    )
    op.add_column("watches", sa.Column("filters", sa.Text(), nullable=True))
    with op.batch_alter_table("watches") as batch:
        batch.alter_column("destination", existing_type=PLACE, type_=TEXT_PLACE, existing_nullable=False)
    with op.batch_alter_table("provider_scripts") as batch:
        batch.alter_column("health_origin", existing_type=NODE, type_=TEXT_PLACE, existing_nullable=False)
    op.add_column("prices", sa.Column("nights", sa.Integer(), nullable=True))
    op.add_column("prices", sa.Column("offer", sa.Text(), nullable=True))
    op.add_column("prices", sa.Column("estimated", sa.Integer(), nullable=True))
    op.add_column("trips", sa.Column("party", sa.Text(), nullable=True))
    op.add_column("trips", sa.Column("max_per_person", sa.Double(), nullable=True))
    op.add_column("trip_quotes", sa.Column("stay_price", sa.Double(), nullable=True))
    with op.batch_alter_table("trip_quotes") as batch:
        batch.alter_column("out_price", existing_type=sa.Double(), nullable=True)


def downgrade() -> None:
    # Antes de la 2.1 no había estancias, viajes sin ida ni proveedores de alojamiento: se borran (con su histórico).
    op.drop_table("stay_queries")
    op.execute("DELETE FROM prices WHERE watch_id IN (SELECT id FROM watches WHERE role = 'stay')")
    op.execute("DELETE FROM runs WHERE watch_id IN (SELECT id FROM watches WHERE role = 'stay')")
    op.execute("DELETE FROM watch_providers WHERE watch_id IN (SELECT id FROM watches WHERE role = 'stay')")
    op.execute("DELETE FROM watches WHERE role = 'stay'")
    no_outbound = "SELECT id FROM trips WHERE id NOT IN (SELECT trip_id FROM watches WHERE role = 'outbound')"
    for table in ("trip_channels", "trip_quotes", "trip_alerts"):
        op.execute(f"DELETE FROM {table} WHERE trip_id IN ({no_outbound})")
    op.execute(f"DELETE FROM trips WHERE id IN (SELECT id FROM ({no_outbound}) AS t)")
    op.execute("DELETE FROM trip_quotes WHERE out_price IS NULL")
    # `key` es palabra reservada en MySQL: con SQLAlchemy Core se entrecomilla sola.
    scripts = sa.table("provider_scripts", sa.column("key"), sa.column("kind"))
    hotel = sa.select(scripts.c.key).where(scripts.c.kind == "hotel")
    for table in ("watch_providers", "provider_routes", "provider_health"):
        t = sa.table(table, sa.column("provider"))
        op.execute(t.delete().where(t.c.provider.in_(hotel)))
    op.execute(scripts.delete().where(scripts.c.kind == "hotel"))
    with op.batch_alter_table("trip_quotes") as batch:
        batch.alter_column("out_price", existing_type=sa.Double(), nullable=False)
        batch.drop_column("stay_price")
    with op.batch_alter_table("trips") as batch:
        batch.drop_column("max_per_person")
        batch.drop_column("party")
    with op.batch_alter_table("prices") as batch:
        batch.drop_column("estimated")
        batch.drop_column("offer")
        batch.drop_column("nights")
    with op.batch_alter_table("provider_scripts") as batch:
        batch.alter_column("health_origin", existing_type=TEXT_PLACE, type_=NODE, existing_nullable=False)
    with op.batch_alter_table("watches") as batch:
        batch.alter_column("destination", existing_type=TEXT_PLACE, type_=PLACE, existing_nullable=False)
        batch.drop_column("filters")
