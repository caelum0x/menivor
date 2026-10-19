"""AI B-roll studio: broll_presets (curated motion presets) + seed globals

Revision ID: d9b2c4e17f38
Revises: c8a1f2e94d67
Create Date: 2026-08-14 02:00:00.000000+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9b2c4e17f38'
down_revision: Union[str, None] = 'c8a1f2e94d67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Curated GLOBAL motion presets (user_id NULL => visible to everyone). Each is a
# starter prompt + default params under a friendly name; ``workflow_id`` is left
# empty so generation uses the operator's configured default comfyui-deploy
# deployment for the mode. Deterministic ids so a re-run/downgrade is idempotent.
_SEED_PRESETS = [
    {
        "id": "brollpreset000000000000000aerial",
        "name": "Cinematic Aerial",
        "description": "Slow drone push-in over a sweeping landscape.",
        "mode": "t2v",
        "prompt_template": (
            "cinematic aerial drone shot slowly pushing in over {subject}, "
            "golden hour, volumetric light, ultra sharp, film grain"
        ),
        "default_params": {"motion_strength": 0.6},
    },
    {
        "id": "brollpreset000000000000000neonci",
        "name": "Neon City Night",
        "description": "Rain-slick neon street with reflective pavement.",
        "mode": "t2v",
        "prompt_template": (
            "slow tracking shot down a neon-lit {subject} street at night, "
            "rain-slick reflective pavement, shallow depth of field, cyberpunk"
        ),
        "default_params": {"motion_strength": 0.5},
    },
    {
        "id": "brollpreset0000000000000macropro",
        "name": "Macro Product",
        "description": "Tight rotating macro on a product surface.",
        "mode": "t2v",
        "prompt_template": (
            "extreme macro rotating shot of {subject}, soft studio lighting, "
            "glossy reflections, crisp detail, shallow depth of field"
        ),
        "default_params": {"motion_strength": 0.35},
    },
    {
        "id": "brollpreset00000000000000natflow",
        "name": "Nature Flow",
        "description": "Gentle push across water, mist, and foliage.",
        "mode": "t2v",
        "prompt_template": (
            "gentle camera push across {subject}, flowing water, drifting mist, "
            "lush foliage, soft morning light, serene"
        ),
        "default_params": {"motion_strength": 0.45},
    },
    {
        "id": "brollpreset0000000000000imgparal",
        "name": "Photo Parallax (i2v)",
        "description": "Subtle 3D parallax push on your reference image.",
        "mode": "i2v",
        "prompt_template": "subtle 3d parallax camera push, gentle motion, cinematic",
        "default_params": {"motion_strength": 0.3},
    },
]


def upgrade() -> None:
    # BRAND-NEW table — additive, safe on a populated DB; existing rows/tests are
    # unaffected. Every NOT NULL column declares its ``server_default`` so the row
    # shape is self-describing and autogenerate reports no drift.
    op.create_table(
        'broll_presets',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=True),
        sa.Column('provider', sa.String(length=40), server_default=sa.text("'comfyui'"), nullable=False),
        sa.Column('workflow_id', sa.String(length=128), server_default=sa.text("''"), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.String(length=512), server_default=sa.text("''"), nullable=False),
        sa.Column('mode', sa.String(length=8), server_default=sa.text("'t2v'"), nullable=False),
        sa.Column('prompt_template', sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column('thumbnail_url', sa.String(length=512), server_default=sa.text("''"), nullable=False),
        sa.Column('default_params', sa.JSON(), nullable=True),
        sa.Column('is_public', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_broll_presets_user_id'), 'broll_presets', ['user_id'], unique=False)

    # Seed the curated GLOBAL presets (user_id NULL, is_public TRUE). Bulk insert
    # with explicit ids so the seed is idempotent under a re-run.
    presets_table = sa.table(
        'broll_presets',
        sa.column('id', sa.String),
        sa.column('user_id', sa.String),
        sa.column('provider', sa.String),
        sa.column('workflow_id', sa.String),
        sa.column('name', sa.String),
        sa.column('description', sa.String),
        sa.column('mode', sa.String),
        sa.column('prompt_template', sa.Text),
        sa.column('thumbnail_url', sa.String),
        sa.column('default_params', sa.JSON),
        sa.column('is_public', sa.Boolean),
        sa.column('is_active', sa.Boolean),
    )
    op.bulk_insert(
        presets_table,
        [
            {
                "id": p["id"],
                "user_id": None,
                "provider": "comfyui",
                "workflow_id": "",
                "name": p["name"],
                "description": p["description"],
                "mode": p["mode"],
                "prompt_template": p["prompt_template"],
                "thumbnail_url": "",
                # Pass the raw dict — the sa.JSON column serializes it on write
                # (json.dumps here would double-encode into a JSON string).
                "default_params": p["default_params"],
                "is_public": True,
                "is_active": True,
            }
            for p in _SEED_PRESETS
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_broll_presets_user_id'), table_name='broll_presets')
    op.drop_table('broll_presets')
