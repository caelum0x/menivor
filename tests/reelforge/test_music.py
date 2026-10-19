"""Unit tests for the ReelForge background-music library (app/services/music.py).

Covers:
  * list_music()      — scans resource/songs for supported audio, stable ids
  * get_music_path()  — safe resolution inside resource/songs, None handling
  * traversal / symlink rejection — path escapes never resolve to a real file

The songs directory is redirected to a pytest ``tmp_path`` by monkeypatching
``utils.song_dir`` (used by ``music._songs_dir``), so the tests never depend on
the tracks MPT happens to ship and never touch the real resource directory.
"""

from __future__ import annotations

import os

import pytest

from app.services import music


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def songs_dir(tmp_path, monkeypatch):
    """Redirect the music library at an isolated temp songs directory."""
    directory = tmp_path / "songs"
    directory.mkdir()
    monkeypatch.setattr(music.utils, "song_dir", lambda sub_dir="": str(directory))
    # Duration probing is best-effort; force it off so listing is deterministic
    # and does not depend on ffprobe being installed in the test environment.
    monkeypatch.setattr(music, "_ffprobe_binary", lambda: None)
    return directory


def _touch(directory, name: str, data: bytes = b"\x00\x01\x02") -> str:
    path = directory / name
    path.write_bytes(data)
    return str(path)


# --------------------------------------------------------------------------- #
# list_music
# --------------------------------------------------------------------------- #
def test_list_music_empty_directory(songs_dir):
    assert music.list_music() == []


def test_list_music_lists_supported_audio_only(songs_dir):
    _touch(songs_dir, "Chill Beat.mp3")
    _touch(songs_dir, "track_two.wav")
    _touch(songs_dir, "third.m4a")
    _touch(songs_dir, "notes.txt")  # ignored
    _touch(songs_dir, "clip.mp4")   # ignored

    items = music.list_music()
    filenames = {item["filename"] for item in items}
    assert filenames == {"Chill Beat.mp3", "track_two.wav", "third.m4a"}

    for item in items:
        assert set(item.keys()) >= {"id", "name", "filename"}
        assert isinstance(item["id"], str) and item["id"]
        # duration_s is optional and suppressed here (no ffprobe)
        assert "duration_s" not in item


def test_list_music_ids_are_stable_slugs(songs_dir):
    _touch(songs_dir, "Chill Beat.mp3")
    first = music.list_music()
    second = music.list_music()
    assert first == second  # deterministic across calls

    (item,) = first
    assert item["id"] == "chill-beat"
    assert item["name"] == "Chill Beat"


def test_list_music_disambiguates_slug_collisions(songs_dir):
    # Both slugify to "same-track"; ids must remain unique + reproducible.
    _touch(songs_dir, "same track.mp3")
    _touch(songs_dir, "same_track.wav")

    ids = [item["id"] for item in music.list_music()]
    assert len(ids) == len(set(ids)) == 2
    assert "same-track" in ids
    assert any(i.startswith("same-track-") for i in ids)


# --------------------------------------------------------------------------- #
# get_music_path
# --------------------------------------------------------------------------- #
def test_get_music_path_resolves_known_id(songs_dir):
    expected = _touch(songs_dir, "Chill Beat.mp3")
    (item,) = music.list_music()

    resolved = music.get_music_path(item["id"])
    assert resolved is not None
    assert os.path.realpath(resolved) == os.path.realpath(expected)
    assert os.path.isfile(resolved)


@pytest.mark.parametrize("bad_id", [None, "", "   ", "does-not-exist"])
def test_get_music_path_returns_none_for_missing(songs_dir, bad_id):
    _touch(songs_dir, "Chill Beat.mp3")
    assert music.get_music_path(bad_id) is None


@pytest.mark.parametrize(
    "payload",
    [
        "../../etc/passwd",
        "..%2f..%2fetc%2fpasswd",
        "/etc/passwd",
        "chill-beat/../../../../etc/passwd",
    ],
)
def test_get_music_path_rejects_traversal(songs_dir, payload):
    _touch(songs_dir, "Chill Beat.mp3")
    # None of these match a scanned id, so nothing is resolved.
    assert music.get_music_path(payload) is None


# --------------------------------------------------------------------------- #
# symlink escape rejection (defence-in-depth in _scan)
# --------------------------------------------------------------------------- #
def test_list_music_skips_symlink_escaping_directory(songs_dir, tmp_path):
    outside = tmp_path / "secret.mp3"
    outside.write_bytes(b"\x00\x01")
    link = songs_dir / "evil.mp3"
    try:
        os.symlink(str(outside), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    _touch(songs_dir, "Chill Beat.mp3")

    filenames = {item["filename"] for item in music.list_music()}
    assert "evil.mp3" not in filenames
    assert "Chill Beat.mp3" in filenames
    # And the escaping symlink is not resolvable by any id.
    assert music.get_music_path("evil") is None
