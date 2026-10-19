"""Official ad-library sources. One module per source; each returns :class:`TrackedAd` values."""

from app.domains.competitors.sources.base import SourceError, SourceNotConnected, TrackedAd

__all__ = ["SourceError", "SourceNotConnected", "TrackedAd"]
