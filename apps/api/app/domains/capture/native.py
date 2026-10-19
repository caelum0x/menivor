"""Native game capture: record gameplay from an iOS Simulator or Android emulator.

Our games are native mobile apps (Expo), so gameplay is recorded from a
simulator/emulator running on the capture host, not from a browser:

* iOS: ``xcrun simctl io <device> recordVideo --codec=h264 --force <file>``,
  stopped with SIGINT after the recording length. Needs macOS with Xcode.
* Android: ``adb -s <serial> shell screenrecord --time-limit <s> <file>`` on
  the device, then ``adb pull``. Needs the Android platform tools.

Before recording, the game is brought up in one of three ways: a deep link
(``simctl openurl`` / ``am start -a VIEW -d``), launching the app by bundle id
or package name (``simctl launch`` / ``monkey -p``), or neither (the operator
already launched it). See ``DEMO_MODE.md`` for the demo deep-link contract.

Every value that reaches a command line is validated against a strict pattern
and passed as an argv list (no local shell). The Android deep link crosses the
device shell, so it is additionally quoted with :func:`shlex.quote`.

The feature is off unless the operator enables it (``[app] capture_native_game
= true``) and, when ``capture_native_app_ids`` is set, only those bundle ids /
package names can be captured.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.domains.capture.browser import Recording

PLATFORM_IOS = "ios"
PLATFORM_ANDROID = "android"
PLATFORMS = (PLATFORM_IOS, PLATFORM_ANDROID)

#: Simulator UDID / name alias ("booted") or adb serial ("emulator-5554", "127.0.0.1:5555").
_DEVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
#: iOS bundle id or Android package name.
_APP_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)+$")
#: Custom-scheme or https deep link without whitespace, quotes, backticks, parens, <, >, \ or |.
_DEEP_LINK = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]{0,31}://[A-Za-z0-9._~:/?#@!$&*+,;=%\[\]-]{0,480}$")
_TITLE_MAX = 80

SETTLE_DEFAULT_S = 4
SETTLE_MAX_S = 30
COMMAND_TIMEOUT_S = 60
STOP_TIMEOUT_S = 20
ANDROID_MAX_S = 180
ANDROID_REMOTE_DIR = "/sdcard"

INSTALL_HINT_IOS = "iOS game capture needs macOS with Xcode command line tools (xcrun simctl) on the capture host"
INSTALL_HINT_ANDROID = "Android game capture needs the Android platform tools (adb) on the capture host"


class NativeCaptureError(RuntimeError):
    """A user-presentable native capture failure."""


class NativeTargetError(ValueError):
    """Invalid native capture target (HTTP 422)."""


@dataclass(frozen=True)
class NativeTarget:
    platform: str
    device: str
    app_id: str = ""
    deep_link: str = ""
    title: str = ""
    settle_s: int = SETTLE_DEFAULT_S

    def as_options(self) -> dict[str, Any]:
        return {
            "platform": self.platform, "device": self.device, "app_id": self.app_id,
            "deep_link": self.deep_link, "title": self.title, "settle_s": self.settle_s,
        }

    def source_url(self) -> str:
        """Stable, non-secret label stored as the capture's ``source_url``."""
        if self.deep_link:
            return self.deep_link
        return f"{self.platform}-device://{self.device}/{self.app_id or 'running-app'}"


