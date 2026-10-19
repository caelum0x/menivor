"""Real ``httpx`` client to the live **mint-server**, injectable + config-gated.

This is the Mint-settlement rail for the ReelForge wallet (ADR-0001/0002): a job
holds its quoted max on Mint at reserve, captures the measured actual to the
treasury on success, and releases the hold on failure. Every amount is a bare
integer microdollar — ReelForge micros *are* Mint micros, no conversion.

The client never opens a socket at import time: the constructor accepts an
already-built ``httpx.Client`` (or a ``transport`` for tests), and a module-level
factory (:func:`mint_client_from_config`) builds the real one lazily and caches
it for the process. When ``MINT_SERVER_URL`` is unset, :func:`mint_enabled`
returns ``False`` and every caller falls back to the local microdollar ledger
unchanged.

Errors reuse the bridge's :class:`WalletBridgeError` so the create-time HTTP
surface and worker logs behave exactly like the local-ledger path. Mint status
codes pass straight through (402 insufficient/reserve, 409 idempotency, 422
capture>hold/expired, 403 frozen/KYC); a transport failure/timeout maps to a
clean ``502`` so a reserve returns a 5xx and the best-effort worker wrapper logs
it without crashing the pipeline.
"""

import base64
import binascii
import json
import threading
from typing import Any

import httpx

from app.domains.reels.wallet_bridge import WalletBridgeError

# Default per-request timeout (seconds) when the caller does not override it.
_DEFAULT_TIMEOUT = 10.0


