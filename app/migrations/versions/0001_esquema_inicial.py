"""Esquema inicial: settings, watches, prices, alerts y runs.

Copia congelada del esquema a fecha 2026-09-30: no importar app.db aquí, porque el esquema de
app.db seguirá cambiando y esta migración debe crear siempre lo mismo.

Revisión: 0001
Anterior:
Creada: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_OPTS = {"mysql_charset": "utf8mb4"}
ISO = sa.String(32)
IATA = sa.String(3)


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        **_OPTS,
    )
    op.create_table(
        "watches",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("origin", IATA, nullable=False),
        sa.Column("destination", IATA, nullable=False),
        sa.Column("providers", sa.String(200), nullable=False, server_default="vueling"),
        sa.Column("max_price", sa.Double),
        sa.Column("discount_pct", sa.Double, nullable=False, server_default="30"),
        sa.Column("date_from", sa.String(10)),
        sa.Column("date_to", sa.String(10)),
        sa.Column("enabled", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", ISO, nullable=False),
        **_OPTS,
    )
    op.create_table(
        "prices",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("flight_date", sa.String(10), nullable=False),
        sa.Column("price", sa.Double, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("checked_at", ISO, nullable=False),
        sa.Column("origin", IATA),
        sa.Column("destination", IATA),
        **_OPTS,
    )
    op.create_index("idx_prices_snap", "prices", ["watch_id", "provider", "checked_at"])
    op.create_index("idx_prices_date", "prices", ["watch_id", "provider", "flight_date"])
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("flight_date", sa.String(10), nullable=False),
        sa.Column("price", sa.Double, nullable=False),
        sa.Column("link", sa.Text),
        sa.Column("sent_at", ISO, nullable=False),
        **_OPTS,
    )
    op.create_index("idx_alerts", "alerts", ["watch_id", "provider", "flight_date"])
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("started_at", ISO, nullable=False),
        sa.Column("finished_at", ISO),
        sa.Column("ok", sa.Integer),
        sa.Column("n_prices", sa.Integer, nullable=False, server_default="0"),
        sa.Column("n_deals", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        **_OPTS,
    )


def downgrade() -> None:
    for table in ("runs", "alerts", "prices", "watches", "settings"):
        op.drop_table(table)
