"""Internal request protocol shared by SDK resources."""

from typing import Any, Dict, Optional, Protocol


class RequestClient(Protocol):
    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any: ...
