"""CMAF packaging with shaka-packager (BSD-3-Clause, pinned v3.9.3, checksum verified at start).

One run produces clear fMP4 CMAF segments shared by an HLS master playlist and a
DASH MPD. Tier 1 protection (ADR-0003) for non-free titles is HLS AES-128:
every media playlist gets ``#EXT-X-KEY:METHOD=AES-128`` pointing at our key
server (``key_uri``, with an explicit IV because the init section is encrypted
too) and each init section and segment is encrypted with AES-128-CBC. This
plays natively in Safari and in hls.js everywhere, with no EME. Protected
titles publish HLS only (the DASH manifest is removed: DASH would need a
separate CENC packaging). The key never appears in a manifest; the key server
(MV5) releases it only with a valid playback token.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .ladder_profiles import SEGMENT_SECONDS
from .tracks import Track

SIDECAR = Path(__file__).resolve().parents[3] / "sidecars" / "shaka-packager"
VERSION = (SIDECAR / "VERSION").read_text(encoding="utf-8").strip() if (SIDECAR / "VERSION").exists() else ""
BIN_ENV = "SHAKA_PACKAGER_BIN"
MASTER = "master.m3u8"
MPD = "manifest.mpd"


class PackagerError(RuntimeError):
    pass


def expected_sha256(platform: str) -> str:
    for line in (SIDECAR / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, _, name = line.strip().partition("  ")
        if name == f"packager-{platform}":
            return digest
    raise PackagerError(f"no pinned checksum for packager-{platform}")


def verify_binary(path: str, platform: str) -> str:
    """Refuse to package with a binary that is not the pinned build."""
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if digest != expected_sha256(platform):
        raise PackagerError(f"packager checksum mismatch for {platform}")
    return digest


@dataclass(frozen=True)
class Protection:
    key_hex: str
    iv_hex: str
    key_uri: str

    def __post_init__(self) -> None:
        for value in (self.key_hex, self.iv_hex):
            if len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("key and IV are 16 bytes of lowercase hex")


def command(packager: str, *, video: Sequence[tuple[str, str]], audio: str | None, out_dir: str,
            tracks: Sequence[Track] = ()) -> list[str]:
    """``video`` is ``[(rung name, mp4 path)]``; outputs land under ``out_dir``."""
    streams = []
    for name, path in video:
        streams.append(f"in={path},stream=video,init_segment={out_dir}/v_{name}/init.mp4,"
                       f"segment_template={out_dir}/v_{name}/$Number$.m4s,playlist_name=v_{name}.m3u8")
    if audio:
        streams.append(f"in={audio},stream=audio,init_segment={out_dir}/a_main/init.mp4,"
                       f"segment_template={out_dir}/a_main/$Number$.m4s,playlist_name=a_main.m3u8,"
                       "hls_group_id=audio,hls_name=Main")
    for i, track in enumerate(tracks):
        if track.kind == "audio":
            streams.append(f"in={track.path},stream=audio,language={track.language},"
                           f"init_segment={out_dir}/a_{i}/init.mp4,segment_template={out_dir}/a_{i}/$Number$.m4s,"
                           f"playlist_name=a_{i}.m3u8,hls_group_id=audio,hls_name={track.name}")
        else:
            streams.append(f"in={track.path},stream=text,language={track.language},"
                           f"output={out_dir}/t_{i}.vtt,playlist_name=t_{i}.m3u8,hls_group_id=subs,"
                           f"hls_name={track.name}")
    args = [packager, *streams, "--segment_duration", str(SEGMENT_SECONDS), "--hls_master_playlist_output",
            f"{out_dir}/{MASTER}", "--mpd_output", f"{out_dir}/{MPD}", "--hls_playlist_type", "VOD"]
    return args


def _encrypt_file(path: Path, key: bytes, iv: bytes) -> None:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    padder = padding.PKCS7(128).padder()
    data = padder.update(path.read_bytes()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    path.write_bytes(encryptor.update(data) + encryptor.finalize())


def protect_hls(out_dir: str, protection: Protection) -> list[str]:
    """Encrypt every media playlist's init section and segments (AES-128) and add the key tag.

    Returns the playlists changed. Subtitles stay clear. The DASH manifest is removed.
    """
    root = Path(out_dir)
    key, iv = bytes.fromhex(protection.key_hex), bytes.fromhex(protection.iv_hex)
    tag = f'#EXT-X-KEY:METHOD=AES-128,URI="{protection.key_uri}",IV=0x{protection.iv_hex}'
    changed = []
    for playlist in sorted(root.glob("*.m3u8")):
        if playlist.name == MASTER:
            continue
        lines = playlist.read_text(encoding="utf-8").splitlines()
        if not any(line.startswith("#EXTINF") for line in lines) or any("EXT-X-KEY" in line for line in lines):
            continue
        media = [line for line in lines if line and not line.startswith("#")]
        if all(name.endswith(".vtt") for name in media):
            continue
        out, tagged = [], False
        for line in lines:
            if not tagged and (line.startswith("#EXT-X-MAP") or line.startswith("#EXTINF")):
                out.append(tag)
                tagged = True
            if line.startswith("#EXT-X-MAP"):
                uri = line.split('URI="', 1)[1].split('"', 1)[0]
                _encrypt_file(root / uri, key, iv)
            out.append(line)
        for name in media:
            _encrypt_file(root / name, key, iv)
        playlist.write_text("\n".join(out) + "\n", encoding="utf-8")
        changed.append(playlist.name)
    mpd = root / MPD
    if mpd.exists():
        mpd.unlink()
    return changed


def packager_bin() -> str:
    path = os.getenv(BIN_ENV) or "/usr/local/bin/packager"
    if not os.path.exists(path):
        raise PackagerError("the packager is not installed on this worker")
    return path


__all__ = ["MASTER", "MPD", "PackagerError", "Protection", "VERSION", "command", "expected_sha256", "packager_bin",
           "protect_hls", "verify_binary"]
