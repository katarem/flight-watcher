"""Usuarios y vigilancias por usuario: tabla users y watches.user_id.

user_id queda nullable: en una BD con datos previas las vigilancias existentes se asignan al
administrador al arrancar (db.bootstrap_admin), que también recoge los canales de aviso globales.

Revisión: 0002
Anterior: 0001
Creada: 2026-10-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=10), server_default='user', nullable=False),
    sa.Column('enabled', sa.Integer(), server_default='1', nullable=False),
    sa.Column('avatar', sa.String(length=100), nullable=True),
    sa.Column('discord_webhook', sa.String(length=500), server_default='', nullable=False),
    sa.Column('telegram_token', sa.String(length=200), server_default='', nullable=False),
    sa.Column('telegram_chat_id', sa.String(length=50), server_default='', nullable=False),
    sa.Column('notify_errors', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    mysql_charset='utf8mb4'
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index('ux_users_username', ['username'], unique=True)

    with op.batch_alter_table('watches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_index('idx_watches_user', ['user_id'], unique=False)
        batch_op.create_foreign_key('fk_watches_user_id', 'users', ['user_id'], ['id'], ondelete='CASCADE')



def downgrade() -> None:
    with op.batch_alter_table('watches', schema=None) as batch_op:
        batch_op.drop_constraint('fk_watches_user_id', type_='foreignkey')
        batch_op.drop_index('idx_watches_user')
        batch_op.drop_column('user_id')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index('ux_users_username')

    op.drop_table('users')