class MintClient:
    """A thin, injectable HTTP client over the mint-server ``/v1`` money routes."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        treasury_account: str,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.treasury_account = treasury_account
        if client is not None:
            # Tests inject a MockTransport-backed client; no socket is opened.
            self._client = client
        else:
            # Real runtime: a live socket to mint-server (satisfies no-stub rule).
            self._client = httpx.Client(
                base_url=base_url,
                headers={"x-api-key": api_key},
                timeout=timeout,
                transport=transport,
            )

    # ------------------------------------------------------------------ #
    # Envelope helpers
    # ------------------------------------------------------------------ #
    def _headers(self) -> dict[str, str] | None:
        # Send x-api-key on every request so an injected bare client is
        # authenticated too (and the header is observable in tests).
        return {"x-api-key": self.api_key} if self.api_key else None

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        data, _ = self._post_with_headers(path, body)
        return data

    def _post_with_headers(
        self, path: str, body: dict[str, Any]
    ) -> tuple[Any, httpx.Headers]:
        try:
            response = self._client.post(path, json=body, headers=self._headers())
        except httpx.RequestError as exc:
            raise WalletBridgeError(502, f"mint unreachable: {exc}") from exc
        return self._parse(response), response.headers

    def _get(self, path: str) -> Any:
        try:
            response = self._client.get(path, headers=self._headers())
        except httpx.RequestError as exc:
            raise WalletBridgeError(502, f"mint unreachable: {exc}") from exc
        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        """Return ``data`` on a ``{success:true}`` 2xx; else raise mapped error."""
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if (
            200 <= response.status_code < 300
            and isinstance(payload, dict)
            and payload.get("success")
        ):
            return payload.get("data")
        message = f"mint error (status {response.status_code})"
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                message = str(error["message"])
        raise WalletBridgeError(response.status_code, message)

    # ------------------------------------------------------------------ #
    # Accounts
    # ------------------------------------------------------------------ #
    def create_account(self, kind: str = "User", owner_ref: str | None = None) -> str:
        """Create a Mint account and return its ``acct_...`` id."""
        data = self._post("/v1/accounts", {"kind": kind, "owner_ref": owner_ref})
        return str(data["account_id"])

    def read_balance(self, account_id: str) -> dict:
        """Return ``{account_id, available_micros, held_micros, updated_seq}``."""
        return self._get(f"/v1/accounts/{account_id}/balance")

    def create_address(self, account_id: str, purpose: str = "receive") -> str:
        """Create a public Mint routing address for ``account_id``.

        The ``ait1...`` address is safe to share as a destination. It is not a
        credential and cannot authorize a debit from the owning account.
        """
        data = self._post(f"/v1/accounts/{account_id}/addresses", {"purpose": purpose})
        return str(data["address"])

    def lookup_address(self, address: str) -> str:
        """Resolve a public Mint address to its authoritative account id."""
        data = self._get(f"/v1/addresses/{address}")
        return str(data["account_id"])

    def mint_deposit(
        self,
        account_id: str,
        amount_micros: int,
        deposit_ref: str,
        idem_key: str,
    ) -> dict:
        """Credit a provider-confirmed deposit to ``account_id`` exactly once.

        ``deposit_ref`` is provider-namespaced (for example
        ``creem:checkout_123``). The live Mint reserve independently re-queries
        that provider reference before it changes supply, so a verified Menivor
        webhook is correlation evidence rather than the money trust boundary.
        Mint de-duplicates on the deposit reference; ``idem_key`` identifies the
        caller attempt and may safely change on a retry.
        """
        return self._post(
            "/v1/mint",
            {
                "to": account_id,
                "amount_micros": int(amount_micros),
                "deposit_ref": deposit_ref,
                "idem_key": idem_key,
            },
        )

    def transfer(
        self,
        from_account: str,
        to_account: str,
        amount_micros: int,
        idem_key: str,
        ref: str | None = None,
    ) -> dict:
        """Move AI tokens exactly once to an account id or public address.

        ``from_account`` remains an authoritative account id selected only
        after Menivor's ownership/RBAC checks. ``to_account`` may be either an
        ``acct_...`` id or a shareable ``ait1...`` receive address.
        """
        return self._post(
            "/v1/transfers",
            {
                "from": from_account,
                "to": to_account,
                "amount_micros": int(amount_micros),
                "idem_key": idem_key,
                "ref": ref,
            },
        )

    # ------------------------------------------------------------------ #
    # Holds (reserve -> capture / release)
    # ------------------------------------------------------------------ #
    def create_hold(
        self,
        from_account: str,
        amount_micros: int,
        idem_key: str,
        ref: str | None = None,
    ) -> dict:
        """HOLD ``amount_micros`` on ``from_account`` and return the hold receipt."""
        return self._post(
            "/v1/holds",
            {
                "from": from_account,
                "amount_micros": int(amount_micros),
                "idem_key": idem_key,
                "ref": ref,
            },
        )

    def capture_hold(
        self,
        hold_id: str,
        amount_micros: int,
        to: str,
        idem_key: str,
        ref: str | None = None,
    ) -> dict:
        """CAPTURE ``amount_micros`` of a hold to account ``to`` (the treasury)."""
        return self._post(
            f"/v1/holds/{hold_id}/capture",
            {
                "amount_micros": int(amount_micros),
                "to": to,
                "idem_key": idem_key,
                "ref": ref,
            },
        )

    def capture_hold_with_receipt(
        self,
        hold_id: str,
        amount_micros: int,
        to: str,
        idem_key: str,
        ref: str | None = None,
    ) -> tuple[dict, dict]:
        """Capture and return both the hold view and Mint's signed receipt.

        Identity-bound media must carry this proof into Identity Lock; a 2xx
        response without it is therefore a hard protocol failure.
        """
        data, headers = self._post_with_headers(
            f"/v1/holds/{hold_id}/capture",
            {
                "amount_micros": int(amount_micros),
                "to": to,
                "idem_key": idem_key,
                "ref": ref,
            },
        )
        self._validate_terminal_hold_data(data, hold_id, "capture")
        receipt = self._decode_settlement_receipt(
            headers,
            operation="hold.capture",
            amount_micros=int(amount_micros),
        )
        return data, receipt

    def release_hold(self, hold_id: str, idem_key: str, ref: str | None = None) -> dict:
        """RELEASE the uncaptured remainder of a hold back to the payer."""
        return self._post(
            f"/v1/holds/{hold_id}/release",
            {"idem_key": idem_key, "ref": ref},
        )

    def release_hold_with_receipt(
        self,
        hold_id: str,
        amount_micros: int,
        idem_key: str,
        ref: str | None = None,
    ) -> tuple[dict, dict]:
        """Release a hold and require Mint's authentic signed terminal receipt."""
        data, headers = self._post_with_headers(
            f"/v1/holds/{hold_id}/release",
            {"idem_key": idem_key, "ref": ref},
        )
        self._validate_terminal_hold_data(data, hold_id, "release")
        receipt = self._decode_settlement_receipt(
            headers,
            operation="hold.release",
            amount_micros=int(amount_micros),
        )
        return data, receipt

    @staticmethod
    def _validate_terminal_hold_data(data: Any, hold_id: str, verb: str) -> None:
        if not isinstance(data, dict) or str(data.get("hold_id", "")) != hold_id:
            raise WalletBridgeError(
                502, f"mint {verb} response does not match the requested hold"
            )

    @staticmethod
    def _decode_settlement_receipt(
        headers: httpx.Headers,
        *,
        operation: str,
        amount_micros: int,
    ) -> dict:
        """Decode and validate Mint's flat signed ``AITP-Receipt`` exactly.

        Signature verification remains Mint's trust boundary; this client
        requires the complete signed/hash-linked wire proof and binds its
        operation and amount to the terminal request before persistence.
        """
        encoded = headers.get("aitp-receipt", "").strip()
        if not encoded:
            raise WalletBridgeError(502, f"mint {operation} returned no signed receipt")
        try:
            if "=" in encoded:
                raise ValueError("receipt must use canonical unpadded base64url")
            decoded = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4),
                altchars=b"-_",
                validate=True,
            )
            if (
                base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
                != encoded
            ):
                raise ValueError("receipt is not canonical base64url")
            receipt = json.loads(decoded)
        except (binascii.Error, UnicodeDecodeError, ValueError, TypeError) as exc:
            raise WalletBridgeError(
                502, f"mint {operation} returned an invalid receipt"
            ) from exc
        if not isinstance(receipt, dict):
            raise WalletBridgeError(
                502, f"mint {operation} returned an invalid receipt"
            )

        seq = receipt.get("seq")
        amount = receipt.get("amount_micros")
        if (
            isinstance(seq, bool)
            or not isinstance(seq, int)
            or seq <= 0
            or isinstance(amount, bool)
            or not isinstance(amount, int)
            or amount != int(amount_micros)
            or receipt.get("op") != operation
            or not isinstance(receipt.get("op_hash"), str)
            or not receipt["op_hash"]
            or not isinstance(receipt.get("hash"), str)
            or not receipt["hash"]
            or not isinstance(receipt.get("sig"), str)
            or not receipt["sig"]
        ):
            raise WalletBridgeError(
                502, f"mint {operation} receipt does not match the terminal operation"
            )
        return receipt

    def get_hold(self, hold_id: str) -> dict:
        """Read a hold (reconcile / introspection)."""
        return self._get(f"/v1/holds/{hold_id}")


