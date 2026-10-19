from __future__ import annotations

from pathlib import Path
import subprocess


REQUIRED_FILTERS = "ass trim atrim setpts asetpts concat overlay scale crop fps"
REQUIRED_ENCODERS = "libx264 aac"


def _write_fake_tool(path: Path, filters: str, encoders: str) -> None:
    path.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f'  -hide_banner) case "$2" in -filters) for name in {filters}; do echo " T.. $name test"; done ;; '
        f'-encoders) for name in {encoders}; do echo " V..... $name test"; done ;; esac ;;\n'
        '  -version) echo "fake tool 1.0" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_release_media_toolchain_verifier_accepts_complete_pair_and_rejects_gap(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    verifier = root / "apps" / "desktop" / "packaging" / "verify-media-toolchain.sh"
    ffmpeg = tmp_path / "ffmpeg"
    ffprobe = tmp_path / "ffprobe"
    _write_fake_tool(ffmpeg, REQUIRED_FILTERS, REQUIRED_ENCODERS)
    _write_fake_tool(ffprobe, "", "")

    subprocess.run([str(verifier), str(ffmpeg), str(ffprobe)], check=True)

    _write_fake_tool(
        ffmpeg,
        REQUIRED_FILTERS.replace("ass ", ""),
        REQUIRED_ENCODERS,
    )
    rejected = subprocess.run(
        [str(verifier), str(ffmpeg), str(ffprobe)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 1
    assert "missing required filter: ass" in rejected.stderr
