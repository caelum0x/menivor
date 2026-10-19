"""Device attestation for the mobile free grant (MN3).

A new anonymous device account starts with 0 credits. Its one-time free
credits are granted only when the install proves it is the real app on a real
device, or when the account links a verified identity (Apple / Google):

* iOS: Apple App Attest. The app asks ``POST /auth/device/challenge`` for a
  challenge, calls ``DCAppAttestService.attestKey(keyId, SHA256(challenge))``
  and sends ``{key_id, attestation, challenge}``. The attestation is verified
  here in full: the x5c chain to Apple's App Attestation root CA, the nonce
  extension, the key id, the RP id hash (``TEAMID.bundle``), a zero counter and
  the production (or, when configured, development) AAGUID.
* Android: Play Integrity. The app requests a token with the challenge as the
  nonce and sends ``{integrity_token, challenge}``. The token is decoded by
  Google's ``decodeIntegrityToken`` API with a service account (free tier) and
  must show the right package, the same nonce, a fresh timestamp,
  ``PLAY_RECOGNIZED`` and ``MEETS_DEVICE_INTEGRITY``.

Challenges are stateless: ``b64url(ts | random | HMAC(secret, ...))`` bound to
the platform and install id and valid for 10 minutes.

Configuration (all optional; a missing key makes that platform report
``available: false`` and the grant waits for an identity link instead):

* ``APPLE_APP_ATTEST_APP_ID``     ``TEAMID.com.arhansuba.menivor``
* ``APPLE_APP_ATTEST_ROOT_CA``    PEM text or a file path (Apple's
  ``Apple_App_Attestation_Root_CA.pem``)
* ``APPLE_APP_ATTEST_ENV``        ``production`` (default) or ``development``
* ``PLAY_INTEGRITY_PACKAGE``      Android package name
* ``PLAY_INTEGRITY_SERVICE_ACCOUNT`` service-account JSON text or a file path
* ``MENIVOR_DEVICE_GRANT_GATE``   ``attest`` (default) or ``off`` (the old
  immediate grant; kept only as an owner rollback switch)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger

CHALLENGE_TTL_S = 600
_CHALLENGE_TAG = b"menivor-attest-v1"
_NONCE_OID = "1.2.840.113635.100.8.2"
_NONCE_PREFIX = bytes([0x30, 0x24, 0xA1, 0x22, 0x04, 0x20])
_AAGUID_PROD = b"appattest" + b"\x00" * 7
_AAGUID_DEV = b"appattestdevelop"
_PLAY_SCOPE = "https://www.googleapis.com/auth/playintegrity"
_HTTP_TIMEOUT_S = 10.0

#: Request budget for ``/auth/device`` (Redis, falling back to an in-process
#: bucket when Redis is down, so the limit always holds).
IP_REQUESTS_PER_WINDOW = 60
NET_REQUESTS_PER_WINDOW = 240
REQUEST_WINDOW_S = 600

_DEFAULT_TRUSTED_PROXIES = (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "100.64.0.0/10", "::1/128", "fc00::/7",
)


@dataclass(frozen=True)
class AttestResult:
    passed: bool
    provider: str
    reason: str = ""
    #: A stable per-install key (App Attest key id) used to refuse re-use.
    device_key: str = ""


class AttestationError(ValueError):
    """The attestation is invalid (the message is safe to log, not to show)."""


# --------------------------------------------------------------------------- #
# Flags
# --------------------------------------------------------------------------- #
def grant_gate_enabled() -> bool:
    return os.getenv("MENIVOR_DEVICE_GRANT_GATE", "attest").strip().lower() != "off"


def availability() -> dict[str, bool]:
    return {"ios": _apple_configured(), "android": _play_configured()}


# --------------------------------------------------------------------------- #
# Client address (behind Caddy / Cloudflare)
# --------------------------------------------------------------------------- #
def _trusted_networks() -> list[Any]:
    raw = os.getenv("MENIVOR_TRUSTED_PROXIES", "").strip()
    items = [p.strip() for p in raw.split(",") if p.strip()] if raw else list(_DEFAULT_TRUSTED_PROXIES)
    nets = []
    for item in items:
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            logger.warning(f"MENIVOR_TRUSTED_PROXIES: ignoring {item!r}")
    return nets


def _is_trusted(ip: str, nets: list[Any]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in nets)


def _valid_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return ""


def client_ip(request: Any) -> str:
    """The caller's address. Forwarding headers are trusted only from a proxy.

    uvicorn runs without ``--proxy-headers``, so ``request.client.host`` is the
    reverse proxy. When that peer is a trusted proxy, ``CF-Connecting-IP`` is
    used, else the right-most untrusted ``X-Forwarded-For`` hop.
    """
    client = getattr(request, "client", None)
    peer = _valid_ip(str(getattr(client, "host", "") or "")) if client else ""
    nets = _trusted_networks()
    if not peer or not _is_trusted(peer, nets):
        return peer
    headers = getattr(request, "headers", {}) or {}
    cf = _valid_ip(str(headers.get("cf-connecting-ip") or ""))
    if cf:
        return cf
    hops = [h for h in (x.strip() for x in str(headers.get("x-forwarded-for") or "").split(",")) if h]
    for hop in reversed(hops):
        ip = _valid_ip(hop)
        if ip and not _is_trusted(ip, nets):
            return ip
    return _valid_ip(hops[0]) if hops else peer


def enforce_request_budget(request_id: str, ip: str) -> None:
    """429 when one address or its network calls ``/auth/device`` too often."""
    from app.models.exception import HttpException
    from app.services.abuse.grant_markers import network_of
    from app.services.ratelimit import rate_limit

    if not ip:
        return
    checks = (
        (f"device_auth:ip:{ip}", IP_REQUESTS_PER_WINDOW),
        (f"device_auth:net:{network_of(ip)}", NET_REQUESTS_PER_WINDOW),
    )
    for key, limit in checks:
        result = rate_limit(key, limit, REQUEST_WINDOW_S)
        if not result.allowed:
            raise HttpException(
                task_id=request_id,
                status_code=429,
                message=f"{request_id}: too many sign-in attempts from this network; retry in {result.reset_s}s",
                data={"code": "device_rate_limited", "reset_s": result.reset_s},
            )


# --------------------------------------------------------------------------- #
# Challenges
# --------------------------------------------------------------------------- #
def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    text = str(value or "").strip()
    text = text.replace("-", "+").replace("_", "/")
    return base64.b64decode(text + "=" * (-len(text) % 4))


def _challenge_mac(secret: bytes, platform: str, install_id: str, body: bytes) -> bytes:
    msg = _CHALLENGE_TAG + b"|" + platform.encode() + b"|" + install_id.encode() + b"|" + body
    return hmac.new(secret, msg, hashlib.sha256).digest()[:16]


def issue_challenge(secret: bytes, platform: str, install_id: str, *, now: float | None = None) -> str:
    body = struct.pack(">Q", int(now if now is not None else time.time())) + os.urandom(16)
    return _b64u(body + _challenge_mac(secret, platform, install_id, body))


def check_challenge(
    secret: bytes, platform: str, install_id: str, challenge: str, *, now: float | None = None
) -> None:
    try:
        raw = _unb64(challenge)
    except (ValueError, TypeError) as exc:
        raise AttestationError("challenge is not base64") from exc
    if len(raw) != 40:
        raise AttestationError("challenge has the wrong length")
    body, mac = raw[:24], raw[24:]
    if not hmac.compare_digest(mac, _challenge_mac(secret, platform, install_id, body)):
        raise AttestationError("challenge was not issued for this install")
    issued = struct.unpack(">Q", body[:8])[0]
    age = (now if now is not None else time.time()) - issued
    if age < -60 or age > CHALLENGE_TTL_S:
        raise AttestationError("challenge expired")


# --------------------------------------------------------------------------- #
# Minimal CBOR (the App Attest attestation object)
# --------------------------------------------------------------------------- #
def _cbor_len(data: bytes, pos: int, info: int) -> tuple[int, int]:
    if info < 24:
        return info, pos
    sizes = {24: 1, 25: 2, 26: 4, 27: 8}
    if info not in sizes:
        raise AttestationError("unsupported CBOR length")
    n = sizes[info]
    if pos + n > len(data):
        raise AttestationError("truncated CBOR")
    return int.from_bytes(data[pos:pos + n], "big"), pos + n


def _cbor_item(data: bytes, pos: int, depth: int = 0) -> tuple[Any, int]:
    if depth > 16 or pos >= len(data):
        raise AttestationError("malformed CBOR")
    head = data[pos]
    major, info = head >> 5, head & 0x1F
    pos += 1
    if major == 7:
        simple = {20: False, 21: True, 22: None}
        if info in simple:
            return simple[info], pos
        raise AttestationError("unsupported CBOR simple value")
    value, pos = _cbor_len(data, pos, info)
    if major == 0:
        return value, pos
    if major == 1:
        return -1 - value, pos
    if major in (2, 3):
        end = pos + value
        if end > len(data):
            raise AttestationError("truncated CBOR string")
        chunk = data[pos:end]
        return (chunk if major == 2 else chunk.decode("utf-8")), end
    if major == 4:
        items = []
        for _ in range(value):
            item, pos = _cbor_item(data, pos, depth + 1)
            items.append(item)
        return items, pos
    if major == 5:
        out = {}
        for _ in range(value):
            key, pos = _cbor_item(data, pos, depth + 1)
            out[key], pos = _cbor_item(data, pos, depth + 1)
        return out, pos
    if major == 6:
        return _cbor_item(data, pos, depth + 1)
    raise AttestationError("unsupported CBOR type")


def cbor_loads(data: bytes) -> Any:
    item, _ = _cbor_item(bytes(data), 0)
    return item


# --------------------------------------------------------------------------- #
# Apple App Attest
# --------------------------------------------------------------------------- #
def _read_value(env: str) -> str:
    raw = os.getenv(env, "").strip()
    if raw and not raw.startswith(("-----", "{")) and os.path.isfile(raw):
        with open(raw, encoding="utf-8") as handle:
            return handle.read()
    return raw


def _apple_configured() -> bool:
    return bool(os.getenv("APPLE_APP_ATTEST_APP_ID", "").strip() and _read_value("APPLE_APP_ATTEST_ROOT_CA"))


def _apple_root():
    from cryptography import x509

    pem = _read_value("APPLE_APP_ATTEST_ROOT_CA")
    if not pem:
        raise AttestationError("App Attest root CA is not configured")
    return x509.load_pem_x509_certificate(pem.encode("utf-8"))


def _check_validity(cert: Any, now: datetime) -> None:
    if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
        raise AttestationError("certificate is outside its validity period")


def verify_app_attest(
    *, key_id: str, attestation: str, challenge: str, app_id: str, root: Any,
    allow_development: bool = False, now: datetime | None = None,
) -> str:
    """Verify an App Attest attestation; returns the key id (hex) on success."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    when = now or datetime.now(timezone.utc)
    try:
        key_raw = _unb64(key_id)
        obj = cbor_loads(_unb64(attestation))
    except (ValueError, TypeError) as exc:
        raise AttestationError("attestation is not decodable") from exc
    if not isinstance(obj, dict) or obj.get("fmt") != "apple-appattest":
        raise AttestationError("not an App Attest attestation")
    stmt, auth = obj.get("attStmt") or {}, obj.get("authData") or b""
    x5c = stmt.get("x5c") if isinstance(stmt, dict) else None
    if not isinstance(x5c, list) or len(x5c) < 2 or not isinstance(auth, bytes) or len(auth) < 55:
        raise AttestationError("attestation is missing fields")

    cred = x509.load_der_x509_certificate(x5c[0])
    inter = x509.load_der_x509_certificate(x5c[1])
    try:
        inter.verify_directly_issued_by(root)
        cred.verify_directly_issued_by(inter)
    except Exception as exc:  # noqa: BLE001 - any chain failure is a rejection
        raise AttestationError("certificate chain does not lead to Apple") from exc
    for cert in (cred, inter, root):
        _check_validity(cert, when)

    client_hash = hashlib.sha256(challenge.encode("utf-8")).digest()
    nonce = hashlib.sha256(auth + client_hash).digest()
    try:
        ext = cred.extensions.get_extension_for_oid(x509.ObjectIdentifier(_NONCE_OID)).value
        ext_bytes = bytes(ext.value)
    except Exception as exc:  # noqa: BLE001
        raise AttestationError("nonce extension missing") from exc
    if not (ext_bytes[:6] == _NONCE_PREFIX and len(ext_bytes) == 38 and hmac.compare_digest(ext_bytes[6:], nonce)):
        raise AttestationError("nonce does not match")

    point = cred.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    if not hmac.compare_digest(hashlib.sha256(point).digest(), key_raw):
        raise AttestationError("key id does not match the attested key")
    if not hmac.compare_digest(auth[:32], hashlib.sha256(app_id.encode("utf-8")).digest()):
        raise AttestationError("attestation is for another app")
    if struct.unpack(">I", auth[33:37])[0] != 0:
        raise AttestationError("counter must be 0")
    aaguid = auth[37:53]
    if aaguid != _AAGUID_PROD and not (allow_development and aaguid == _AAGUID_DEV):
        raise AttestationError("attestation environment is not allowed")
    cred_len = struct.unpack(">H", auth[53:55])[0]
    if not hmac.compare_digest(auth[55:55 + cred_len], key_raw):
        raise AttestationError("credential id does not match the key id")
    return key_raw.hex()


