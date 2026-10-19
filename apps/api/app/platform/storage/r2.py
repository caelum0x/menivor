"""Cloudflare R2 platform adapter (S3-compatible, via boto3).

Implements the storage interface from INTEGRATION_CONTRACT.md §2.7.

R2 is reached through boto3's S3 client with a custom ``endpoint_url``
(``https://<account_id>.r2.cloudflarestorage.com``), ``region_name="auto"``
and SigV4 signing (mandatory for R2 presigned URLs).

boto3 is an optional dependency at import time: the import is guarded here so
that merely importing this module never crashes the pipeline. The clear
``RuntimeError`` is raised only when an :class:`R2Client` is actually
instantiated without boto3 installed.
"""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from loguru import logger

from app.config import config

try:  # boto3 is optional at compile time (see module docstring).
    import boto3
    from botocore.client import Config as _BotoConfig
    from botocore.exceptions import BotoCoreError, ClientError

    _BOTO3_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only without boto3
    boto3 = None  # type: ignore[assignment]
    _BotoConfig = None  # type: ignore[assignment]
    BotoCoreError = ClientError = Exception  # type: ignore[misc,assignment]
    _BOTO3_IMPORT_ERROR = exc


_DEFAULT_EXPIRES: int = 900
# Finished-result GET URLs are handed to end users and must survive well beyond
# the short-lived upload window; CTO §5.6 mandates a 7-day presigned GET.
_RESULT_URL_EXPIRES: int = 7 * 24 * 3600  # 604800 seconds (7 days)
_R2_ENDPOINT_TEMPLATE: str = "https://{account_id}.r2.cloudflarestorage.com"
_REQUIRED_CONFIG_KEYS: tuple[str, ...] = (
    "account_id",
    "access_key_id",
    "secret_access_key",
    "bucket",
)


def _insecure_http_endpoint_allowed() -> bool:
    """Explicit opt-in for a plain-HTTP S3 endpoint (local-dev MinIO only).

    Production R2 is always HTTPS; this flag exists solely so the self-contained
    ``apps/api/docker-compose.yml`` stack can back media with its bundled
    ``http://minio:9000`` service during local development. Never set it on a
    deployment that faces real users.
    """
    return os.getenv("R2_ALLOW_INSECURE_HTTP", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _normalize_s3_endpoint(endpoint: str, bucket: str) -> str:
    """Return an origin-only S3 endpoint without logging credential context."""
    value = endpoint.strip().rstrip("/")
    parsed = urlsplit(value)
    allowed_schemes = {"https"} | ({"http"} if _insecure_http_endpoint_allowed() else set())
    if (
        parsed.scheme not in allowed_schemes
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "R2_S3_ENDPOINT must be an HTTPS S3 origin without query or fragment"
        )
    path = parsed.path.rstrip("/")
    if path == f"/{bucket}":
        path = ""
    elif path:
        raise RuntimeError(
            "R2_S3_ENDPOINT must not contain an object or bucket path; configure "
            "the bucket separately with R2_BUCKET_NAME"
        )
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


@dataclass(frozen=True)
class PresignResult:
    """Immutable result of a presigned upload handshake.

    ``headers`` are the signed headers the client MUST echo on the PUT
    request (e.g. ``Content-Type``); omitting them invalidates the signature.
    """

    put_url: str
    get_url: str
    key: str
    headers: dict[str, str]


def _r2_config() -> dict[str, Any]:
    """Return the ``[r2]`` config section as a plain dict.

    Read defensively via ``getattr`` so importing this module does not require
    the ``r2`` section to already exist on the config module (it is added by
    the config builder per §3).

    ``public_base_url`` has no dedicated env override in the config builder
    (unlike the four credential keys), so it is wired here — environment wins,
    then the ``config.toml`` value, then empty string. This lets env-only
    container deploys supply it and lets startup validation require it, rather
    than silently falling back to the SigV4-gated private R2 endpoint.
    """
    section = getattr(config, "r2", {}) or {}
    try:
        cfg = dict(section)
    except (TypeError, ValueError):
        cfg = {}
    cfg["public_base_url"] = os.getenv(
        "R2_PUBLIC_BASE_URL", cfg.get("public_base_url", "")
    )
    return cfg


def _result_url_expires() -> int:
    """Return the expiry (seconds) for finished-result presigned GET URLs.

    Defaults to :data:`_RESULT_URL_EXPIRES` (7 days) but honours an optional
    ``config.r2['result_url_expires_s']`` override. Invalid or non-positive
    overrides fall back to the default rather than producing an already-expired
    or unbounded URL.
    """
    section = getattr(config, "r2", {}) or {}
    try:
        raw = section.get("result_url_expires_s")
    except AttributeError:  # pragma: no cover - config.r2 not a mapping
        raw = None
    if raw is None:
        return _RESULT_URL_EXPIRES
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            f"Invalid config.r2.result_url_expires_s={raw!r}; "
            f"falling back to default {_RESULT_URL_EXPIRES}s."
        )
        return _RESULT_URL_EXPIRES
    if value <= 0:
        logger.warning(
            f"Non-positive config.r2.result_url_expires_s={value}; "
            f"falling back to default {_RESULT_URL_EXPIRES}s."
        )
        return _RESULT_URL_EXPIRES
    return value