def parse_target(raw: dict[str, Any] | None, *, allowed_app_ids: tuple[str, ...] = ()) -> NativeTarget:
    """Validate a native target; raises :class:`NativeTargetError` with a clear message."""
    raw = dict(raw or {})
    platform = str(raw.get("platform") or "").strip().lower()
    if platform not in PLATFORMS:
        raise NativeTargetError("pick the platform: ios (Simulator) or android (emulator)")
    device = str(raw.get("device") or "").strip() or ("booted" if platform == PLATFORM_IOS else "")
    if not device:
        raise NativeTargetError("give the emulator's adb serial, e.g. emulator-5554")
    if not _DEVICE.match(device):
        raise NativeTargetError("the device must be a simulator UDID, 'booted' or an adb serial")
    app_id = str(raw.get("app_id") or "").strip()
    if app_id and (len(app_id) > 150 or not _APP_ID.match(app_id)):
        raise NativeTargetError("the app id must be a bundle id or package name, e.g. com.example.game")
    deep_link = str(raw.get("deep_link") or "").strip()
    if deep_link and not _DEEP_LINK.match(deep_link):
        raise NativeTargetError("the deep link must look like mygame://play (no spaces or quotes)")
    if allowed_app_ids:
        if not app_id:
            raise NativeTargetError("this server only captures listed games; give the app id")
        if app_id not in allowed_app_ids:
            raise NativeTargetError("this app id is not on the server's native capture list")
    title = " ".join(str(raw.get("title") or "").split())[:_TITLE_MAX]
    try:
        settle = int(raw.get("settle_s", SETTLE_DEFAULT_S))
    except (TypeError, ValueError) as exc:
        raise NativeTargetError("settle_s must be a whole number of seconds") from exc
    if not 0 <= settle <= SETTLE_MAX_S:
        raise NativeTargetError(f"settle_s must be between 0 and {SETTLE_MAX_S} seconds")
    return NativeTarget(platform=platform, device=device, app_id=app_id, deep_link=deep_link, title=title,
                        settle_s=settle)


# --------------------------------------------------------------------------- #
# Command plans (pure; unit-tested)
# --------------------------------------------------------------------------- #
def launch_commands(target: NativeTarget, tool: str) -> list[list[str]]:
    """Commands that bring the game to the foreground (empty when the operator launched it)."""
    if target.platform == PLATFORM_IOS:
        if target.deep_link:
            return [[tool, "simctl", "openurl", target.device, target.deep_link]]
        if target.app_id:
            return [[tool, "simctl", "launch", "--terminate-running-process", target.device, target.app_id]]
        return []
    if target.deep_link:
        view = ["shell", "am", "start", "-W", "-a", "android.intent.action.VIEW", "-d", shlex.quote(target.deep_link)]
        if target.app_id:
            view += ["-p", target.app_id]
        return [[tool, "-s", target.device, *view]]
    if target.app_id:
        return [[tool, "-s", target.device, "shell", "monkey", "-p", target.app_id,
                 "-c", "android.intent.category.LAUNCHER", "1"]]
    return []


def record_command(target: NativeTarget, tool: str, out: str, seconds: int) -> list[str]:
    if target.platform == PLATFORM_IOS:
        return [tool, "simctl", "io", target.device, "recordVideo", "--codec=h264", "--force", out]
    return [tool, "-s", target.device, "shell", "screenrecord", "--time-limit", str(seconds), out]


def screenshot_command(target: NativeTarget, tool: str, out: str) -> list[str]:
    if target.platform == PLATFORM_IOS:
        return [tool, "simctl", "io", target.device, "screenshot", "--type=jpeg", out]
    return [tool, "-s", target.device, "exec-out", "screencap", "-p"]


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #
Runner = Callable[..., subprocess.CompletedProcess]


def _tool(platform: str) -> str:
    name = "xcrun" if platform == PLATFORM_IOS else "adb"
    found = shutil.which(name)
    if not found:
        raise NativeCaptureError(INSTALL_HINT_IOS if platform == PLATFORM_IOS else INSTALL_HINT_ANDROID)
    return found


