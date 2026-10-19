from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def test_desktop_update_signer_derives_artifact_truth_and_valid_signature(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "sign-desktop-update.py"
    private_key = tmp_path / "release-key.pem"
    public_key = tmp_path / "release-public.pem"
    artifact = tmp_path / "Menivor-x86_64.AppImage"
    artifact.write_bytes(b"real release artifact")
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)],
        check=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
    )
    spec = {
        "channel": "stable",
        "version": "1.2.3",
        "published_at": "2026-08-28T00:00:00Z",
        "notes_url": "https://updates.example/1.2.3",
        "artifacts": [
            {
                "platform": "linux",
                "arch": "x86_64",
                "kind": "appimage",
                "url": "https://updates.example/Menivor-x86_64.AppImage",
                "path": str(artifact),
            }
        ],
    }
    spec_path = tmp_path / "spec.json"
    manifest_path = tmp_path / "stable.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--spec",
            str(spec_path),
            "--private-key",
            str(private_key),
            "--key-id",
            "release-1",
            "--output",
            str(manifest_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    release = manifest["release"]
    assert manifest["schema_version"] == 1
    assert manifest["key_id"] == "release-1"
    assert release["artifacts"][0]["size_bytes"] == artifact.stat().st_size
    assert release["artifacts"][0]["sha256"] == hashlib.sha256(
        artifact.read_bytes()
    ).hexdigest()
    assert "MENIVOR_UPDATE_PUBLIC_KEY_BASE64=" in completed.stdout

    canonical = json.dumps(
        release, ensure_ascii=False, separators=(",", ":")
    ).encode()
    payload_path = tmp_path / "canonical.json"
    signature_path = tmp_path / "canonical.sig"
    payload_path.write_bytes(canonical)
    signature_path.write_bytes(base64.b64decode(manifest["signature_base64"]))
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-verify",
            "-pubin",
            "-inkey",
            str(public_key),
            "-rawin",
            "-in",
            str(payload_path),
            "-sigfile",
            str(signature_path),
        ],
        check=True,
    )
