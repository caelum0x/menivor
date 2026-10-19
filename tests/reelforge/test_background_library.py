"""Rights-clean background catalog and offline materialization tests."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from app.domains.content import background_library as library


_PACKAGED_IDS = (
    "voxel-parkour",
    "neon-runner",
    "synthwave-road",
    # Legacy ids still resolve to the same packaged loops.
    "minecraft-parkour",
    "subway-surfers",
    "gta-driving",
    "block-runner",
    "sand-slice",
    "marble-loop",
)


@pytest.mark.parametrize("background_id", _PACKAGED_IDS)
def test_packaged_backgrounds_materialize_without_network(background_id: str):
    clip = library.get(background_id)
    assert clip is not None
    assert clip.source == "bundled"
    assert clip.needs_asset is False

    paths = library.materialize(clip, task_id="job_1", duration_s=30)

    assert len(paths) == 1
    path = Path(paths[0]).resolve()
    assert path.parent == library._ASSET_ROOT
    assert path.read_bytes()[4:8] == b"ftyp"


def test_packaged_background_is_preferred_over_stock_fallback():
    resolved = library.resolve("minecraft-parkour", prefer_available=True)
    assert resolved is not None
    assert resolved.id == "voxel-parkour"
    assert library.to_dict(resolved)["available"] is True


def test_packaged_path_cannot_escape_asset_root():
    clip = library.get("minecraft-parkour")
    assert clip is not None
    with pytest.raises(library.BackgroundUnavailable, match="invalid packaged"):
        library.materialize(
            replace(clip, asset_path="../secret.mp4"),
            task_id="job_1",
            duration_s=30,
        )


def test_missing_packaged_asset_fails_explicitly():
    clip = library.get("minecraft-parkour")
    assert clip is not None
    with pytest.raises(library.BackgroundUnavailable, match="asset is missing"):
        library.materialize(
            replace(clip, asset_path="does-not-exist.mp4"),
            task_id="job_1",
            duration_s=30,
        )


def test_stock_background_uses_injected_downloader():
    clip = library.get("generic-parkour")
    assert clip is not None
    calls: list[tuple] = []

    def downloader(*args, **kwargs):
        calls.append((args, kwargs))
        return ["/tmp/stock.mp4"]

    assert library.materialize(
        clip, task_id="job_2", duration_s=12, downloader=downloader
    ) == ["/tmp/stock.mp4"]
    assert calls[0][0] == ("job_2", [clip.query])
    assert calls[0][1]["source"] == clip.provider


def test_remote_operator_owned_bundle_path_remains_supported():
    clip = library.BackgroundClip(
        "operator-loop",
        library.NATURE,
        "Operator loop",
        "bundled",
        r2_key="library/backgrounds/operator-loop.mp4",
    )
    requested: list[str] = []

    def storage(key: str) -> str:
        requested.append(key)
        return "/tmp/operator-loop.mp4"

    assert library.materialize(
        clip, task_id="job_3", duration_s=8, storage=storage
    ) == ["/tmp/operator-loop.mp4"]
    assert requested == [clip.r2_key]


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
@pytest.mark.parametrize("background_id", _PACKAGED_IDS)
def test_packaged_background_is_valid_vertical_h264(background_id: str):
    clip = library.get(background_id)
    assert clip is not None
    path = library.materialize(clip, task_id="probe", duration_s=4)[0]
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height",
            "-of",
            "csv=p=0",
            path,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "h264,720,1280"
