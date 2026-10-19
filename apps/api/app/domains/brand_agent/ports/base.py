"""Shared port plumbing: the "not available" error and module-path resolution."""

from __future__ import annotations

import importlib
import os
from typing import Any

from loguru import logger


class PortUnavailable(Exception):
    """The capability is not installed or not connected. ``reason`` is user-facing."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def load_port(env_name: str, default_path: str, stub: Any) -> Any:
    """The object at ``module:attr`` (env ``env_name`` overrides ``default_path``), else ``stub``.

    A missing or broken module never breaks the agent: it falls back to the stub
    (a missing one is the normal state before the other branch merges).
    """
    path = (os.environ.get(env_name) or default_path).strip()
    module_name, _, attr = path.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return stub
    except Exception as exc:  # noqa: BLE001 - a broken optional module must not break the agent
        logger.warning(f"brand agent port {path} failed to import: {type(exc).__name__}")
        return stub
    port = getattr(module, attr or "PORT", None)
    return port if port is not None else stub


__all__ = ["PortUnavailable", "load_port"]
