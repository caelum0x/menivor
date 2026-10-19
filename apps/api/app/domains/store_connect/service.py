"""Phase 3 "Connect your store": validate → encrypt → persist → read.

A creator pastes an App Store Connect API key (issuer id, key id, ``.p8``
private key) or a Google Play service-account JSON. The credential is
validated against the real provider (one cheap authenticated call — see
:mod:`.clients`) BEFORE it is ever persisted, then encrypted with
:mod:`app.services.crypto_tokens` (the same Fernet helper that already
protects Direct-Publish OAuth tokens — reused here rather than inventing a
second encryption scheme) and stored via
:class:`~app.models.db.repositories.StoreConnectionRepository`.

The first feature built on top (``list_appstore_apps`` / ``add_play_app`` /
``list_play_apps``) returns each connected app's id/name, current version, and
an approximate rating — the same shape the App Store Audit tool
(``/tools/app-store-audit``) consumes, so a connected account's own apps slot
straight into that flow instead of requiring a manual bundle-id/package-name
lookup. Import-safe: a missing DB layer raises a clean 503 at call time rather
than breaking app startup (same pattern as
:mod:`app.domains.publishing.extended.connections`).
"""

from __future__ import annotations

import json
from typing import Any, Callable

from app.services import crypto_tokens

from .clients import (
    AppStoreConnectClient,
    AppStoreCredentials,
    PlayDeveloperClient,
    StoreConnectError,
    Transport,
)

try:
    from app.models.db.base import get_session
    from app.models.db.repositories import StoreConnectionRepository

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - import-safe; callers get a clear 503
    get_session = None  # type: ignore[assignment]
    StoreConnectionRepository = None  # type: ignore[assignment]
    _IMPORT_ERROR = exc


def require_ready() -> None:
    if get_session is None or StoreConnectionRepository is None:
        raise StoreConnectError(
            "store_connect", f"store-connect persistence unavailable: {_IMPORT_ERROR}", status_code=503,
        )
    if not crypto_tokens.is_configured():
        raise StoreConnectError(
            "store_connect", "store connections are not set up on this server (token key missing)", status_code=503,
        )


def _enc(value: str) -> str:
    return crypto_tokens.encrypt(value)  # type: ignore[union-attr]


def _dec(blob: str) -> str:
    return crypto_tokens.decrypt(blob)  # type: ignore[union-attr]


def connection_record(row: Any) -> dict:
    return {
        "provider": row.provider,
        "account_name": row.account_name or "",
        "status": row.status,
        "status_note": row.status_note or "",
        "connected_at": row.connected_at.isoformat() if row.connected_at else None,
        "package_names": list((row.meta or {}).get("package_names", [])) if row.provider == "play" else None,
    }


# --------------------------------------------------------------------------- #
# Connect
# --------------------------------------------------------------------------- #
def connect_appstore(
    user_id: str, issuer_id: str, key_id: str, private_key_pem: str, *, transport: Transport | None = None,
) -> dict:
    """Validate an App Store Connect API key against Apple, then store it."""
    require_ready()
    issuer_id = (issuer_id or "").strip()
    key_id = (key_id or "").strip()
    private_key_pem = (private_key_pem or "").strip()
    if not issuer_id or not key_id or not private_key_pem:
        raise StoreConnectError(
            "appstore", "the issuer ID, key ID, and the .p8 private key are all required", status_code=400,
        )
    if "PRIVATE KEY" not in private_key_pem:
        raise StoreConnectError("appstore", "that doesn't look like a .p8 private key (expected a PEM block)",
                                 status_code=400)
    creds = AppStoreCredentials(issuer_id=issuer_id, key_id=key_id, private_key_pem=private_key_pem)
    AppStoreConnectClient(creds, transport=transport).validate()  # raises on a bad key
    blob = json.dumps({"issuer_id": issuer_id, "key_id": key_id, "private_key_pem": private_key_pem})
    with get_session() as session:  # type: ignore[misc]
        row = StoreConnectionRepository(session).upsert(  # type: ignore[misc]
            user_id=user_id, provider="appstore", credentials_enc=_enc(blob), account_name=issuer_id,
            status="connected",
        )
        return connection_record(row)


