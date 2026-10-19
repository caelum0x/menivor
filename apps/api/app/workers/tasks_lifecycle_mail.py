"""Money lifecycle mail sweep (MG5): payment failed, Autopilot paused, credits low.

Importing this module also subscribes the "Autopilot paused" mail to MN1's
``channel_paused`` signal in the worker process (where the beat-driven runner
runs), so a pause is mailed at once; the sweep catches anything missed.

Registration (hand-off to M1.5, the sole Wave B owner of ``celery_app.py``): add
``"app.workers.tasks_lifecycle_mail"`` to ``include`` and a beat entry::

    "lifecycle-mail-sweep": {
        "task": "app.workers.tasks_lifecycle_mail.lifecycle_mail_sweep_task",
        "schedule": 900.0,
    },

``MENIVOR_LIFECYCLE_MAIL=0`` turns the sweep off. Never raises.
"""

from __future__ import annotations

import os

from loguru import logger

from app.services.billing import lifecycle_mail
from app.workers.celery_app import celery_app

lifecycle_mail.install()


def sweep_enabled() -> bool:
    return (os.environ.get("MENIVOR_LIFECYCLE_MAIL") or "1").strip().lower() not in {"0", "false", "off"}


def lifecycle_mail_sweep() -> dict[str, int]:
    if not sweep_enabled():
        return {}
    try:
        return lifecycle_mail.sweep()
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"lifecycle mail sweep failed: {exc}")
        return {}


@celery_app.task(name="app.workers.tasks_lifecycle_mail.lifecycle_mail_sweep_task")
def lifecycle_mail_sweep_task() -> dict[str, int]:
    return lifecycle_mail_sweep()


__all__ = ["lifecycle_mail_sweep", "lifecycle_mail_sweep_task", "sweep_enabled"]
