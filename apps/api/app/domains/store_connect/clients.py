"""App Store Connect + Google Play Developer API clients.

Both clients talk to the real provider REST APIs through a single injectable
:class:`Transport` seam (same pattern as
:mod:`app.domains.publishing.connectors.base`) so tests assert the exact
request shape without ever hitting a network.

App Store Connect auths with a short-lived ES256 JWT signed by the operator's
``.p8`` private key (https://developer.apple.com/documentation/appstoreconnectapi/generating-tokens-for-api-requests).
Google Play auths with a service-account bearer token minted by
``google-auth`` (https://developers.google.com/android-publisher). Neither
client ever logs a credential; errors carry only the HTTP status and the
provider's own (non-secret) error body.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

import jwt

_ASC_BASE = "https://api.appstoreconnect.apple.com/v1"
_PLAY_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"
_PLAY_SCOPES = ("https://www.googleapis.com/auth/androidpublisher",)


class StoreConnectError(RuntimeError):
    """A store-connect validation/read failed (bad credential, API rejection)."""

    def __init__(self, provider: str, message: str, *, status_code: int = 400) -> None:
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"[{provider}] {message}")


@runtime_checkable
class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


@runtime_checkable
class Transport(Protocol):
    """The single network seam both clients call."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        json: Any | None = None,
    ) -> HttpResponse: ...


class RequestsTransport:
    """Default :class:`Transport` backed by ``requests`` (lazy import)."""

    def __init__(self, timeout_s: float = 20.0) -> None:
        self._timeout = timeout_s

    def request(self, method, url, *, headers=None, params=None, json=None) -> HttpResponse:
        import requests

        return requests.request(method, url, headers=headers, params=params, json=json, timeout=self._timeout)


def _safe_json(resp: HttpResponse) -> dict:
    try:
        body = resp.json()
        return body if isinstance(body, dict) else {"data": body}
    except Exception:
        return {}


def _status_code_for(status_code: int, provider: str, body: dict) -> int:
    if status_code >= 500:
        return 502
    if status_code in (401, 403):
        return 401
    return 400


# --------------------------------------------------------------------------- #
# App Store Connect
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AppStoreCredentials:
    """The three values on an App Store Connect API key (Users and Access ->
    Integrations -> App Store Connect API): issuer id, key id, and the ``.p8``
    private key's full PEM text (``-----BEGIN PRIVATE KEY-----...``)."""

    issuer_id: str
    key_id: str
    private_key_pem: str


