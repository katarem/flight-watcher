"""Viajes de ida y vuelta: tablas trips, trip_channels, trip_quotes y trip_alerts.

Un viaje junta dos vigilancias del mismo usuario (ida y vuelta) con un rango de noches. Solo añade
tablas nuevas: no toca las existentes ni sus datos.

Revisión: 0005
Anterior: 0004
Creada: 2026-10-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_OPTS = {"mysql_charset": "utf8mb4"}


def upgrade() -> None:
    op.create_table(
        "trips",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("outbound_id", sa.Integer, sa.ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("return_id", sa.Integer, sa.ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("min_nights", sa.Integer, nullable=False),
        sa.Column("max_nights", sa.Integer, nullable=False),
        sa.Column("date_from", sa.String(10)),
        sa.Column("date_to", sa.String(10)),
        sa.Column("max_total", sa.Double),
        sa.Column("discount_pct", sa.Double, nullable=False, server_default="30"),
        sa.Column("enabled", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(32), nullable=False),
        **_OPTS,
    )
    op.create_index("idx_trips_user", "trips", ["user_id"])
    op.create_table(
        "trip_channels",
        sa.Column("trip_id", sa.Integer, sa.ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True),
        **_OPTS,
    )
    op.create_table(
        "trip_quotes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trip_id", sa.Integer, sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checked_at", sa.String(32), nullable=False),
        sa.Column("out_date", sa.String(10), nullable=False),
        sa.Column("ret_date", sa.String(10), nullable=False),
        sa.Column("total", sa.Double, nullable=False),
        sa.Column("out_price", sa.Double, nullable=False),
        sa.Column("ret_price", sa.Double, nullable=False),
        **_OPTS,
    )
    op.create_index("idx_trip_quotes", "trip_quotes", ["trip_id", "checked_at"])
    op.create_table(
        "trip_alerts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trip_id", sa.Integer, sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("out_date", sa.String(10), nullable=False),
        sa.Column("ret_date", sa.String(10), nullable=False),
        sa.Column("total", sa.Double, nullable=False),
        sa.Column("sent_at", sa.String(32), nullable=False),
        **_OPTS,
    )
    op.create_index("idx_trip_alerts", "trip_alerts", ["trip_id", "out_date"])


def downgrade() -> None:
    op.drop_index("idx_trip_alerts", table_name="trip_alerts")
    op.drop_table("trip_alerts")
    op.drop_index("idx_trip_quotes", table_name="trip_quotes")
    op.drop_table("trip_quotes")
    op.drop_table("trip_channels")
    op.drop_index("idx_trips_user", table_name="trips")
    op.drop_table("trips")
