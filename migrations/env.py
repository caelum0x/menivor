"""Alembic migration environment for ReelForge.

Resolves the database URL from ``config.neon.database_url`` (falling back to the
``NEON_DATABASE_URL`` environment variable) and targets
``app.models.db.base.Base.metadata`` for autogenerate. No secrets are stored in
``alembic.ini`` — everything is read at runtime.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import the declarative Base and every model module so that Base.metadata is
# fully populated before autogenerate compares it against the live database.
from app.models.db.base import Base
from app.models.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.models.db import render  # noqa: F401  (registers render_jobs on Base.metadata)
from app.models.db import clipmarket  # noqa: F401  (registers clip_campaigns/clip_submissions)
from app.models.db import gateway  # noqa: F401  (registers provisioning_keys/gateway_usage)
from app.models.db import templates as templates_model  # noqa: F401  (registers template_instances)
from app.models.db import characters as characters_model  # noqa: F401  (registers characters)
from app.models.db import canon as canon_model  # noqa: F401  (registers canons/canon_versions)
from app.models.db import character_refs as character_refs_model  # noqa: F401  (registers character_references)
from app.models.db import trends as trends_model  # noqa: F401  (registers trend_observations)
from app.models.db import film as film_model  # noqa: F401  (registers film_projects/film_shots)
from app.models.db import experiments as experiments_model  # noqa: F401  (registers experiments/variants)
from app.models.db import media_jobs as media_jobs_model  # noqa: F401  (registers media_jobs)
from app.models.db import series_runs as series_runs_model  # noqa: F401  (registers channel_runs/channel_clips)
from app.domains.adstudio import models as adstudio_model  # noqa: F401  (registers adstudio_projects/adstudio_variants)
from app.domains.beta import models as beta_model  # noqa: F401  (registers beta_access_requests)
from app.domains.social_inbox import models as social_inbox_model  # noqa: F401  (registers social_inbox_posts/threads)
from app.domains.design import models as design_model  # noqa: F401  (registers design_docs/design_templates)
from app.domains.content_month import models as content_month_model  # noqa: F401  (registers content_plans/content_ideas)
from app.domains.approvals import models as approvals_model  # noqa: F401  (registers approval_items)
from app.domains.approvals import settings_models as approvals_settings_model  # noqa: F401  (registers approval_feed_settings)
from app.domains.ads import allocation_models as ad_allocation_model  # noqa: F401  (registers ad_allocation_proposals)
from app.domains.capture import models as capture_model  # noqa: F401  (registers capture_jobs)
from app.domains.adstudio import catalog_models as store_catalog_model  # noqa: F401  (registers store_catalog_imports/products)
from app.domains.publishing.extended import channel_models as social_channel_model  # noqa: F401  (registers social_channel_credentials)
from app.domains.multipost import models as multipost_model  # noqa: F401  (registers multipost_* tables)
from app.domains.performance import models as performance_model  # noqa: F401  (registers tracked_posts/post_snapshots)
from app.domains.ott import models as ott_model  # noqa: F401  (registers ott_channels/ott_series/ott_titles/ott_collections)
from app.services.ott_transcode import models as ott_transcode_model  # noqa: F401  (registers ott_nodes/ott_encode_jobs/ott_content_keys)
from app.services.loops import preset_drop as preset_drop_model  # noqa: F401  (registers preset_drops)
from app.domains.ott_viewers import models as ott_viewers_model  # noqa: F401  (registers ott_viewers/ott_watch_progress/ott_usage_hours)
from app.domains.ott_commerce import models as ott_commerce_model  # noqa: F401  (registers ott_offers/ott_entitlements/ott_mint_events/ott_ads/ott_ad_settings)
from app.domains.ott_live import models as ott_live_model  # noqa: F401  (registers ott_live_streams/ott_chat_messages/ott_linear_channels)
from app.domains.ott_analytics import models as ott_analytics_model  # noqa: F401  (registers ott_beacons/ott_qoe_hourly)
from app.domains.ott import roles as ott_roles_model  # noqa: F401  (registers ott_channel_members)
from app.domains.ott_ai import models as ott_ai_model  # noqa: F401  (registers ott_ai_outputs)
from app.domains.ott_discovery import models as ott_discovery_model  # noqa: F401  (registers ott_title_embeddings)
from app.domains.ott import upload_check as ott_upload_check_model  # noqa: F401  (registers ott_upload_checks)

# Alembic Config object (values from alembic.ini).
config = context.config

# Configure Python logging from the ini file when present.
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        # Logging config is best-effort; never block migrations on it.
        pass

# Metadata for 'autogenerate' support.
target_metadata = Base.metadata


def _resolve_database_url() -> str:
    """Resolve the DB URL from app config, then env, then alembic.ini."""
    try:
        from app.config import config as app_config

        neon = getattr(app_config, "neon", None)
        if neon is not None:
            url = neon.get("database_url", "") or ""
            if url:
                return url
    except Exception:
        # Config may be unavailable in some CI contexts; fall through.
        pass

    env_url = (
        os.getenv("REELFORGE_DATABASE_URL", "")
        or os.getenv("NEON_DATABASE_URL", "")
        or os.getenv("DATABASE_URL", "")
    )
    if env_url:
        return env_url

    ini_url = config.get_main_option("sqlalchemy.url") or ""
    return ini_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB connection)."""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live database connection."""
    url = _resolve_database_url()
    if not url:
        raise RuntimeError(
            "No database URL configured for Alembic. Set "
            "REELFORGE_DATABASE_URL, NEON_DATABASE_URL, DATABASE_URL, or "
            "config.neon.database_url."
        )

    ini_section = config.get_section(config.config_ini_section) or {}
    ini_section["sqlalchemy.url"] = url

    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