class AppStoreConnectClient:
    """Minimal App Store Connect API client: auth + apps + versions + reviews.

    https://developer.apple.com/documentation/appstoreconnectapi
    """

    def __init__(
        self,
        creds: AppStoreCredentials,
        *,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._creds = creds
        self._transport = transport or RequestsTransport()
        self._clock = clock

    def _token(self) -> str:
        now = int(self._clock())
        payload = {
            "iss": self._creds.issuer_id,
            "iat": now,
            # Apple rejects a JWT whose exp is more than 20 minutes out.
            "exp": now + 1190,
            "aud": "appstoreconnect-v1",
        }
        try:
            return jwt.encode(
                payload, self._creds.private_key_pem, algorithm="ES256",
                headers={"kid": self._creds.key_id, "typ": "JWT"},
            )
        except Exception as exc:  # noqa: BLE001 - surfaced as a clean, typed error
            raise StoreConnectError(
                "appstore", f"could not sign the App Store Connect key: {exc}"
            ) from exc

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self._transport.request(
            "GET", f"{_ASC_BASE}{path}", headers={"Authorization": f"Bearer {self._token()}"}, params=params,
        )
        status = int(getattr(resp, "status_code", 0))
        if not (200 <= status < 300):
            body = _safe_json(resp)
            raise StoreConnectError(
                "appstore",
                f"App Store Connect rejected the request (HTTP {status}): {body}",
                status_code=_status_code_for(status, "appstore", body),
            )
        return _safe_json(resp)

    def validate(self) -> None:
        """Raise :class:`StoreConnectError` when the key cannot authenticate."""
        self._get("/apps", {"limit": "1"})

    def list_apps(self) -> list[dict]:
        """``[{"id","name","bundle_id"}]`` for every app this key can see."""
        body = self._get("/apps", {"limit": "200", "fields[apps]": "name,bundleId,sku"})
        return [
            {
                "id": str(app.get("id") or ""),
                "name": str((app.get("attributes") or {}).get("name") or ""),
                "bundle_id": str((app.get("attributes") or {}).get("bundleId") or ""),
            }
            for app in (body.get("data") or [])
            if isinstance(app, dict) and app.get("id")
        ]

    def latest_version(self, app_id: str) -> dict | None:
        """The newest App Store version's string + review state, or ``None``."""
        body = self._get(f"/apps/{app_id}/appStoreVersions", {"limit": "1", "sort": "-createdDate"})
        rows = [r for r in (body.get("data") or []) if isinstance(r, dict)]
        if not rows:
            return None
        attrs = rows[0].get("attributes") or {}
        return {"version": str(attrs.get("versionString") or ""), "state": str(attrs.get("appStoreState") or "")}

    def rating_summary(self, app_id: str, *, sample: int = 50) -> dict:
        """Average of the most recent customer-review star ratings.

        The App Store Connect API has no single "average rating" field — this
        is computed client-side from a bounded recent sample, so it is an
        approximation of (not identical to) the star average shown on the App
        Store product page.
        """
        body = self._get(
            f"/apps/{app_id}/customerReviews", {"limit": str(min(max(sample, 1), 200)), "sort": "-createdDate"},
        )
        ratings = [
            int((row.get("attributes") or {}).get("rating") or 0)
            for row in (body.get("data") or [])
            if isinstance(row, dict) and (row.get("attributes") or {}).get("rating")
        ]
        return {
            "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "sample_size": len(ratings),
            "approximate": True,
        }


# --------------------------------------------------------------------------- #
# Google Play Developer API
# --------------------------------------------------------------------------- #
class PlayDeveloperClient:
    """Minimal Android Publisher API client: auth + edits + tracks + reviews.

    https://developers.google.com/android-publisher

    The Play Developer API has NO endpoint that lists every app a service
    account can manage (unlike App Store Connect's ``/v1/apps``) — a caller
    must already know the package name. Each package is therefore registered
    one at a time (see :func:`app.domains.store_connect.service.add_play_app`).
    """

    def __init__(
        self,
        service_account_info: dict,
        *,
        transport: Transport | None = None,
        credentials_factory: Callable[[dict], Any] | None = None,
    ) -> None:
        self._info = service_account_info
        self._transport = transport or RequestsTransport()
        self._credentials_factory = credentials_factory

    def _credentials(self) -> Any:
        if self._credentials_factory is not None:
            return self._credentials_factory(self._info)
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_info(self._info, scopes=list(_PLAY_SCOPES))

    def _token(self) -> str:
        try:
            creds = self._credentials()
            from google.auth.transport.requests import Request

            creds.refresh(Request())
            return str(creds.token or "")
        except StoreConnectError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as a clean, typed error
            raise StoreConnectError(
                "play", f"could not authenticate the Play service account: {exc}"
            ) from exc

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}"}

    def _handle(self, resp: HttpResponse, *, allow_empty: bool = False) -> dict:
        status = int(getattr(resp, "status_code", 0))
        if not (200 <= status < 300):
            body = _safe_json(resp)
            raise StoreConnectError(
                "play",
                f"Play Developer API rejected the request (HTTP {status}): {body}",
                status_code=_status_code_for(status, "play", body),
            )
        if allow_empty and int(getattr(resp, "status_code", 0)) == 204:
            return {}
        return _safe_json(resp)

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._handle(self._transport.request("GET", f"{_PLAY_BASE}{path}", headers=self._headers(), params=params))

    def _post(self, path: str, body: dict) -> dict:
        return self._handle(self._transport.request("POST", f"{_PLAY_BASE}{path}", headers=self._headers(), json=body))

    def _delete(self, path: str) -> None:
        self._handle(
            self._transport.request("DELETE", f"{_PLAY_BASE}{path}", headers=self._headers()), allow_empty=True,
        )

    def validate(self) -> None:
        """Raise :class:`StoreConnectError` when the key cannot authenticate.

        Minting an access token is the only universal "is this key good" check
        available without already knowing a package name.
        """
        self._token()

    def current_version(self, package_name: str) -> dict:
        """Open, read, and discard a Play "edit" to read the production
        track's latest release (version code / name). Edits are Play's unit
        of change; a read-only edit is opened and immediately dropped (never
        committed) so this never risks publishing anything."""
        edit = self._post(f"/applications/{package_name}/edits", {})
        edit_id = str(edit.get("id") or "")
        if not edit_id:
            raise StoreConnectError("play", f"Play did not return an edit id for {package_name!r}")
        try:
            body = self._get(f"/applications/{package_name}/edits/{edit_id}/tracks/production")
            releases = [r for r in (body.get("releases") or []) if isinstance(r, dict)]
            version_codes = [c for r in releases for c in (r.get("versionCodes") or [])]
            version_name = next((str(r.get("name")) for r in releases if r.get("name")), "")
            return {
                "version_code": str(version_codes[0]) if version_codes else None,
                "version_name": version_name,
                "track": "production",
            }
        finally:
            try:
                self._delete(f"/applications/{package_name}/edits/{edit_id}")
            except StoreConnectError:
                pass  # best-effort cleanup; an orphaned read-only edit expires on its own

    def rating_summary(self, package_name: str, *, sample: int = 50) -> dict:
        """Average of the most recent review star ratings (client-computed;
        see :meth:`AppStoreConnectClient.rating_summary` for the same caveat)."""
        body = self._get(f"/applications/{package_name}/reviews", {"maxResults": str(min(max(sample, 1), 100))})
        ratings: list[int] = []
        for review in (body.get("reviews") or []):
            if not isinstance(review, dict):
                continue
            for comment in review.get("comments") or []:
                rating = ((comment or {}).get("userComment") or {}).get("starRating")
                if rating:
                    ratings.append(int(rating))
        return {
            "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
            "sample_size": len(ratings),
            "approximate": True,
        }
