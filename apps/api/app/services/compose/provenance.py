"""C2PA Content Credentials on every final MP4 (M7.1).

MN5 (:mod:`app.services.provenance`) already writes plain container metadata
("AI-generated", generator, content id) into each final reel. That metadata is
easy to strip and is not signed. This module adds the signed layer: a C2PA
manifest embedded in the MP4 that any C2PA reader (``c2patool``, the
``c2pa-python`` Reader, https://contentcredentials.org/verify) can find.

The manifest says:

* ``c2pa.actions`` - one ``c2pa.created`` action whose ``digitalSourceType`` is
  the IPTC term ``trainedAlgorithmicMedia`` (media made by a trained model; the
  EU AI Act Art. 50 machine-readable marking the plan asks for), with
  Menivor as the software agent.
* ``com.menivor.provenance`` - the content id to quote in a takedown report and
  the report URL.

Signing key, in order:

1. ``REELFORGE_C2PA_CERT_CHAIN_PATH`` + ``REELFORGE_C2PA_PRIVATE_KEY_PATH``: a
   PEM certificate chain (leaf first) and its ES256 private key. Use this for a
   certificate from a CA on the C2PA trust list.
2. Otherwise a self-issued ES256 chain (a Menivor CA and a signing leaf),
   generated once and kept in ``REELFORGE_C2PA_KEY_DIR`` (default
   ``<runtime>/c2pa``). The manifest is cryptographically valid; readers report
   the signer as not on their trust list (``signingCredential.untrusted``).
   That is stated in :func:`read_manifest`'s ``trusted`` field, never hidden.

``REELFORGE_C2PA_TSA_URL`` optionally adds an RFC 3161 timestamp. It is unset by
default so signing makes no network call.

``REELFORGE_C2PA_ENABLED`` (default on) switches the signed layer. With it off
the MN5 metadata tag is still written; nothing else changes.

Signing is done after the MN5 remux: any later remux would drop the manifest's
``uuid`` box. The media packets are not re-encoded.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any

from app.services.provenance import GENERATOR, REPORT_URL

ENV_ENABLED = "REELFORGE_C2PA_ENABLED"
ENV_CERT_CHAIN = "REELFORGE_C2PA_CERT_CHAIN_PATH"
ENV_PRIVATE_KEY = "REELFORGE_C2PA_PRIVATE_KEY_PATH"
ENV_KEY_DIR = "REELFORGE_C2PA_KEY_DIR"
ENV_TSA_URL = "REELFORGE_C2PA_TSA_URL"

MIME_MP4 = "video/mp4"
DIGITAL_SOURCE_TYPE_URI = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
MENIVOR_ASSERTION = "com.menivor.provenance"
SELF_ISSUED_BUNDLE = "signer.pem"
SELF_ISSUED_CA_NAME = "Menivor Content Credentials CA"
SELF_ISSUED_LEAF_NAME = "Menivor Content Credentials"
CA_VALID_DAYS = 3650
LEAF_VALID_DAYS = 825
UNTRUSTED_CODE = "signingCredential.untrusted"
_FALSEY = {"0", "false", "no", "off"}


class ContentCredentialsError(RuntimeError):
    """The C2PA manifest could not be built, signed or read."""


@dataclass(frozen=True)
class SigningMaterial:
    """A PEM certificate chain (leaf first) and its private key."""

    cert_chain_pem: bytes
    private_key_pem: bytes
    source: str  # "configured" or "self_issued"


def c2pa_enabled() -> bool:
    return os.getenv(ENV_ENABLED, "true").strip().lower() not in _FALSEY


def build_manifest(content_id: str) -> dict[str, Any]:
    """The manifest definition signed into the final MP4 for ``content_id``."""
    cid = str(content_id)
    return {
        "claim_generator_info": [{"name": GENERATOR, "version": "1"}],
        "title": f"{cid}.mp4",
        "format": MIME_MP4,
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": DIGITAL_SOURCE_TYPE_URI,
                            "softwareAgent": {"name": GENERATOR},
                        }
                    ]
                },
            },
            {
                "label": MENIVOR_ASSERTION,
                "data": {"ai_generated": True, "content_id": cid, "report_url": REPORT_URL},
            },
        ],
    }


# --------------------------------------------------------------------------- #
# Signing material
# --------------------------------------------------------------------------- #
def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as exc:
        raise ContentCredentialsError(f"cannot read C2PA signing file {path!r}: {exc}") from exc


def _key_dir() -> str:
    configured = os.getenv(ENV_KEY_DIR, "").strip()
    if configured:
        return configured
    from app.utils import utils

    return os.path.join(utils.storage_dir(), "c2pa")


def _issue_self_signed_bundle() -> bytes:
    """A new PEM bundle: leaf private key, leaf certificate, CA certificate."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = _dt.datetime.now(_dt.timezone.utc)
    start = now - _dt.timedelta(minutes=5)

    def _name(common_name: str) -> x509.Name:
        return x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, GENERATOR),
        ])

    def _usage(*, sign: bool, ca: bool) -> x509.KeyUsage:
        return x509.KeyUsage(
            digital_signature=sign, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=ca, crl_sign=ca,
            encipher_only=False, decipher_only=False,
        )

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(_name(SELF_ISSUED_CA_NAME))
        .issuer_name(_name(SELF_ISSUED_CA_NAME))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(now + _dt.timedelta(days=CA_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(_usage(sign=False, ca=True), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(_name(SELF_ISSUED_LEAF_NAME))
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(now + _dt.timedelta(days=LEAF_VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(_usage(sign=True, ca=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    key_pem = leaf_key.private_bytes(
        pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return key_pem + leaf_cert.public_bytes(pem) + ca_cert.public_bytes(pem)


def _split_bundle(bundle: bytes, source: str) -> SigningMaterial:
    marker = b"-----END PRIVATE KEY-----"
    end = bundle.find(marker)
    if end < 0 or b"-----BEGIN CERTIFICATE-----" not in bundle:
        raise ContentCredentialsError("C2PA signer bundle is malformed")
    cut = end + len(marker)
    return SigningMaterial(
        cert_chain_pem=bundle[cut:].lstrip(),
        private_key_pem=bundle[:cut] + b"\n",
        source=source,
    )


def _self_issued_material() -> SigningMaterial:
    """The persisted self-issued chain, created once (first writer wins)."""
    directory = _key_dir()
    path = os.path.join(directory, SELF_ISSUED_BUNDLE)
    if not os.path.isfile(path):
        os.makedirs(directory, mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".signer-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(_issue_self_signed_bundle())
            os.chmod(tmp, 0o600)
            try:
                os.link(tmp, path)  # atomic and fails if another worker won
            except FileExistsError:
                pass
        finally:
            os.remove(tmp)
    return _split_bundle(_read(path), "self_issued")


def load_signing_material() -> SigningMaterial:
    chain_path = os.getenv(ENV_CERT_CHAIN, "").strip()
    key_path = os.getenv(ENV_PRIVATE_KEY, "").strip()
    if chain_path or key_path:
        if not (chain_path and key_path):
            raise ContentCredentialsError(f"set both {ENV_CERT_CHAIN} and {ENV_PRIVATE_KEY}, or neither")
        return SigningMaterial(_read(chain_path), _read(key_path), "configured")
    return _self_issued_material()


# --------------------------------------------------------------------------- #
# Sign and read
# --------------------------------------------------------------------------- #
def _c2pa() -> Any:
    try:
        import c2pa
    except ImportError as exc:  # pragma: no cover - the dependency is pinned
        raise ContentCredentialsError("c2pa-python is not installed on this server") from exc
    return c2pa


def sign_mp4(path: str, content_id: str) -> dict[str, Any]:
    """Embed a signed C2PA manifest into the MP4 at ``path`` (in place).

    Returns the :func:`read_manifest` summary of the signed file. Raises
    :class:`ContentCredentialsError` so a reel is never delivered unsigned
    while the signed layer is on.
    """
    if not path or not os.path.isfile(path):
        raise ContentCredentialsError(f"no final video to sign at {path!r}")
    c2pa = _c2pa()
    material = load_signing_material()
    tsa = os.getenv(ENV_TSA_URL, "").strip() or None
    tmp = f"{path}.c2pa.mp4"
    try:
        info = c2pa.C2paSignerInfo(
            c2pa.C2paSigningAlg.ES256, material.cert_chain_pem, material.private_key_pem,
            tsa.encode() if tsa else None,
        )
        signer = c2pa.Signer.from_info(info)
        builder = c2pa.Builder(build_manifest(content_id))
        with open(path, "rb") as source, open(tmp, "w+b") as dest:
            builder.sign(signer, MIME_MP4, source, dest)
    except Exception as exc:  # noqa: BLE001 - c2pa raises its own error types
        _discard(tmp)
        raise ContentCredentialsError(f"C2PA signing failed: {exc}") from exc
    summary = read_manifest(tmp)
    if not summary.get("present"):
        _discard(tmp)
        raise ContentCredentialsError("C2PA manifest missing after signing")
    os.replace(tmp, path)
    return summary


def _discard(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:  # pragma: no cover - best-effort cleanup
        pass


def _summarize(store: dict[str, Any]) -> dict[str, Any]:
    label = store.get("active_manifest")
    manifest = (store.get("manifests") or {}).get(label) or {}
    assertions = {a.get("label"): a.get("data") or {} for a in manifest.get("assertions") or []}
    actions = []
    for key in ("c2pa.actions.v2", "c2pa.actions"):
        actions.extend((assertions.get(key) or {}).get("actions") or [])
    source_types = sorted({str(a.get("digitalSourceType")) for a in actions if a.get("digitalSourceType")})
    menivor = assertions.get(MENIVOR_ASSERTION) or {}
    statuses = [str(s.get("code")) for s in store.get("validation_status") or []]
    signature = manifest.get("signature_info") or {}
    state = str(store.get("validation_state") or "")
    return {
        "present": bool(label and manifest),
        "manifest_label": label,
        "claim_generator": [g.get("name") for g in manifest.get("claim_generator_info") or []],
        "signer": signature.get("common_name") or signature.get("issuer"),
        "issuer": signature.get("issuer"),
        "signed_at": signature.get("time"),
        "validation_state": state,
        "validation_codes": statuses,
        "valid": state in {"Valid", "Trusted"},
        "trusted": state == "Trusted" or (state == "Valid" and UNTRUSTED_CODE not in statuses),
        "ai_generated": DIGITAL_SOURCE_TYPE_URI in source_types or bool(menivor.get("ai_generated")),
        "digital_source_types": source_types,
        "content_id": menivor.get("content_id"),
        "made_with_menivor": GENERATOR in {g.get("name") for g in manifest.get("claim_generator_info") or []},
    }


_EMPTY: dict[str, Any] = {"present": False, "valid": False, "trusted": False, "ai_generated": False,
                          "made_with_menivor": False, "content_id": None}


def read_manifest(path: str, mime: str = MIME_MP4) -> dict[str, Any]:
    """A summary of the C2PA manifest in ``path``; ``present`` is False if none."""
    c2pa = _c2pa()
    try:
        with open(path, "rb") as fh:
            reader = c2pa.Reader(mime, fh)
            store = json.loads(reader.json() or "{}")
    except OSError as exc:
        raise ContentCredentialsError(f"cannot open {path!r}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - "no manifest" is an error in c2pa
        if "ManifestNotFound" in type(exc).__name__ or "manifest" in str(exc).lower():
            return dict(_EMPTY)
        raise ContentCredentialsError(f"C2PA read failed: {exc}") from exc
    return _summarize(store) if store.get("active_manifest") else dict(_EMPTY)


def has_manifest(path: str) -> bool:
    try:
        return bool(read_manifest(path).get("present"))
    except ContentCredentialsError:
        return False


__all__ = [
    "ContentCredentialsError",
    "DIGITAL_SOURCE_TYPE_URI",
    "ENV_CERT_CHAIN",
    "ENV_ENABLED",
    "ENV_KEY_DIR",
    "ENV_PRIVATE_KEY",
    "ENV_TSA_URL",
    "MENIVOR_ASSERTION",
    "SigningMaterial",
    "build_manifest",
    "c2pa_enabled",
    "has_manifest",
    "load_signing_material",
    "read_manifest",
    "sign_mp4",
]
