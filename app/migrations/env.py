"""Entorno de Alembic: usa el motor y el esquema de app.db (mismas variables DB_*).

La app lo invoca desde db.init() pasando su conexión en `config.attributes["connection"]`;
la CLI (`alembic ...` desde la raíz del repo) abre una propia con el motor de app.db.
"""
from __future__ import annotations

from alembic import context

from app import db


def _run(con):
    context.configure(
        connection=con,
        target_metadata=db.metadata,
        render_as_batch=con.dialect.name == "sqlite",  # SQLite apenas soporta ALTER TABLE
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Modo offline (--sql) no soportado: las migraciones se aplican contra la BD configurada.")

_con = context.config.attributes.get("connection")
if _con is None:
    with db.engine.begin() as _con:
        _run(_con)
else:
    _run(_con)
