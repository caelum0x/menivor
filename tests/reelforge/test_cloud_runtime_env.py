"""Secret-boundary tests for the shared cloud runtime launcher."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "cloud-runtime-env.py"


def _minimal_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }


def test_non_storage_profile_does_not_import_r2_secret(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "DATABASE_URL=postgresql://user:pass@db.example.test/mint\n"
        "R2_SECRET_ACCESS_KEY=must-not-cross-profile-boundary\n",
        encoding="utf-8",
    )
    child = (
        "import os,sys; "
        "sys.exit(0 if 'R2_SECRET_ACCESS_KEY' not in os.environ else 9)"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "mint",
            "--env-file",
            str(dotenv),
            "--",
            sys.executable,
            "-c",
            child,
        ],
        env=_minimal_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_psql_command_is_rejected_as_database_url(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "DATABASE_URL=psql postgresql://user:pass@db.example.test/mint\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "mint", "--env-file", str(dotenv), "--check"],
        env=_minimal_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "not a psql command" in result.stderr
    assert "user:pass" not in result.stderr


def test_reelforge_bucket_precedence_prefers_product_specific_name() -> None:
    env = _minimal_env()
    env.update(
        {
            "PYTHONPATH": f"{ROOT / 'apps' / 'api'}:{ROOT}",
            "REELFORGE_R2_BUCKET_NAME": "reelforge-private",
            "R2_BUCKET_NAME": "shared-development",
            "R2_BUCKET": "legacy",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.config import config; "
            "assert config.r2['bucket'] == 'reelforge-private'",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