def connect_play(
    user_id: str, service_account_json: str, *, transport: Transport | None = None,
    credentials_factory: Callable[[dict], Any] | None = None,
) -> dict:
    """Validate a Play service-account JSON against Google, then store it."""
    require_ready()
    raw = (service_account_json or "").strip()
    if not raw:
        raise StoreConnectError("play", "paste the Play service-account JSON key's contents", status_code=400)
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StoreConnectError("play", f"that isn't valid JSON: {exc}", status_code=400) from exc
    if (
        not isinstance(info, dict)
        or info.get("type") != "service_account"
        or not str(info.get("client_email") or "").strip()
        or not str(info.get("private_key") or "").strip()
    ):
        raise StoreConnectError("play", "that doesn't look like a Google service-account JSON key", status_code=400)
    PlayDeveloperClient(info, transport=transport, credentials_factory=credentials_factory).validate()
    with get_session() as session:  # type: ignore[misc]
        row = StoreConnectionRepository(session).upsert(  # type: ignore[misc]
            user_id=user_id, provider="play", credentials_enc=_enc(json.dumps(info)),
            account_name=str(info.get("client_email") or ""), status="connected", meta={"package_names": []},
        )
        return connection_record(row)


# --------------------------------------------------------------------------- #
# Read / disconnect
# --------------------------------------------------------------------------- #
def list_connections(user_id: str) -> list[dict]:
    require_ready()
    with get_session() as session:  # type: ignore[misc]
        return [connection_record(row) for row in StoreConnectionRepository(session).list_for_user(user_id)]  # type: ignore[misc]


def disconnect(user_id: str, provider: str) -> bool:
    require_ready()
    with get_session() as session:  # type: ignore[misc]
        return StoreConnectionRepository(session).delete(user_id, provider)  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# First feature: apps + current version + ratings (feeds App Store Audit)
# --------------------------------------------------------------------------- #
def _load_appstore_credentials(user_id: str) -> AppStoreCredentials:
    with get_session() as session:  # type: ignore[misc]
        row = StoreConnectionRepository(session).get(user_id, "appstore")  # type: ignore[misc]
        if row is None:
            raise StoreConnectError("appstore", "connect an App Store Connect key first", status_code=409)
        blob = json.loads(_dec(row.credentials_enc))
    return AppStoreCredentials(**blob)


def list_appstore_apps(user_id: str, *, transport: Transport | None = None) -> list[dict]:
    """Every app this ASC key can see, with its current version + an approximate rating."""
    require_ready()
    client = AppStoreConnectClient(_load_appstore_credentials(user_id), transport=transport)
    out: list[dict] = []
    for app in client.list_apps():
        version = client.latest_version(app["id"]) or {"version": "", "state": ""}
        rating = client.rating_summary(app["id"])
        out.append({**app, **version, **rating})
    return out


def _load_play_connection(user_id: str) -> tuple[dict, list[str]]:
    with get_session() as session:  # type: ignore[misc]
        row = StoreConnectionRepository(session).get(user_id, "play")  # type: ignore[misc]
        if row is None:
            raise StoreConnectError("play", "connect a Play service account first", status_code=409)
        info = json.loads(_dec(row.credentials_enc))
        packages = list((row.meta or {}).get("package_names", []))
    return info, packages


def add_play_app(
    user_id: str, package_name: str, *, transport: Transport | None = None,
    credentials_factory: Callable[[dict], Any] | None = None,
) -> dict:
    """Register a package name (Play has no "list all my apps" endpoint) and read it once.

    Every subsequent :func:`list_play_apps` call re-reads every registered
    package name, so this both validates the package is reachable with this
    service account AND adds it to the creator's tracked list.
    """
    require_ready()
    package_name = (package_name or "").strip()
    if not package_name or "." not in package_name or " " in package_name:
        raise StoreConnectError("play", "enter a valid Android package name (e.g. com.example.app)", status_code=400)
    info, packages = _load_play_connection(user_id)
    client = PlayDeveloperClient(info, transport=transport, credentials_factory=credentials_factory)
    version = client.current_version(package_name)
    rating = client.rating_summary(package_name)
    if package_name not in packages:
        packages = [*packages, package_name]
    with get_session() as session:  # type: ignore[misc]
        repo = StoreConnectionRepository(session)  # type: ignore[misc]
        current = repo.get(user_id, "play")
        if current is None:
            raise StoreConnectError("play", "connect a Play service account first", status_code=409)
        repo.upsert(
            user_id=user_id, provider="play", credentials_enc=current.credentials_enc,
            account_name=current.account_name, status="connected", meta={"package_names": packages},
        )
    return {"package_name": package_name, **version, **rating}


def list_play_apps(
    user_id: str, *, transport: Transport | None = None, credentials_factory: Callable[[dict], Any] | None = None,
) -> list[dict]:
    """Every registered package name's current version + an approximate rating."""
    require_ready()
    info, packages = _load_play_connection(user_id)
    if not packages:
        return []
    client = PlayDeveloperClient(info, transport=transport, credentials_factory=credentials_factory)
    out: list[dict] = []
    for package_name in packages:
        version = client.current_version(package_name)
        rating = client.rating_summary(package_name)
        out.append({"package_name": package_name, **version, **rating})
    return out
