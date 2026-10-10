"""Proveedores por vigilancia con su cobertura, caché de rutas, salud de proveedores, escalas y monedas.

- `watch_providers` sustituye a la columna CSV `watches.providers`: cada proveedor de una vigilancia con
  los pares de aeropuertos reales que cubre, si está activo y cuándo se comprobó. Las vigilancias actuales
  se convierten con todos los pares de su origen y destino (TCI = TFN + TFS), sin comprobar todavía.
- `provider_routes` (caché de cobertura) y `provider_health` (última prueba de acceso de cada proveedor).
- `watches.origin/destination` admiten ciudades, países y grupos (hasta 40 caracteres) y `watches.max_stops`
  limita las escalas (las vigilancias actuales quedan en 0: solo directos, como hasta ahora).
- `prices.orig_price` (precio en la moneda original; `price` sigue en euros) y `prices.stops`.

Revisión: 0004
Anterior: 0003
Creada: 2026-10-10
"""
from __future__ import annotations

import json
from itertools import product

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_OPTS = {"mysql_charset": "utf8mb4"}
# Foto de los códigos de ciudad que admitía la app hasta esta versión (no importar app.places aquí).
_METRO = {"TCI": ("TFN", "TFS")}


def _pairs(origin: str, destination: str) -> list[str]:
    return [f"{o}-{d}" for o, d in product(_METRO.get(origin, (origin,)), _METRO.get(destination, (destination,)))
            if o != d]


def upgrade() -> None:
    op.create_table(
        "watch_providers",
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watches.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("provider", sa.String(50), primary_key=True),
        sa.Column("routes", sa.Text, nullable=False),
        sa.Column("active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("checked_at", sa.String(32)),
        **_OPTS,
    )
    op.create_table(
        "provider_routes",
        sa.Column("provider", sa.String(50), primary_key=True),
        sa.Column("origin", sa.String(3), primary_key=True),
        sa.Column("destination", sa.String(3), primary_key=True),
        sa.Column("operated", sa.Integer, nullable=False),
        sa.Column("checked_at", sa.String(32), nullable=False),
        **_OPTS,
    )
    op.create_table(
        "provider_health",
        sa.Column("provider", sa.String(50), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("detail", sa.Text, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("checked_at", sa.String(32), nullable=False),
        **_OPTS,
    )

    # Datos: el CSV de proveedores pasa a filas de watch_providers.
    con = op.get_bind()
    watches = sa.table("watches", sa.column("id"), sa.column("origin"), sa.column("destination"),
                       sa.column("providers"), sa.column("max_stops"))
    links = sa.table("watch_providers", sa.column("watch_id"), sa.column("provider"), sa.column("routes"),
                     sa.column("active"), sa.column("checked_at"))
    rows = []
    for w in con.execute(sa.select(watches.c.id, watches.c.origin, watches.c.destination, watches.c.providers)).mappings():
        routes = json.dumps(_pairs(w["origin"], w["destination"]))
        for key in dict.fromkeys(p.strip() for p in (w["providers"] or "").split(",") if p.strip()):
            rows.append({"watch_id": w["id"], "provider": key, "routes": routes, "active": 1, "checked_at": None})
    if rows:
        con.execute(sa.insert(links), rows)

    with op.batch_alter_table("watches") as batch_op:
        batch_op.add_column(sa.Column("max_stops", sa.Integer))
        batch_op.alter_column("origin", existing_type=sa.String(3), type_=sa.String(40), existing_nullable=False)
        batch_op.alter_column("destination", existing_type=sa.String(3), type_=sa.String(40), existing_nullable=False)
        batch_op.drop_column("providers")
    con.execute(sa.update(watches).values(max_stops=0))

    with op.batch_alter_table("prices") as batch_op:
        batch_op.add_column(sa.Column("orig_price", sa.Double))
        batch_op.add_column(sa.Column("stops", sa.Integer))


def downgrade() -> None:
    with op.batch_alter_table("prices") as batch_op:
        batch_op.drop_column("stops")
        batch_op.drop_column("orig_price")

    with op.batch_alter_table("watches") as batch_op:
        batch_op.add_column(sa.Column("providers", sa.String(200), nullable=False, server_default="vueling"))
    con = op.get_bind()
    watches = sa.table("watches", sa.column("id"), sa.column("providers"))
    links = sa.table("watch_providers", sa.column("watch_id"), sa.column("provider"))
    by_watch: dict[int, list[str]] = {}
    for wid, key in con.execute(sa.select(links.c.watch_id, links.c.provider).order_by(links.c.provider)).all():
        by_watch.setdefault(wid, []).append(key)
    for wid, keys in by_watch.items():
        con.execute(sa.update(watches).where(watches.c.id == wid).values(providers=",".join(keys)))
    # Las ciudades, países y grupos no caben en 3 letras: el downgrade solo es seguro con aeropuertos y TCI.
    with op.batch_alter_table("watches") as batch_op:
        batch_op.drop_column("max_stops")
        batch_op.alter_column("origin", existing_type=sa.String(40), type_=sa.String(3), existing_nullable=False)
        batch_op.alter_column("destination", existing_type=sa.String(40), type_=sa.String(3), existing_nullable=False)

    op.drop_table("provider_health")
    op.drop_table("provider_routes")
    op.drop_table("watch_providers")
