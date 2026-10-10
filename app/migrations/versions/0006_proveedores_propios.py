"""Proveedores propios: tabla provider_scripts (scripts de Python escritos desde el panel).

Solo añade una tabla nueva: no toca las existentes ni sus datos.

Revisión: 0006
Anterior: 0005
Creada: 2026-10-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_OPTS = {"mysql_charset": "utf8mb4"}


def upgrade() -> None:
    op.create_table(
        "provider_scripts",
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("coverage", sa.String(20), nullable=False),
        sa.Column("max_routes", sa.Integer),
        sa.Column("health_origin", sa.String(3), nullable=False),
        sa.Column("health_destination", sa.String(3), nullable=False),
        sa.Column("link_template", sa.Text, nullable=False),
        sa.Column("notes", sa.Text, nullable=False),
        sa.Column("min_interval", sa.Double, nullable=False, server_default="1.5"),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("enabled", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("updated_by", sa.String(32), nullable=False),
        **_OPTS,
    )


def downgrade() -> None:
    op.drop_table("provider_scripts")
