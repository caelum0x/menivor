"""Errors shared by the enhance lanes (MH7)."""

from __future__ import annotations


class EnhanceError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
