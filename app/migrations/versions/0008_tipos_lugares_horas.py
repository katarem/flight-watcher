"""1.9: tipos de transporte y de proveedor, lugares genéricos y horas en los precios.

- `watches.kind` y `provider_scripts.kind` (transporte de la vigilancia y tipo del proveedor): todo lo que ya había
  es de vuelos (`flight`).
- `prices.departs_at` / `prices.arrives_at`: salida y llegada del precio si la web las da (NULL en lo anterior).
- Los lugares reales (`prices.origin/destination`, `provider_routes.origin/destination` y la ruta de prueba de
  `provider_scripts`) pasan de 3 caracteres (IATA) a 10: estaciones, puertos y paradas tienen códigos más largos.

En SQLite, cambiar el tamaño de una columna recrea la tabla (`batch_alter_table`); `db.init()` desactiva antes las
claves foráneas para que el ON DELETE CASCADE no borre nada. En el resto de motores es un ALTER COLUMN.

Revisión: 0008
Anterior: 0007
Creada: 2026-10-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

NODE = sa.String(10)
IATA = sa.String(3)


def _resize(table: str, columns: tuple[str, ...], old, new, nullable: bool) -> None:
    with op.batch_alter_table(table) as batch:
        for col in columns:
            batch.alter_column(col, existing_type=old, type_=new, existing_nullable=nullable)


def upgrade() -> None:
    op.add_column("watches", sa.Column("kind", sa.String(10), nullable=False, server_default="flight"))
    op.add_column("provider_scripts", sa.Column("kind", sa.String(10), nullable=False, server_default="flight"))
    op.add_column("prices", sa.Column("departs_at", sa.String(16), nullable=True))
    op.add_column("prices", sa.Column("arrives_at", sa.String(16), nullable=True))
    _resize("prices", ("origin", "destination"), IATA, NODE, True)
    _resize("provider_routes", ("origin", "destination"), IATA, NODE, False)
    _resize("provider_scripts", ("health_origin", "health_destination"), IATA, NODE, False)


def downgrade() -> None:
    # Volver a 3 caracteres solo es posible si todo son aeropuertos (lo único que había antes de la 1.9).
    _resize("provider_scripts", ("health_origin", "health_destination"), NODE, IATA, False)
    _resize("provider_routes", ("origin", "destination"), NODE, IATA, False)
    _resize("prices", ("origin", "destination"), NODE, IATA, True)
    with op.batch_alter_table("prices") as batch:
        batch.drop_column("arrives_at")
        batch.drop_column("departs_at")
    with op.batch_alter_table("provider_scripts") as batch:
        batch.drop_column("kind")
    with op.batch_alter_table("watches") as batch:
        batch.drop_column("kind")