def _run(cmd: list[str], runner: Runner = subprocess.run, timeout: int = COMMAND_TIMEOUT_S) -> bytes:
    try:
        proc = runner(cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise NativeCaptureError(f"'{cmd[1]} {cmd[2]}' timed out on the capture host") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()[-2:]
        raise NativeCaptureError(f"device command failed: {' | '.join(tail)[:300] or 'exit ' + str(proc.returncode)}")
    return proc.stdout or b""


def _record_ios(target: NativeTarget, tool: str, out: str, seconds: int, shot: str) -> list[tuple[str, str]]:
    shots: list[tuple[str, str]] = []
    proc = subprocess.Popen(  # noqa: S603 - argv list, validated values
        record_command(target, tool, out, seconds), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        time.sleep(seconds / 2)
        if proc.poll() is not None:
            err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", errors="replace").strip()
            raise NativeCaptureError(f"the simulator stopped recording: {err[-300:] or 'is the device booted?'}")
        try:
            _run(screenshot_command(target, tool, shot))
            shots.append((shot, "gameplay"))
        except NativeCaptureError:
            pass  # the video matters; a missing still is fine
        time.sleep(seconds - seconds / 2)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)  # simctl finalizes the file on SIGINT
            try:
                proc.wait(timeout=STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    return shots


def _android_still(target: NativeTarget, tool: str, shot: str) -> bool:
    """``screencap`` gives PNG bytes; store them as the JPEG the worker uploads."""
    try:
        png = _run(screenshot_command(target, tool, shot))
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(png)) as img:
            img.convert("RGB").save(shot, "JPEG", quality=90)
        return True
    except Exception:  # noqa: BLE001 - the video matters; a missing still is fine
        return False


def _record_android(target: NativeTarget, tool: str, out: str, seconds: int, shot: str,
                    remote_name: str) -> list[tuple[str, str]]:
    seconds = min(seconds, ANDROID_MAX_S)
    remote = f"{ANDROID_REMOTE_DIR}/{remote_name}"
    shots: list[tuple[str, str]] = []
    proc = subprocess.Popen(  # noqa: S603 - argv list, validated values
        record_command(target, tool, remote, seconds), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        time.sleep(seconds / 2)
        if _android_still(target, tool, shot):
            shots.append((shot, "gameplay"))
        try:
            proc.wait(timeout=seconds + STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        if proc.returncode not in (0, None):
            err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", errors="replace").strip()
            raise NativeCaptureError(f"screenrecord failed: {err[-300:] or 'is the emulator running?'}")
        _run([tool, "-s", target.device, "pull", remote, out], timeout=COMMAND_TIMEOUT_S * 2)
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            subprocess.run([tool, "-s", target.device, "shell", "rm", "-f", remote],  # noqa: S603
                           capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return shots


def record_native(target: NativeTarget, duration_s: float, work_dir: str, *, capture_id: str) -> Recording:
    """Launch (optionally) and record ``duration_s`` of gameplay; returns the raw recording."""
    tool = _tool(target.platform)
    for cmd in launch_commands(target, tool):
        _run(cmd)
    time.sleep(target.settle_s)
    seconds = max(1, int(round(duration_s)))
    out = os.path.join(work_dir, f"native-{target.platform}.mp4")
    shot = os.path.join(work_dir, "shot-native-mid.jpg")
    started = time.monotonic()
    if target.platform == PLATFORM_IOS:
        shots = _record_ios(target, tool, out, seconds, shot)
    else:
        shots = _record_android(target, tool, out, seconds, shot, f"menivor-{capture_id[:12]}.mp4")
    if not os.path.isfile(out) or os.path.getsize(out) == 0:
        raise NativeCaptureError("the device produced no recording")
    meta = {
        "title": target.title or target.app_id or "",
        "platform": target.platform,
        "app_id": target.app_id,
        "capture_mode": f"native_{target.platform}",
    }
    return Recording(video_path=out, lead_in_s=0.0, recorded_s=time.monotonic() - started, screenshots=shots,
                     page_meta=meta)


__all__ = [
    "NativeCaptureError",
    "NativeTarget",
    "NativeTargetError",
    "PLATFORMS",
    "launch_commands",
    "parse_target",
    "record_command",
    "record_native",
    "screenshot_command",
]