# --------------------------------------------------------------------------- #
# Google Play Integrity
# --------------------------------------------------------------------------- #
_token_lock = threading.Lock()
_token_cache: dict[str, Any] = {}


def _play_configured() -> bool:
    return bool(os.getenv("PLAY_INTEGRITY_PACKAGE", "").strip() and _read_value("PLAY_INTEGRITY_SERVICE_ACCOUNT"))


def _service_account() -> dict[str, Any]:
    raw = _read_value("PLAY_INTEGRITY_SERVICE_ACCOUNT")
    if not raw:
        raise AttestationError("Play Integrity service account is not configured")
    return json.loads(raw)


def _google_access_token(account: dict[str, Any], http_post: Any) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    with _token_lock:
        cached = _token_cache.get("token")
        if cached and _token_cache.get("exp", 0) > time.time() + 60:
            return str(cached)
    token_uri = str(account.get("token_uri") or "https://oauth2.googleapis.com/token")
    now = int(time.time())
    header = _b64u(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64u(json.dumps({
        "iss": account["client_email"], "scope": _PLAY_SCOPE, "aud": token_uri,
        "iat": now, "exp": now + 3600,
    }).encode())
    key = serialization.load_pem_private_key(account["private_key"].encode("utf-8"), password=None)
    signature = key.sign(f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    body = http_post(token_uri, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": f"{header}.{claims}.{_b64u(signature)}",
    })
    token = str(body.get("access_token") or "")
    if not token:
        raise AttestationError("Google token exchange failed")
    with _token_lock:
        _token_cache.update(token=token, exp=now + int(body.get("expires_in") or 3000))
    return token


def _http_post(url: str, *, data: dict | None = None, json_body: dict | None = None, token: str = "") -> dict:
    import httpx

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = httpx.post(url, data=data, json=json_body, headers=headers, timeout=_HTTP_TIMEOUT_S)
    if resp.status_code >= 400:
        raise AttestationError(f"Google API returned {resp.status_code}")
    return resp.json()


def check_play_verdict(payload: dict[str, Any], *, package: str, challenge: str, now_ms: int | None = None) -> None:
    """Apply the acceptance rules to a decoded ``tokenPayloadExternal``."""
    details = payload.get("requestDetails") or {}
    if details.get("requestPackageName") != package:
        raise AttestationError("integrity token is for another package")
    if str(details.get("nonce") or "").rstrip("=") != challenge.rstrip("="):
        raise AttestationError("integrity nonce does not match")
    stamp = int(details.get("timestampMillis") or 0)
    current = now_ms if now_ms is not None else int(time.time() * 1000)
    if abs(current - stamp) > CHALLENGE_TTL_S * 1000:
        raise AttestationError("integrity token is stale")
    app = payload.get("appIntegrity") or {}
    if app.get("appRecognitionVerdict") != "PLAY_RECOGNIZED":
        raise AttestationError("app is not the Play-distributed build")
    device = payload.get("deviceIntegrity") or {}
    if "MEETS_DEVICE_INTEGRITY" not in (device.get("deviceRecognitionVerdict") or []):
        raise AttestationError("device does not meet integrity")


def verify_play_integrity(*, integrity_token: str, challenge: str, http_post: Any = None) -> None:
    post = http_post or _http_post
    package = os.getenv("PLAY_INTEGRITY_PACKAGE", "").strip()
    account = _service_account()
    token = _google_access_token(account, lambda url, data: post(url, data=data))
    decoded = post(
        f"https://playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken",
        json_body={"integrity_token": integrity_token},
        token=token,
    )
    check_play_verdict(decoded.get("tokenPayloadExternal") or {}, package=package, challenge=challenge)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def verify(secret: bytes, platform: str, install_id: str, attestation: dict[str, Any] | None) -> AttestResult:
    """Verify an install's attestation. Never raises; failures are ``passed=False``."""
    provider = "app_attest" if platform == "ios" else "play_integrity"
    if not attestation:
        return AttestResult(False, provider, "no attestation sent")
    challenge = str(attestation.get("challenge") or "")
    try:
        check_challenge(secret, platform, install_id, challenge)
        if platform == "ios":
            if not _apple_configured():
                return AttestResult(False, provider, "App Attest is not configured")
            key_hex = verify_app_attest(
                key_id=str(attestation.get("key_id") or ""),
                attestation=str(attestation.get("attestation") or ""),
                challenge=challenge,
                app_id=os.getenv("APPLE_APP_ATTEST_APP_ID", "").strip(),
                root=_apple_root(),
                allow_development=os.getenv("APPLE_APP_ATTEST_ENV", "production").strip().lower() == "development",
            )
            return AttestResult(True, provider, device_key=key_hex)
        if not _play_configured():
            return AttestResult(False, provider, "Play Integrity is not configured")
        verify_play_integrity(integrity_token=str(attestation.get("integrity_token") or ""), challenge=challenge)
        return AttestResult(True, provider)
    except AttestationError as exc:
        logger.info(f"device attestation rejected ({provider}): {exc}")
        return AttestResult(False, provider, str(exc))
    except Exception as exc:  # noqa: BLE001 - provider outage: no grant, no crash
        logger.warning(f"device attestation error ({provider}): {type(exc).__name__}: {exc}")
        return AttestResult(False, provider, "attestation could not be checked")


__all__ = [
    "AttestResult",
    "AttestationError",
    "CHALLENGE_TTL_S",
    "availability",
    "cbor_loads",
    "check_challenge",
    "check_play_verdict",
    "client_ip",
    "enforce_request_budget",
    "grant_gate_enabled",
    "issue_challenge",
    "verify",
    "verify_app_attest",
    "verify_play_integrity",
]