class R2Client:
    """Thin boto3 wrapper for Cloudflare R2 presign + upload operations."""

    def __init__(self, *, bucket: str | None = None, public_base_url: str | None = None) -> None:
        """Build the underlying S3 client from ``config.r2``.

        ``bucket`` and ``public_base_url`` select a different bucket on the same
        account and credentials (the public marketing bucket, see
        :func:`get_public_media_client`); both default to ``config.r2``.

        Reads ``account_id``, ``access_key_id``, ``secret_access_key``,
        ``bucket`` and ``public_base_url``. Raises a clear ``RuntimeError`` if
        boto3 is missing or required config keys are absent — never silently
        degrades.
        """
        if boto3 is None or _BotoConfig is None:
            raise RuntimeError(
                "boto3 is required for Cloudflare R2 storage but is not "
                "installed. Add 'boto3' to the environment "
                f"(original import error: {_BOTO3_IMPORT_ERROR})."
            )

        cfg = _r2_config()
        if bucket is not None:
            cfg["bucket"] = bucket
        if public_base_url is not None:
            cfg["public_base_url"] = public_base_url
        missing = [
            key for key in _REQUIRED_CONFIG_KEYS if not str(cfg.get(key, "")).strip()
        ]
        if missing:
            raise RuntimeError(
                "Cloudflare R2 is not configured. Missing required "
                f"config.r2 keys: {', '.join(missing)}."
            )

        self._account_id: str = str(cfg["account_id"]).strip()
        self._bucket: str = str(cfg["bucket"]).strip()
        self._public_base_url: str = str(cfg.get("public_base_url", "") or "").strip()
        configured_endpoint = str(cfg.get("endpoint_url", "") or "").strip()
        self._endpoint_url: str = (
            _normalize_s3_endpoint(configured_endpoint, self._bucket)
            if configured_endpoint
            else _R2_ENDPOINT_TEMPLATE.format(account_id=self._account_id)
        )

        self._s3 = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=str(cfg["access_key_id"]).strip(),
            aws_secret_access_key=str(cfg["secret_access_key"]).strip(),
            region_name="auto",
            config=_BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def healthcheck(self) -> None:
        """Verify the configured bucket is reachable without listing objects."""
        try:
            self._s3.head_bucket(Bucket=self._bucket)
        except (BotoCoreError, ClientError) as exc:
            raise RuntimeError(f"R2 bucket health check failed: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Presign helpers
    # ------------------------------------------------------------------ #
    def presign_put(
        self, key: str, content_type: str, expires: int = _DEFAULT_EXPIRES
    ) -> str:
        """Return a presigned PUT URL for ``key`` requiring ``content_type``."""
        try:
            return self._s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=int(expires),
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error(f"R2 presign_put failed for key={key!r}: {exc}")
            raise

    def presign_get(
        self,
        key: str,
        expires: int = _DEFAULT_EXPIRES,
        download_name: str | None = None,
    ) -> str:
        """Return a presigned GET URL for ``key``.

        When ``download_name`` is provided a
        ``Content-Disposition: attachment`` response header is signed in so the
        browser downloads with that filename.
        """
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        if download_name:
            safe_name = os.path.basename(download_name)
            params["ResponseContentDisposition"] = f'attachment; filename="{safe_name}"'
        try:
            return self._s3.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=int(expires),
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error(f"R2 presign_get failed for key={key!r}: {exc}")
            raise

    def presign_result_get(self, key: str, download_name: str | None = None) -> str:
        """Return a long-lived presigned GET URL for a finished result object.

        Uses the 7-day result expiry (CTO §5.6), honouring the optional
        ``config.r2['result_url_expires_s']`` override. Thin wrapper over
        :meth:`presign_get` so the same Content-Disposition handling applies.
        """
        return self.presign_get(
            key,
            expires=_result_url_expires(),
            download_name=download_name,
        )

    # ------------------------------------------------------------------ #
    # Upload
    # ------------------------------------------------------------------ #
    def upload_file(
        self, local_path: str, key: str, content_type: str | None = None
    ) -> str:
        """Upload ``local_path`` to ``key`` and return its permanent public URL.

        The content type is guessed from the filename when not supplied.
        Returns ``public_base_url + key``. Raises ``RuntimeError`` when
        ``public_base_url`` is not configured rather than returning the
        SigV4-gated private S3 endpoint (see :meth:`public_url`).
        """
        if not os.path.isfile(local_path):
            raise FileNotFoundError(
                f"R2 upload_file: local file not found: {local_path}"
            )

        resolved_type = (
            content_type
            or mimetypes.guess_type(local_path)[0]
            or "application/octet-stream"
        )
        try:
            with open(local_path, "rb") as fp:
                self._s3.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=fp,
                    ContentType=resolved_type,
                )
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.error(f"R2 upload_file failed for key={key!r}: {exc}")
            raise
        return self.public_url(key)

    def download_file(self, key: str, local_path: str) -> str:
        """Download a private object to ``local_path`` and return that path."""
        clean_key = str(key or "").lstrip("/")
        if not clean_key:
            raise ValueError("R2 download_file requires a non-empty key")
        destination = os.path.abspath(local_path)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        try:
            self._s3.download_file(self._bucket, clean_key, destination)
        except Exception as exc:  # noqa: BLE001 - boto transfer errors vary by version
            logger.error(f"R2 download_file failed for key={clean_key!r}: {exc}")
            raise
        return destination

    def upload_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        """Upload an in-memory ``data`` blob to ``key``; return the ``key``.

        Unlike :meth:`upload_file` this does NOT compute a permanent public URL
        (so it never requires ``public_base_url``) — it is used for private,
        owner-scoped objects (e.g. a GDPR data-export archive) that are handed
        back only through a short-lived presigned GET (:meth:`presign_get`).
        """
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error(f"R2 upload_bytes failed for key={key!r}: {exc}")
            raise
        return key

    def put_file(
        self, local_path: str, key: str, content_type: str | None = None
    ) -> str:
        """Upload ``local_path`` to a private ``key`` and return the ``key``.

        The private-object sibling of :meth:`upload_file`: it never requires
        ``public_base_url`` because the object is only ever handed out through a
        presigned GET (e.g. a stitched film export or a re-hosted render output).
        """
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"R2 put_file: local file not found: {local_path}")
        resolved_type = (
            content_type
            or mimetypes.guess_type(local_path)[0]
            or "application/octet-stream"
        )
        try:
            with open(local_path, "rb") as fp:
                self._s3.put_object(
                    Bucket=self._bucket, Key=key, Body=fp, ContentType=resolved_type
                )
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.error(f"R2 put_file failed for key={key!r}: {exc}")
            raise
        return key

    def delete_object(self, key: str) -> bool:
        """Delete ``key`` from the bucket. Returns ``True`` when the call succeeded.

        Deleting a missing key is a success on S3/R2 (idempotent). Errors are
        logged and re-raised so callers doing best-effort cleanup can decide.
        """
        clean_key = str(key or "").lstrip("/")
        if not clean_key:
            return False
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=clean_key)
        except (BotoCoreError, ClientError) as exc:
            logger.error(f"R2 delete_object failed for key={clean_key!r}: {exc}")
            raise
        return True

    # ------------------------------------------------------------------ #
    # Presigned upload handshake (used by POST /uploads/presign)
    # ------------------------------------------------------------------ #
    def presign_upload(
        self,
        filename: str,
        content_type: str,
        size: int,
        prefix: str = "uploads",
    ) -> PresignResult:
        """Generate a unique key and return matching PUT + GET presigned URLs.

        ``key = f'{prefix}/{uuid4().hex}{ext}'`` where ``ext`` is derived from
        ``filename``. ``size`` is accepted for interface/quotas parity with the
        API contract; R2 does not require it to be signed into the PUT URL.
        """
        _ = size  # reserved for future quota enforcement; kept per §2.7 signature
        ext = os.path.splitext(os.path.basename(filename or ""))[1]
        clean_prefix = str(prefix or "uploads").strip("/")
        key = f"{clean_prefix}/{uuid4().hex}{ext}"

        put_url = self.presign_put(key, content_type)
        get_url = self.presign_get(key)
        return PresignResult(
            put_url=put_url,
            get_url=get_url,
            key=key,
            headers={"Content-Type": content_type},
        )

    # ------------------------------------------------------------------ #
    # CORS bootstrap (one-shot, idempotent)
    # ------------------------------------------------------------------ #
    def ensure_cors(self, origins: list[str]) -> None:
        """Idempotently apply a PUT/GET/HEAD CORS policy for ``origins``.

        Intended for a one-shot bootstrap step, not per-request. Errors are
        logged; failure here must not crash the caller.
        """
        rules = {
            "CORSRules": [
                {
                    "AllowedOrigins": list(origins),
                    "AllowedMethods": ["PUT", "GET", "HEAD"],
                    "AllowedHeaders": ["*"],
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 3600,
                }
            ]
        }
        try:
            self._s3.put_bucket_cors(Bucket=self._bucket, CORSConfiguration=rules)
            logger.info(
                f"R2 CORS policy applied for bucket={self._bucket!r} origins={origins}"
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error(f"R2 ensure_cors failed for bucket={self._bucket!r}: {exc}")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def public_url(self, key: str) -> str:
        """Return the permanent public object URL for ``key``.

        Requires ``public_base_url`` to be configured (the bucket's public or
        custom-domain URL). When it is unset we raise instead of falling back to
        the ``https://<account>.r2.cloudflarestorage.com/<bucket>/<key>`` S3
        endpoint: that endpoint is SigV4-gated, so an unauthenticated consumer
        (e.g. HeyGen fetching an ``audio_url``) receives HTTP 401/403 and the
        render fails silently. Failing loudly here surfaces the misconfiguration
        instead of shipping an unreachable URL downstream.
        """
        if not self._public_base_url:
            raise RuntimeError(
                "Cloudflare R2 public_base_url is not configured. Set the "
                "R2_PUBLIC_BASE_URL environment variable (or config.r2."
                "public_base_url) to the bucket's public/custom-domain URL; the "
                "private S3 endpoint is SigV4-gated and cannot be fetched by "
                "external consumers such as HeyGen."
            )
        clean_key = key.lstrip("/")
        return f"{self._public_base_url.rstrip('/')}/{clean_key}"


# ---------------------------------------------------------------------- #
# Lazy module singleton
# ---------------------------------------------------------------------- #
_r2_client_singleton: R2Client | None = None


def get_r2_client() -> R2Client:
    """Return the process-wide :class:`R2Client`, constructing it on first use.

    Instantiation is deferred so that importing this module (or the surrounding
    package) does not require boto3 or a populated ``config.r2`` section.
    """
    global _r2_client_singleton
    if _r2_client_singleton is None:
        _r2_client_singleton = R2Client()
    return _r2_client_singleton


# ---------------------------------------------------------------------- #
# Public marketing media (M2.1): the landing showcase and style samples live
# in their own public bucket behind a custom domain, never on ``r2.dev``
# (rate-limited, not for production, and TLS-reset from some networks).
# ---------------------------------------------------------------------- #
PUBLIC_MEDIA_BUCKET_DEFAULT: str = "menivor-public"
PUBLIC_MEDIA_BASE_URL_DEFAULT: str = "https://media.menivor.com"
_public_media_singleton: R2Client | None = None


def public_media_target() -> tuple[str, str]:
    """``(bucket, public base URL)`` for public marketing media.

    ``R2_PUBLIC_MEDIA_BUCKET`` and ``R2_PUBLIC_MEDIA_BASE_URL`` override the
    defaults. An ``r2.dev`` base URL is refused: it is not a production origin.
    """
    bucket = os.getenv("R2_PUBLIC_MEDIA_BUCKET", "").strip() or PUBLIC_MEDIA_BUCKET_DEFAULT
    base = (os.getenv("R2_PUBLIC_MEDIA_BASE_URL", "").strip() or PUBLIC_MEDIA_BASE_URL_DEFAULT).rstrip("/")
    parsed = urlsplit(base)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise RuntimeError("R2_PUBLIC_MEDIA_BASE_URL must be an https origin")
    if host == "r2.dev" or host.endswith(".r2.dev"):
        raise RuntimeError(
            "R2_PUBLIC_MEDIA_BASE_URL must be a custom domain (e.g. media.menivor.com), not r2.dev"
        )
    return bucket, base


def get_public_media_client() -> R2Client:
    """The :class:`R2Client` for the public marketing bucket (same credentials)."""
    global _public_media_singleton
    if _public_media_singleton is None:
        bucket, base = public_media_target()
        _public_media_singleton = R2Client(bucket=bucket, public_base_url=base)
    return _public_media_singleton


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute access for the module-level ``r2_client`` singleton."""
    if name == "r2_client":
        return get_r2_client()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
