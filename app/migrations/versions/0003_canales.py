"""Canales de aviso como lista por usuario: tablas channels y watch_channels.

Los webhook/token/chat que había en la fila de cada usuario pasan a ser canales («Discord», «Telegram»)
enlazados a todas las vigilancias de ese usuario, y las columnas se eliminan. El downgrade recupera
solo la estructura (las columnas quedan vacías: un usuario puede tener varios canales).

Revisión: 0003
Anterior: 0002
Creada: 2026-10-01
"""
from __future__ import annotations

import json
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_OPTS = {"mysql_charset": "utf8mb4"}


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("config", sa.Text, nullable=False),
        sa.Column("enabled", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(32), nullable=False),
        **_OPTS,
    )
    op.create_index("idx_channels_user", "channels", ["user_id"])
    op.create_table(
        "watch_channels",
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watches.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("channel_id", sa.Integer, sa.ForeignKey("channels.id", ondelete="CASCADE"), primary_key=True),
        **_OPTS,
    )

    # Datos: cada canal antiguo del usuario se enlaza a todas sus vigilancias.
    con = op.get_bind()
    users = sa.table("users", sa.column("id"), sa.column("discord_webhook"), sa.column("telegram_token"),
                     sa.column("telegram_chat_id"))
    watches = sa.table("watches", sa.column("id"), sa.column("user_id"))
    channels = sa.Table("channels", sa.MetaData(), sa.Column("id", sa.Integer, primary_key=True),
                        sa.Column("user_id", sa.Integer), sa.Column("kind", sa.String), sa.Column("name", sa.String),
                        sa.Column("config", sa.Text), sa.Column("enabled", sa.Integer), sa.Column("created_at", sa.String))
    links = sa.table("watch_channels", sa.column("watch_id"), sa.column("channel_id"))
    now = datetime.now().isoformat(timespec="seconds")
    for u in con.execute(sa.select(users)).mappings().all():
        found = []
        if u["discord_webhook"]:
            found.append(("discord", "Discord", {"webhook": u["discord_webhook"]}))
        if u["telegram_token"] and u["telegram_chat_id"]:
            found.append(("telegram", "Telegram", {"token": u["telegram_token"], "chat_id": u["telegram_chat_id"]}))
        watch_ids = con.execute(sa.select(watches.c.id).where(watches.c.user_id == u["id"])).scalars().all()
        for kind, name, config in found:
            cid = con.execute(sa.insert(channels).values(
                user_id=u["id"], kind=kind, name=name, config=json.dumps(config), enabled=1, created_at=now,
            )).inserted_primary_key[0]
            if watch_ids:
                con.execute(sa.insert(links), [{"watch_id": w, "channel_id": cid} for w in watch_ids])

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("discord_webhook")
        batch_op.drop_column("telegram_chat_id")
        batch_op.drop_column("telegram_token")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("telegram_token", sa.String(200), server_default="", nullable=False))
        batch_op.add_column(sa.Column("telegram_chat_id", sa.String(50), server_default="", nullable=False))
        batch_op.add_column(sa.Column("discord_webhook", sa.String(500), server_default="", nullable=False))
    op.drop_table("watch_channels")
    op.drop_index("idx_channels_user", table_name="channels")
    op.drop_table("channels")
