"""Proveedores como scripts: columna provider_scripts.source (enlace del paquete del que se importó).

Solo añade una columna que admite NULL: no recrea la tabla ni toca datos. Crear los proveedores incluidos
(Vueling y Ryanair) y pasarles las plantillas de enlace de Ajustes lo hace `providers.bundle.seed()` al arrancar.

Revisión: 0007
Anterior: 0006
Creada: 2026-10-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_scripts", sa.Column("source", sa.String(500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("provider_scripts") as batch:
        batch.drop_column("source")
