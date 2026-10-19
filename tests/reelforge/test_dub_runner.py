"""Dub HTTP mode: the sidecar runner service and the worker's client (no docker socket in the worker).

The runner is stdlib-only and is loaded from its file; the CLI it runs is replaced
by a fake, so neither pyvideotrans nor docker is needed here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from app.domains.dub import catalog
from app.domains.dub import sidecar as dub_sidecar

RUNNER_PATH = Path(__file__).resolve().parents[2] / "apps/api/sidecars/pyvideotrans/runner.py"
TOKEN = "t" * 32

_PLAN = {
    "source_language": "en",
    "target_language": "tr",
    "voice_engine": "edge",
    "voice": "tr-TR-EmelNeural",
    "whisper_model": "small",
    "translation": "google",
}


def _load_runner():
    spec = importlib.util.spec_from_file_location("menivor_dub_runner", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner_mod = _load_runner()


def _body(root, **kw):
    job = Path(root) / "job"
    return {"args": dub_sidecar.cli_args(str(job), _PLAN), "env": {}, "timeout_s": 120, **kw}


# --------------------------------------------------------------------------- #
# Runner: request validation
# --------------------------------------------------------------------------- #
def test_runner_accepts_the_worker_cli_args(tmp_path):
    args, env, timeout = runner_mod.validate_request(_body(tmp_path, env={"PVT_LLM_KEY": "k"}), str(tmp_path), 3600)
    assert args[:2] == ["--task", "vtv"] and env == {"PVT_LLM_KEY": "k"} and timeout == 120


@pytest.mark.parametrize("mutate,match", [
    (lambda b: b.update(args=["--task", "stt", *b["args"][2:]]), "only --task vtv"),
    (lambda b: b["args"].__setitem__(b["args"].index("--name") + 1, "/etc/passwd"), "--name must be inside"),
    (lambda b: b["args"].__setitem__(b["args"].index("--output-dir") + 1, "/tmp/../etc"), "--output-dir must be"),
    (lambda b: b.update(env={"LD_PRELOAD": "/x.so"}), "PVT_"),
    (lambda b: b.update(args="--task vtv"), "non-empty list"),
    (lambda b: b.update(args=["--task", "vtv", ""]), "short non-empty"),
])
def test_runner_refuses_bad_requests(tmp_path, mutate, match):
    body = _body(tmp_path)
    mutate(body)
    with pytest.raises(runner_mod.BadRequest, match=match):
        runner_mod.validate_request(body, str(tmp_path), 3600)


def test_runner_clamps_timeout(tmp_path):
    _, _, timeout = runner_mod.validate_request(_body(tmp_path, timeout_s=99999), str(tmp_path), 3600)
    assert timeout == 3600
    _, _, low = runner_mod.validate_request(_body(tmp_path, timeout_s=1), str(tmp_path), 3600)
    assert low == 60


def test_runner_needs_a_real_token(tmp_path):
    with pytest.raises(SystemExit):
        runner_mod.Runner(token="short", work_root=str(tmp_path), max_timeout_s=60, entrypoint="/bin/true")


# --------------------------------------------------------------------------- #
# Runner over HTTP (real server on localhost, fake CLI)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def served(tmp_path):
    runner = runner_mod.Runner(token=TOKEN, work_root=str(tmp_path), max_timeout_s=600, entrypoint="/bin/true")
    calls = []

    def fake_cli(entrypoint, args, secrets, timeout_s):
        calls.append((args, secrets))
        out = Path(args[args.index("--output-dir") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "input.mp4").write_bytes(b"dubbed")
        (out / "tr.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nMerhaba\n")
        return {"timeout": False, "returncode": 0, "log_tail": "ok"}

    runner.run_cli = fake_cli
    server = ThreadingHTTPServer(("127.0.0.1", 0), runner_mod.make_handler(runner))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield runner, f"http://127.0.0.1:{server.server_address[1]}", calls
    server.shutdown()


def _post(url, token, payload):
    return dub_sidecar._http_post(url + "/run", token, payload, 30)


def test_runner_http_auth_and_health(served, tmp_path):
    runner, url, calls = served
    with urllib.request.urlopen(url + "/healthz", timeout=5) as resp:
        assert json.loads(resp.read()) == {"ok": True, "busy": False}
    status, body = _post(url, "wrong-token", _body(tmp_path))
    assert status == 401 and calls == []
    status, body = _post(url, TOKEN, {"args": ["--task", "vtv"]})
    assert status == 400 and calls == []


def test_runner_refuses_a_second_job_while_busy(served, tmp_path):
    runner, url, _ = served
    runner.lock.acquire()
    try:
        status, body = _post(url, TOKEN, _body(tmp_path))
    finally:
        runner.lock.release()
    assert status == 409 and body["error"] == "busy"


def test_runner_reports_timeout(served, tmp_path):
    runner, url, _ = served
    runner.run_cli = lambda *a: {"timeout": True, "returncode": -9, "log_tail": "slow"}
    status, body = _post(url, TOKEN, _body(tmp_path))
    assert status == 504 and body["error"] == "timeout"


def test_runner_cli_kills_on_timeout_and_strips_runner_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DUB_RUNNER_TOKEN", TOKEN)
    script = tmp_path / "cli.sh"
    script.write_text("#!/bin/sh\necho token=${DUB_RUNNER_TOKEN:-none} key=${PVT_LLM_KEY:-none}\n")
    script.chmod(0o755)
    out = runner_mod.run_cli(str(script), ["--task", "vtv"], {"PVT_LLM_KEY": "k1"}, 30)
    assert out["returncode"] == 0 and "token=none key=k1" in out["log_tail"]
    slow = tmp_path / "slow.sh"
    slow.write_text("#!/bin/sh\nsleep 30\n")
    slow.chmod(0o755)
    monkeypatch.setattr(runner_mod.subprocess.Popen, "communicate", _fast_timeout(runner_mod.subprocess.Popen.communicate))
    assert runner_mod.run_cli(str(slow), [], {}, 1)["timeout"] is True


def _fast_timeout(original):
    def communicate(self, timeout=None):
        if timeout is not None:
            return original(self, timeout=0.2)
        return original(self)

    return communicate


# --------------------------------------------------------------------------- #
# Worker client (HTTP mode end to end against the real runner)
# --------------------------------------------------------------------------- #
def _http_settings(tmp_path, url, **kw):
    return dub_sidecar.SidecarSettings(image="", url=url, token=TOKEN, lock_path=str(tmp_path / "dub.lock"),
                                       work_root=str(tmp_path), **kw)


def test_run_dub_over_http_collects_outputs_and_sends_secrets_in_body(served, tmp_path, monkeypatch):
    _, url, calls = served
    monkeypatch.setattr(dub_sidecar, "_elevenlabs_key", lambda: "el-secret")
    work = tmp_path / "job"
    work.mkdir()
    plan = {**_PLAN, "voice_engine": "elevenlabs", "voice": "Rachel"}
    result = dub_sidecar.run_dub(job_id="job", work_dir=str(work), plan=plan, settings=_http_settings(tmp_path, url))
    args, secrets = calls[0]
    assert args[args.index("--name") + 1] == f"{work}/input.mp4"
    assert secrets == {"PVT_ELEVENLABS_KEY": "el-secret"} and "el-secret" not in " ".join(args)
    assert result.video_path.endswith("input.mp4") and set(result.subtitle_paths) == {"tr"}


@pytest.mark.parametrize("status,body,error", [
    (409, {"error": "busy"}, dub_sidecar.SidecarBusy),
    (504, {"error": "timeout"}, dub_sidecar.SidecarError),
    (401, {"error": "unauthorized"}, dub_sidecar.SidecarError),
    (200, {"returncode": 2, "log_tail": "boom"}, dub_sidecar.SidecarError),
])
def test_run_dub_over_http_maps_runner_errors(tmp_path, monkeypatch, status, body, error):
    monkeypatch.setattr(dub_sidecar, "_http_post", lambda *a: (status, body))
    with pytest.raises(error):
        dub_sidecar.run_dub(job_id="j", work_dir=str(tmp_path), plan=_PLAN, settings=_http_settings(tmp_path, "http://x"))


def test_run_dub_over_http_unreachable_and_missing_token(tmp_path, monkeypatch):
    def refuse(*a):
        raise ConnectionRefusedError("nope")

    monkeypatch.setattr(dub_sidecar, "_http_post", refuse)
    with pytest.raises(dub_sidecar.SidecarError, match="unreachable"):
        dub_sidecar.run_dub(job_id="j", work_dir=str(tmp_path), plan=_PLAN, settings=_http_settings(tmp_path, "http://x"))
    with pytest.raises(dub_sidecar.SidecarError, match="DUB_SIDECAR_TOKEN"):
        dub_sidecar.run_dub(job_id="j", work_dir=str(tmp_path), plan=_PLAN,
                            settings=dub_sidecar.SidecarSettings(image="", url="http://x", work_root=str(tmp_path)))


def test_settings_and_catalog_read_http_mode_from_env(monkeypatch):
    env = {"DUB_SIDECAR_URL": "http://dub:8090/", "DUB_SIDECAR_TOKEN": TOKEN}
    settings = dub_sidecar.settings_from_config(env)
    assert settings.url == "http://dub:8090" and settings.token == TOKEN
    assert TOKEN not in repr(settings)
    assert catalog.sidecar_configured(env) is True
    assert catalog.sidecar_configured({}) is False


# --------------------------------------------------------------------------- #
# Relay names and the default translate model; constraints helper
# --------------------------------------------------------------------------- #
def test_box_relay_name_turns_on_relay_translation_with_claude():
    env = {"RAILYARD_RELAY_URL": "https://relay.example", "RAILYARD_RELAY_API_KEY": "rk"}
    assert catalog.translation_engine(env) == "relay"
    target = dub_sidecar.relay_target(env)
    assert target["api"] == "https://relay.example/openai/v1" and target["key"] == "rk"
    assert target["model"] == "tensorzero::model_name::anthropic::claude-haiku-4-5-20251001"
    assert catalog.translation_engine({}) == "google" and dub_sidecar.relay_target({}) is None


def test_constraints_come_from_upstream_pins_with_overrides_winning():
    spec = importlib.util.spec_from_file_location("mk", RUNNER_PATH.with_name("make_constraints.py"))
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    text = '''dependencies = ["numpy==1.26.0", "requests[socks]==2.32.5", "torch==2.7.1", "openai"]
override-dependencies = ["huggingface-hub==1.10.0", "numpy==2.0.0", "torchcodec ; sys_platform == 'never'"]'''
    assert mk.constraints(text) == "huggingface-hub==1.10.0\nnumpy==2.0.0\nrequests==2.32.5\n"


def test_run_dub_over_http_explains_a_video_with_no_speech(tmp_path, monkeypatch):
    """pyvideotrans' VAD finding no voice is the uploader's fix, not an engine bug."""
    tail = (
        "[Failed] Task error: No human voice detected. Please confirm that human speech "
        "is present in the original file. [info.duration_after_vad=0.0s]."
    )
    monkeypatch.setattr(dub_sidecar, "_http_post", lambda *a: (200, {"returncode": 1, "log_tail": tail}))
    with pytest.raises(dub_sidecar.SidecarError, match="couldn't hear anyone speaking"):
        dub_sidecar.run_dub(job_id="j", work_dir=str(tmp_path), plan=_PLAN, settings=_http_settings(tmp_path, "http://x"))


def test_engine_failure_message_keeps_the_exit_code_for_unknown_errors():
    assert dub_sidecar.engine_failure_message(2, "Traceback: boom") == "dub engine failed (exit 2)"
