"""ReelForge Celery worker package (INTEGRATION_CONTRACT.md §6).

Holds the Celery application (``celery_app``), the JSON-serialisable shared
``JobContext`` passed between chain stages (``context``), the stage tasks that
wrap ``app.services.reelforge`` stage functions (``tasks``), and the
DAG-building / enqueue helpers (``pipeline``).

The submodules are intentionally NOT imported here: importing this package must
not require Celery to be installed or Redis to be reachable. Import the concrete
module you need (e.g. ``from app.workers.pipeline import start_pipeline``).
"""

__all__ = [
    "celery_app",
    "context",
    "pipeline",
    "tasks",
]