# --------------------------------------------------------------------------- #
# Config gate + process-cached factory
# --------------------------------------------------------------------------- #
_CACHE_LOCK = threading.Lock()
_cached_client: MintClient | None = None


def mint_enabled() -> bool:
    """True when a mint-server URL is configured (else the local ledger is used)."""
    from app.config import config

    return bool(config.mint.get("server_url"))


def mint_client_from_config() -> MintClient | None:
    """Return the process-cached :class:`MintClient`, or ``None`` when disabled.

    Requires ``MINT_SERVER_URL`` plus ``MINT_API_KEY`` and
    ``MINT_TREASURY_ACCOUNT``; when any is missing the caller falls back to the
    local microdollar ledger unchanged.
    """
    global _cached_client
    from app.config import config

    server_url = config.mint.get("server_url")
    api_key = config.mint.get("api_key")
    treasury = config.mint.get("treasury_account")
    if not server_url or not api_key or not treasury:
        return None
    with _CACHE_LOCK:
        if _cached_client is None:
            try:
                timeout = float(config.mint.get("timeout_seconds", _DEFAULT_TIMEOUT))
            except (TypeError, ValueError):
                timeout = _DEFAULT_TIMEOUT
            _cached_client = MintClient(
                str(server_url), str(api_key), str(treasury), timeout=timeout
            )
        return _cached_client


def reset_mint_client_cache() -> None:
    """Drop the process-cached client (config changed / tests)."""
    global _cached_client
    with _CACHE_LOCK:
        _cached_client = None
