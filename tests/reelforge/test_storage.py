"""Unit tests for ReelForge storage + avatar registry.

Covers:
  * app/services/storage/r2.py  — R2Client presign/upload/CORS + PresignResult
  * app/services/avatar/base.py — provider registry + get_avatar_provider

All AWS/R2 network I/O is stubbed via a fake boto3 S3 client (monkeypatched
onto the r2 module's ``boto3.client``), so these tests never touch the network
and require neither moto nor real credentials.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.storage import r2 as r2mod
from app.services.avatar import base as avatar_base


# --------------------------------------------------------------------------- #
# Fake boto3 S3 client (records calls, returns deterministic values)
# --------------------------------------------------------------------------- #
class FakeS3Client:
    """Minimal stand-in for a boto3 S3 client.

    Records every call so tests can assert exact operation names + params,
    and returns deterministic presigned URLs without any network access.
    """

    def __init__(self) -> None:
        self.presign_calls: list[dict[str, Any]] = []
        self.put_object_calls: list[dict[str, Any]] = []
        self.put_bucket_cors_calls: list[dict[str, Any]] = []
        self.presign_side_effect: Exception | None = None

    def generate_presigned_url(
        self, client_method: str, Params: dict[str, Any], ExpiresIn: int
    ) -> str:
        self.presign_calls.append(
            {"method": client_method, "params": dict(Params), "expires": ExpiresIn}
        )
        if self.presign_side_effect is not None:
            raise self.presign_side_effect
        key = Params.get("Key", "")
        return f"https://signed.example/{client_method}/{key}?exp={ExpiresIn}"

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_object_calls.append(kwargs)
        return {"ETag": "fake-etag"}

    def put_bucket_cors(self, **kwargs: Any) -> dict[str, Any]:
        self.put_bucket_cors_calls.append(kwargs)
        return {}


@pytest.fixture
def fake_s3(monkeypatch: pytest.MonkeyPatch) -> FakeS3Client:
    """Patch the r2 module so R2Client() builds against a FakeS3Client."""
    fake = FakeS3Client()

    class _FakeBoto3:
        @staticmethod
        def client(service_name: str, **kwargs: Any) -> FakeS3Client:
            # Sanity: contract mandates the S3 endpoint + auto region + SigV4.
            assert service_name == "s3"
            assert kwargs["region_name"] == "auto"
            assert kwargs["endpoint_url"].endswith(".r2.cloudflarestorage.com")
            return fake

    monkeypatch.setattr(r2mod, "boto3", _FakeBoto3)
    # Ensure the optional-import sentinel does not block instantiation.
    monkeypatch.setattr(r2mod, "_BotoConfig", lambda **kw: {"config": kw})
    # public_base_url is a required config key (else HeyGen gets a private,
    # SigV4-gated URL). Supply it so R2Client() constructs against the fake.
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://cdn.example.com")
    # Reset the lazy singleton so get_r2_client() rebuilds against the fake.
    monkeypatch.setattr(r2mod, "_r2_client_singleton", None)
    return fake


@pytest.fixture
def client(fake_s3: FakeS3Client) -> r2mod.R2Client:
    return r2mod.R2Client()


# --------------------------------------------------------------------------- #
# PresignResult carries headers
# --------------------------------------------------------------------------- #
def test_presign_result_is_frozen_and_carries_headers() -> None:
    result = r2mod.PresignResult(
        put_url="https://put", get_url="https://get", key="uploads/x.mp4",
        headers={"Content-Type": "video/mp4"},
    )
    assert result.headers == {"Content-Type": "video/mp4"}
    assert result.put_url == "https://put"
    assert result.get_url == "https://get"
    assert result.key == "uploads/x.mp4"
    # frozen dataclass -> immutable
    with pytest.raises(Exception):
        result.key = "other"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# presign_upload key construction: prefix + uuid + preserved extension
# --------------------------------------------------------------------------- #
def test_presign_upload_key_has_prefix_uuid_and_preserved_extension(
    client: r2mod.R2Client,
) -> None:
    res = client.presign_upload(
        filename="My Recording.MP4", content_type="video/mp4", size=1234, prefix="screens"
    )
    assert isinstance(res, r2mod.PresignResult)
    # prefix preserved
    assert res.key.startswith("screens/")
    # extension preserved (case as-provided by splitext)
    assert res.key.endswith(".MP4")
    # middle segment is a 32-char hex uuid4().hex
    stem = res.key[len("screens/"):-len(".MP4")]
    assert len(stem) == 32
    int(stem, 16)  # raises ValueError if not hex


def test_presign_upload_default_prefix_is_uploads(client: r2mod.R2Client) -> None:
    res = client.presign_upload(filename="clip.wav", content_type="audio/wav", size=1)
    assert res.key.startswith("uploads/")
    assert res.key.endswith(".wav")


def test_presign_upload_strips_slashes_from_prefix(client: r2mod.R2Client) -> None:
    res = client.presign_upload(
        filename="a.png", content_type="image/png", size=1, prefix="/nested/dir/"
    )
    assert res.key.startswith("nested/dir/")
    assert "//" not in res.key


def test_presign_upload_handles_extensionless_filename(client: r2mod.R2Client) -> None:
    res = client.presign_upload(filename="noext", content_type="application/octet-stream", size=1)
    # no extension -> key is just prefix/<32 hex>
    assert res.key.startswith("uploads/")
    stem = res.key[len("uploads/"):]
    assert len(stem) == 32
    int(stem, 16)


def test_presign_upload_keys_are_unique(client: r2mod.R2Client) -> None:
    a = client.presign_upload(filename="x.mp4", content_type="video/mp4", size=1)
    b = client.presign_upload(filename="x.mp4", content_type="video/mp4", size=1)
    assert a.key != b.key


def test_presign_upload_result_headers_and_urls(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    res = client.presign_upload(filename="x.mp4", content_type="video/mp4", size=1, prefix="up")
    # PresignResult carries the signed Content-Type header the client must echo.
    assert res.headers == {"Content-Type": "video/mp4"}
    # put_url comes from a put_object presign, get_url from get_object.
    assert res.put_url.startswith("https://signed.example/put_object/")
    assert res.get_url.startswith("https://signed.example/get_object/")
    # Two presign calls: one PUT, one GET, both for the same key.
    methods = [c["method"] for c in fake_s3.presign_calls]
    assert methods == ["put_object", "get_object"]
    assert fake_s3.presign_calls[0]["params"]["Key"] == res.key
    assert fake_s3.presign_calls[1]["params"]["Key"] == res.key


# --------------------------------------------------------------------------- #
# presign_put -> generate_presigned_url params
# --------------------------------------------------------------------------- #
def test_presign_put_calls_generate_presigned_url_with_correct_params(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    url = client.presign_put("uploads/f.mp4", "video/mp4", expires=600)
    assert url == "https://signed.example/put_object/uploads/f.mp4?exp=600"
    assert len(fake_s3.presign_calls) == 1
    call = fake_s3.presign_calls[0]
    assert call["method"] == "put_object"
    assert call["expires"] == 600
    assert call["params"] == {
        "Bucket": "x",  # R2_BUCKET env from the test runner
        "Key": "uploads/f.mp4",
        "ContentType": "video/mp4",
    }


def test_presign_put_default_expiry_is_900(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    client.presign_put("k", "text/plain")
    assert fake_s3.presign_calls[0]["expires"] == r2mod._DEFAULT_EXPIRES == 900


def test_presign_put_propagates_client_error(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    fake_s3.presign_side_effect = r2mod.BotoCoreError()
    with pytest.raises(r2mod.BotoCoreError):
        client.presign_put("k", "text/plain")


# --------------------------------------------------------------------------- #
# presign_get -> generate_presigned_url params
# --------------------------------------------------------------------------- #
def test_presign_get_basic_params(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    url = client.presign_get("uploads/out.mp4", expires=120)
    assert url == "https://signed.example/get_object/uploads/out.mp4?exp=120"
    call = fake_s3.presign_calls[0]
    assert call["method"] == "get_object"
    assert call["expires"] == 120
    assert call["params"] == {"Bucket": "x", "Key": "uploads/out.mp4"}


def test_presign_get_default_expiry_is_900(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    client.presign_get("k")
    assert fake_s3.presign_calls[0]["expires"] == 900


def test_presign_get_with_download_name_signs_content_disposition(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    client.presign_get("uploads/out.mp4", download_name="Final Reel.mp4")
    params = fake_s3.presign_calls[0]["params"]
    assert (
        params["ResponseContentDisposition"]
        == 'attachment; filename="Final Reel.mp4"'
    )


def test_presign_get_download_name_is_basename_only(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    # Path traversal in the download name must be reduced to the basename.
    client.presign_get("k", download_name="../../etc/passwd")
    params = fake_s3.presign_calls[0]["params"]
    assert params["ResponseContentDisposition"] == 'attachment; filename="passwd"'


# --------------------------------------------------------------------------- #
# presign_result_get -> 7-day expiry (CTO §5.6)
# --------------------------------------------------------------------------- #
def test_result_url_expires_constant_is_seven_days() -> None:
    assert r2mod._RESULT_URL_EXPIRES == 7 * 24 * 3600 == 604800


def test_presign_result_get_uses_seven_day_expiry(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    url = client.presign_result_get("results/final.mp4")
    assert url == "https://signed.example/get_object/results/final.mp4?exp=604800"
    call = fake_s3.presign_calls[0]
    assert call["method"] == "get_object"
    assert call["expires"] == 604800  # ~7 days, not the 900s upload default
    assert call["params"] == {"Bucket": "x", "Key": "results/final.mp4"}


def test_presign_result_get_signs_content_disposition(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    client.presign_result_get("results/final.mp4", download_name="My Reel.mp4")
    params = fake_s3.presign_calls[0]["params"]
    assert params["ResponseContentDisposition"] == 'attachment; filename="My Reel.mp4"'
    assert fake_s3.presign_calls[0]["expires"] == 604800


def test_presign_result_get_honours_config_override(
    client: r2mod.R2Client, fake_s3: FakeS3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(r2mod.config, "r2", {"result_url_expires_s": 3600})
    client.presign_result_get("results/final.mp4")
    assert fake_s3.presign_calls[0]["expires"] == 3600


def test_presign_result_get_ignores_invalid_override(
    client: r2mod.R2Client, fake_s3: FakeS3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(r2mod.config, "r2", {"result_url_expires_s": "not-a-number"})
    client.presign_result_get("results/final.mp4")
    assert fake_s3.presign_calls[0]["expires"] == 604800


def test_presign_result_get_ignores_nonpositive_override(
    client: r2mod.R2Client, fake_s3: FakeS3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(r2mod.config, "r2", {"result_url_expires_s": 0})
    client.presign_result_get("results/final.mp4")
    assert fake_s3.presign_calls[0]["expires"] == 604800


def test_presign_get_default_still_900_for_uploads(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    # General presign_get default is unchanged (short-lived upload window).
    client.presign_get("uploads/x.mp4")
    assert fake_s3.presign_calls[0]["expires"] == 900


# --------------------------------------------------------------------------- #
# upload_file -> put_object + public URL
# --------------------------------------------------------------------------- #
def test_upload_file_puts_object_and_returns_public_url(
    client: r2mod.R2Client, fake_s3: FakeS3Client, tmp_path
) -> None:
    f = tmp_path / "sound.mp3"
    f.write_bytes(b"ID3 fake audio")
    url = client.upload_file(str(f), "audio/sound.mp3")
    assert len(fake_s3.put_object_calls) == 1
    call = fake_s3.put_object_calls[0]
    assert call["Bucket"] == "x"
    assert call["Key"] == "audio/sound.mp3"
    assert call["ContentType"] == "audio/mpeg"  # guessed from .mp3
    # public_base_url configured -> permanent public CDN URL (never the private
    # SigV4-gated S3 endpoint that HeyGen cannot fetch).
    assert url == "https://cdn.example.com/audio/sound.mp3"


def test_upload_file_honours_explicit_content_type(
    client: r2mod.R2Client, fake_s3: FakeS3Client, tmp_path
) -> None:
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\x01")
    client.upload_file(str(f), "k", content_type="application/x-custom")
    assert fake_s3.put_object_calls[0]["ContentType"] == "application/x-custom"


def test_upload_file_missing_local_file_raises(client: r2mod.R2Client) -> None:
    with pytest.raises(FileNotFoundError):
        client.upload_file("/no/such/file.mp4", "k")


# --------------------------------------------------------------------------- #
# public_url helpers
# --------------------------------------------------------------------------- #
def test_public_url_uses_public_base_url_when_configured(
    fake_s3: FakeS3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        r2mod,
        "_r2_config",
        lambda: {
            "account_id": "acct",
            "access_key_id": "ak",
            "secret_access_key": "sk",
            "bucket": "bkt",
            "public_base_url": "https://cdn.example.com/",
        },
    )
    c = r2mod.R2Client()
    assert c.public_url("/media/final.mp4") == "https://cdn.example.com/media/final.mp4"


def test_public_url_raises_when_base_url_unconfigured(client: r2mod.R2Client) -> None:
    # An env-only deploy that forgets R2_PUBLIC_BASE_URL must NOT silently fall
    # back to the SigV4-gated private R2 endpoint (which HeyGen fetches with
    # HTTP 401/403, failing renders). public_url must fail loudly instead.
    client._public_base_url = ""
    with pytest.raises(RuntimeError, match="public_base_url"):
        client.public_url("k.mp4")


def test_public_base_url_env_override_is_wired(
    fake_s3: FakeS3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    # public_base_url has no dedicated override in the config builder, so r2.py
    # wires R2_PUBLIC_BASE_URL itself; env must win over the config.toml value.
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://media.example.net/")
    c = r2mod.R2Client()
    assert c.public_url("clip.mp4") == "https://media.example.net/clip.mp4"


# --------------------------------------------------------------------------- #
# ensure_cors idempotent bootstrap
# --------------------------------------------------------------------------- #
def test_ensure_cors_puts_expected_policy(
    client: r2mod.R2Client, fake_s3: FakeS3Client
) -> None:
    client.ensure_cors(["https://app.example.com"])
    assert len(fake_s3.put_bucket_cors_calls) == 1
    call = fake_s3.put_bucket_cors_calls[0]
    assert call["Bucket"] == "x"
    rule = call["CORSConfiguration"]["CORSRules"][0]
    assert rule["AllowedOrigins"] == ["https://app.example.com"]
    assert rule["AllowedMethods"] == ["PUT", "GET", "HEAD"]


def test_ensure_cors_swallows_errors(
    client: r2mod.R2Client, fake_s3: FakeS3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(**kwargs: Any) -> None:
        raise r2mod.BotoCoreError()

    monkeypatch.setattr(fake_s3, "put_bucket_cors", _boom)
    # Must not raise — bootstrap failures are logged, not propagated.
    client.ensure_cors(["https://app.example.com"])


# --------------------------------------------------------------------------- #
# Construction guards + singleton
# --------------------------------------------------------------------------- #
def test_init_raises_when_boto3_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(r2mod, "boto3", None)
    with pytest.raises(RuntimeError, match="boto3 is required"):
        r2mod.R2Client()


def test_init_raises_when_config_incomplete(
    fake_s3: FakeS3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        r2mod, "_r2_config", lambda: {"account_id": "", "bucket": "", }
    )
    with pytest.raises(RuntimeError, match="not configured"):
        r2mod.R2Client()


def test_get_r2_client_is_singleton(fake_s3: FakeS3Client) -> None:
    a = r2mod.get_r2_client()
    b = r2mod.get_r2_client()
    assert a is b


def test_module_getattr_exposes_r2_client(fake_s3: FakeS3Client) -> None:
    assert isinstance(r2mod.r2_client, r2mod.R2Client)


def test_module_getattr_unknown_raises() -> None:
    with pytest.raises(AttributeError):
        r2mod.__getattr__("nope")


# =========================================================================== #
# avatar/base.py — provider registry
# =========================================================================== #
class _FakeProvider:
    def __init__(self, name: str = "fake") -> None:
        self.name = name

    def is_enabled(self) -> bool:
        return True

    def list_avatars(self) -> list[dict]:
        return []

    def generate_avatar(self, audio_url, avatar_id, **kwargs):  # noqa: ANN001
        return None


@pytest.fixture
def clean_registry(monkeypatch: pytest.MonkeyPatch):
    """Give each avatar test an isolated, empty registry + unloaded flag.

    The default provider modules are evicted from ``sys.modules`` so that the
    lazy ``__import__`` inside ``_ensure_providers_loaded`` actually re-executes
    them and re-registers into the fresh ``AVATAR_PROVIDERS`` dict (a cached
    module would otherwise be a no-op import and leave the registry empty).
    """
    import sys

    monkeypatch.setattr(avatar_base, "AVATAR_PROVIDERS", {})
    monkeypatch.setattr(avatar_base, "_providers_loaded", False)
    for module_path in avatar_base._DEFAULT_PROVIDER_MODULES:
        monkeypatch.delitem(sys.modules, module_path, raising=False)
    return avatar_base


def test_get_avatar_provider_returns_heygen(clean_registry) -> None:
    provider = clean_registry.get_avatar_provider("heygen")
    assert provider.name == "heygen"


def test_registry_populated_after_resolution(clean_registry) -> None:
    assert clean_registry.AVATAR_PROVIDERS == {}
    clean_registry.get_avatar_provider("heygen")
    assert "heygen" in clean_registry.AVATAR_PROVIDERS


def test_default_provider_id_is_heygen(clean_registry) -> None:
    provider = clean_registry.get_avatar_provider()
    assert provider.name == "heygen"


def test_unknown_provider_falls_back_with_warning(
    clean_registry, caplog: pytest.LogCaptureFixture
) -> None:
    # loguru writes through the standard logging hook only if propagated; assert
    # on the returned provider (the observable fallback behavior) plus message.
    messages: list[str] = []
    handler_id = None
    try:
        from loguru import logger as _logger

        handler_id = _logger.add(lambda m: messages.append(str(m)), level="WARNING")
        provider = clean_registry.get_avatar_provider("does-not-exist")
    finally:
        if handler_id is not None:
            _logger.remove(handler_id)
    assert provider.name == "heygen"  # fell back to default
    assert any("unknown avatar provider" in m for m in messages)
    assert any("does-not-exist" in m for m in messages)


def test_register_avatar_provider_adds_to_registry(clean_registry) -> None:
    p = _FakeProvider("customx")
    clean_registry.register_avatar_provider(p)
    assert clean_registry.AVATAR_PROVIDERS["customx"] is p


def test_register_avatar_provider_is_idempotent_overwrite(clean_registry) -> None:
    first = _FakeProvider("dup")
    second = _FakeProvider("dup")
    clean_registry.register_avatar_provider(first)
    clean_registry.register_avatar_provider(second)
    assert clean_registry.AVATAR_PROVIDERS["dup"] is second


def test_register_provider_without_name_is_skipped(clean_registry) -> None:
    class _NoName:
        name = ""

    clean_registry.register_avatar_provider(_NoName())
    assert clean_registry.AVATAR_PROVIDERS == {}


def test_get_provider_returns_registered_fake(clean_registry) -> None:
    p = _FakeProvider("myfake")
    clean_registry.register_avatar_provider(p)
    # Mark providers as loaded so resolution does not import heygen and finds fake.
    clean_registry._providers_loaded = True
    assert clean_registry.get_avatar_provider("myfake") is p


def test_empty_registry_raises_keyerror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(avatar_base, "AVATAR_PROVIDERS", {})
    monkeypatch.setattr(avatar_base, "_providers_loaded", True)  # skip real import
    with pytest.raises(KeyError):
        avatar_base.get_avatar_provider("heygen")


def test_provider_load_failure_is_swallowed(
    clean_registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A default provider module that fails to import must not crash resolution;
    # with nothing registered it surfaces as a KeyError (deployment error).
    monkeypatch.setattr(
        avatar_base, "_DEFAULT_PROVIDER_MODULES", ("app.services.avatar._missing_xyz",)
    )
    with pytest.raises(KeyError):
        clean_registry.get_avatar_provider("heygen")


def test_ensure_providers_loaded_runs_once(clean_registry) -> None:
    calls: list[str] = []
    import builtins

    real_import = builtins.__import__

    def _counting_import(name, *args, **kwargs):  # noqa: ANN001
        if name in avatar_base._DEFAULT_PROVIDER_MODULES:
            calls.append(name)
        return real_import(name, *args, **kwargs)

    builtins.__import__ = _counting_import
    try:
        clean_registry._ensure_providers_loaded()
        clean_registry._ensure_providers_loaded()
    finally:
        builtins.__import__ = real_import
    assert calls == list(avatar_base._DEFAULT_PROVIDER_MODULES)


def test_heygen_provider_satisfies_protocol(clean_registry) -> None:
    provider = clean_registry.get_avatar_provider("heygen")
    assert isinstance(provider, avatar_base.TalkingHeadProvider)
