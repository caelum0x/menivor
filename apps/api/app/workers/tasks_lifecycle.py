"""Onboarding lifecycle mail tick (MR3): Day 0/1/3/7, stops after payment.

Registered by the M-1 steward in ``celery_app.py`` (include plus an hourly
beat entry ``onboarding-mail-tick``). ``MENIVOR_ONBOARDING_MAIL=0`` turns it
off. Never raises.
"""

from __future__ import annotations

import os

from loguru import logger

from app.services.lifecycle import sequence
from app.workers.celery_app import celery_app


def enabled() -> bool:
    return (os.environ.get("MENIVOR_ONBOARDING_MAIL") or "1").strip().lower() not in {"0", "false", "off"}


def onboarding_mail_tick() -> dict[str, int]:
    if not enabled():
        return {}
    try:
        return sequence.run()
    except Exception as exc:  # noqa: BLE001 - a beat tick must never crash the worker
        logger.error(f"onboarding mail tick failed: {exc}")
        return {}


@celery_app.task(name="app.workers.tasks_lifecycle.onboarding_mail_tick_task")
def onboarding_mail_tick_task() -> dict[str, int]:
    return onboarding_mail_tick()


__all__ = ["enabled", "onboarding_mail_tick", "onboarding_mail_tick_task"]
