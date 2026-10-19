"""Typed server-to-server client for Railyard Identity Lock.

Identity-bound media is fail-closed: Menivor resolves the exact locked version
before provider submission and only marks it attested after Identity Lock accepts
Mint's signed terminal settlement evidence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx


class IdentityLockError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class IdentityBinding:
    passport_id: str
    version: int
    content_digest: str
    provider: str
    modality: str
    conditioning: dict[str, Any]


@dataclass(frozen=True)
class IdentityOption:
    passport_id: str
    kind: str
    version: int
    content_digest: str
    status: str = "locked"


class IdentityLockClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"), transport=transport, timeout=timeout
        )

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        try:
            response = self._client.request(
                method,
                path,
                json=body,
                headers={"X-API-Key": self._api_key},
            )
        except httpx.RequestError as exc:
            raise IdentityLockError(502, f"Identity Lock unreachable: {exc}") from exc
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if 200 <= response.status_code < 300 and isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, (dict, list)):
                return data
            raise IdentityLockError(502, "Identity Lock returned an invalid envelope")
        message = f"Identity Lock error (status {response.status_code})"
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            message = str(payload["error"].get("message") or message)
        # Do not leak upstream internals as arbitrary status codes.
        status = response.status_code if 400 <= response.status_code < 500 else 502
        raise IdentityLockError(status, message)

    def list_locked(self, *, owner: str, limit: int = 100) -> list[IdentityOption]:
        """List immutable head versions owned by one Mint account.

        The list endpoint deliberately omits version assets/digests, so each
        locked head is read by exact version before it becomes selectable. This
        prevents a stale list row from silently selecting a later draft.
        """
        query = urlencode({"owner": owner, "limit": max(1, min(100, int(limit)))})
        rows = self._request("GET", f"/v1/passports?{query}")
        if not isinstance(rows, list):
            raise IdentityLockError(502, "Identity Lock returned an invalid passport list")
        result: list[IdentityOption] = []
        for row in rows:
            if not isinstance(row, dict) or str(row.get("owner", "")) != owner:
                continue
            if str(row.get("status", "")) != "locked":
                continue
            passport_id = str(row.get("id", "") or "")
            version = int(row.get("version", 0) or 0)
            if not passport_id or version <= 0:
                continue
            snapshot = self._request(
                "GET", f"/v1/passports/{passport_id}/versions/{version}"
            )
            digest = str(snapshot.get("content_digest", "") or "")
            if snapshot.get("status") != "locked" or not digest:
                continue
            result.append(
                IdentityOption(
                    passport_id=passport_id,
                    kind=str(row.get("kind", "") or "identity"),
                    version=version,
                    content_digest=digest,
                )
            )
        return result

    def prepare(
        self,
        *,
        passport_id: str,
        provider: str,
        modality: str,
        payer_account: str,
        version: int | None = None,
    ) -> IdentityBinding:
        passport = self._request("GET", f"/v1/passports/{passport_id}")
        if str(passport.get("owner", "")) != payer_account:
            raise IdentityLockError(
                409, "the selected passport is not owned by this Mint account"
            )
        request: dict[str, Any] = {"provider": provider, "modality": modality}
        if version is not None:
            request["version"] = int(version)
        conditioning = self._request(
            "POST", f"/v1/passports/{passport_id}/resolve", request
        )
        resolved_version = int(conditioning.get("version", 0) or 0)
        if resolved_version <= 0:
            raise IdentityLockError(502, "Identity Lock resolve omitted its version")
        snapshot = self._request(
            "GET", f"/v1/passports/{passport_id}/versions/{resolved_version}"
        )
        digest = str(snapshot.get("content_digest", "") or "")
        if snapshot.get("status") != "locked" or not digest:
            raise IdentityLockError(409, "Identity Lock resolved a mutable version")
        if str(conditioning.get("passport_id", "")) != passport_id:
            raise IdentityLockError(502, "Identity Lock resolve changed passport identity")
        if str(conditioning.get("provider", "")) != provider:
            raise IdentityLockError(502, "Identity Lock resolve changed provider")
        if str(conditioning.get("modality", "")) != modality:
            raise IdentityLockError(502, "Identity Lock resolve changed modality")
        return IdentityBinding(
            passport_id=passport_id,
            version=resolved_version,
            content_digest=digest,
            provider=provider,
            modality=modality,
            conditioning=conditioning,
        )

    def attest(
        self,
        binding: IdentityBinding,
        *,
        output_ref: str,
        asset_hash: str | None,
        request_id: str,
        payer_account: str,
        receipt: dict,
        settled_at_ms: int,
    ) -> dict:
        proof = {
            "sequence": int(receipt.get("seq", 0) or 0),
            "operation": str(receipt.get("op", "") or ""),
            "operation_hash": str(receipt.get("op_hash", "") or ""),
            "amount_micros": int(receipt.get("amount_micros", 0) or 0),
            "receipt_hash": str(receipt.get("hash", "") or ""),
            "signature": str(receipt.get("sig", "") or ""),
        }
        return self._request(
            "POST",
            f"/v1/passports/{binding.passport_id}/attest",
            {
                "provider": binding.provider,
                "modality": binding.modality,
                "version": binding.version,
                "output_ref": output_ref,
                "asset_hash": asset_hash,
                "settled_at_ms": int(settled_at_ms),
                "payment_evidence": {
                    "request_id": request_id,
                    "payer_account": payer_account,
                    "receipt": proof,
                },
            },
        )


def identity_lock_client_from_config() -> IdentityLockClient | None:
    base_url = os.getenv("IDENTITY_LOCK_URL", "").strip()
    api_key = os.getenv("IDENTITY_LOCK_API_KEY", "").strip()
    if not base_url and not api_key:
        return None
    if not base_url or not api_key:
        raise IdentityLockError(
            503, "Identity Lock requires both IDENTITY_LOCK_URL and IDENTITY_LOCK_API_KEY"
        )
    return IdentityLockClient(base_url, api_key)
