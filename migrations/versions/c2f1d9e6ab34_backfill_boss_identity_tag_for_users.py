"""backfill boss identity tag for users

Revision ID: c2f1d9e6ab34
Revises: eb5dd5c67a9d
Create Date: 2026-03-02 13:05:00.000000

"""
import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2f1d9e6ab34'
down_revision = 'eb5dd5c67a9d'
branch_labels = None
depends_on = None


def _normalize_tags(raw_tags):
    if not raw_tags:
        tags = []
    else:
        try:
            parsed = json.loads(raw_tags)
            tags = parsed if isinstance(parsed, list) else []
        except Exception:
            tags = []

    seen = set()
    cleaned = []
    for t in tags:
        s = str(t).strip()
        if s and s not in seen:
            cleaned.append(s)
            seen.add(s)
    if '老板' not in seen:
        cleaned.append('老板')
    return cleaned


def upgrade():
    bind = op.get_bind()
    users = sa.table(
        'users',
        sa.column('id', sa.Integer),
        sa.column('tags', sa.Text),
    )
    rows = bind.execute(sa.select(users.c.id, users.c.tags)).fetchall()
    for row in rows:
        normalized = _normalize_tags(row.tags)
        bind.execute(
            sa.update(users)
            .where(users.c.id == row.id)
            .values(tags=json.dumps(normalized, ensure_ascii=False))
        )


def downgrade():
    # 仅数据回填，无安全可逆操作
    pass
