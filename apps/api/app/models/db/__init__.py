"""ReelForge persistence layer (SQLAlchemy 2.0 + Alembic).

Exposes the declarative ``Base``, the lazily-initialized engine / session
factory (``base``), the ORM models (``models``) and the repository layer
(``repositories``). See ``docs/reelforge/INTEGRATION_CONTRACT.md`` §4.
"""

from app.models.db.base import Base, SessionLocal, get_engine, get_session

__all__ = [
    "Base",
    "SessionLocal",
    "get_engine",
    "get_session",
]
