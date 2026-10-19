"""RunPod InfiniteTalk worker (infinitetalk / infinitetalk_dub) and the API adapter, end to end, no GPU.

The fake RunPod endpoint below runs the real worker handler in-process, so the adapter's
request and the worker's input contract are checked against each other.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from app.domains.lipsync_translate import engines, pipeline

HANDLER = Path(__file__).resolve().parents[2] / "infra" / "render-workers" / "infinitetalk" / "handler.py"
ENV = {"MEDIA_ALLOWED_HOSTS": "media.menivor.test", "INFINITETALK_DIR": "/opt/it"}
VIDEO = "https://media.menivor.test/studio/source.mp4"


def _load():
    spec = importlib.util.spec_from_file_location("infinitetalk_handler", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module by name
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def worker():
    return _load()


class FakeGpu:
    """Stands in for ffmpeg, the InfiniteTalk script, the media download and the bucket."""

    def __init__(self, fail_model=False):
        self.calls, self.specs, self.uploads, self.fail_model = [], [], [], fail_model

    def download(self, url, dest, max_bytes):
        self.calls.append(("download", url))
        Path(dest).write_bytes(b"source-video")
        return dest

    def run(self, argv, cwd):
        self.calls.append((Path(argv[1]).name if argv[0] == "python" else argv[0], cwd))
        if argv[0] == "ffmpeg":
            Path(argv[-1]).write_bytes(b"wav")
            return
        if self.fail_model:
            raise self.error_cls("generate_infinitetalk.py failed: CUDA out of memory")
        spec = argv[argv.index("--input_json") + 1]
        self.specs.append(json.loads(Path(spec).read_text()))
        Path(argv[argv.index("--save_file") + 1] + ".mp4").write_bytes(b"lipsynced")

    def upload(self, path, key):
        self.uploads.append((Path(path).read_bytes(), key))
        return f"https://cdn.menivor.test/{key}"


def _deps(worker, gpu, env=ENV):
    gpu.error_cls = worker.WorkerError
    return worker.Deps(env=env, download=gpu.download, run=gpu.run, upload=gpu.upload)


def _audio():
    return base64.b64encode(b"mp3-bytes").decode()


def test_dub_task_downloads_converts_runs_the_model_and_uploads(worker):
    gpu = FakeGpu()
    out = worker.handle({"input": {"task": "infinitetalk_dub", "video_url": VIDEO, "audio_base64": _audio(),
                                   "seconds": 12}}, _deps(worker, gpu))
    assert out["video_url"].startswith("https://cdn.menivor.test/render-workers/infinitetalk/")
    assert out["seconds"] == 12.0 and out["task"] == "infinitetalk_dub"
    assert [c[0] for c in gpu.calls] == ["ffmpeg", "download", "generate_infinitetalk.py"]
    spec = gpu.specs[0]
    assert spec["cond_video"].endswith("source.mp4") and spec["cond_audio"]["person1"].endswith("speech.wav")
    assert gpu.uploads[0][0] == b"lipsynced"
    assert not os.path.exists(os.path.dirname(spec["cond_video"]))  # temp files removed


def test_image_task_uses_the_first_frame(worker):
    gpu = FakeGpu()
    out = worker.handle({"input": {"task": "infinitetalk", "image_base64": base64.b64encode(b"png").decode(),
                                   "audio_base64": _audio(), "seconds": 5, "prompt": "talks"}}, _deps(worker, gpu))
    assert "video_url" in out and gpu.specs[0]["cond_video"].endswith("first_frame.png")
    assert "download" not in [c[0] for c in gpu.calls]


@pytest.mark.parametrize("payload,needle", [
    ({"task": "clone_voice"}, "unknown task"),
    ({"task": "infinitetalk_dub", "video_url": "http://media.menivor.test/a.mp4", "audio_base64": "eA==",
      "seconds": 5}, "https"),
    ({"task": "infinitetalk_dub", "video_url": "https://169.254.169.254/latest", "audio_base64": "eA==",
      "seconds": 5}, "allowed media host"),
    ({"task": "infinitetalk_dub", "video_url": VIDEO, "audio_base64": "not base64!", "seconds": 5}, "base64"),
    ({"task": "infinitetalk_dub", "video_url": VIDEO, "audio_base64": "eA==", "seconds": 999}, "seconds"),
])
def test_bad_input_is_refused_without_running_anything(worker, payload, needle):
    gpu = FakeGpu()
    out = worker.handle({"input": payload}, _deps(worker, gpu))
    assert needle in out["error"]
    assert not any(c[0] == "generate_infinitetalk.py" for c in gpu.calls) and gpu.uploads == []


def test_model_failure_is_reported(worker):
    out = worker.handle({"input": {"task": "infinitetalk_dub", "video_url": VIDEO, "audio_base64": _audio(),
                                   "seconds": 5}}, _deps(worker, FakeGpu(fail_model=True)))
    assert "CUDA out of memory" in out["error"]


def test_model_flags_follow_the_lora_setting(worker):
    plain = worker.model_argv({}, "in.json", "out", "infinitetalk-480")
    fast = worker.model_argv({"INFINITETALK_LORA": "/models/lightx2v.safetensors"}, "in.json", "out", "infinitetalk-480")
    assert plain[plain.index("--sample_steps") + 1] == "40" and "--lora_dir" not in plain
    assert fast[fast.index("--sample_steps") + 1] == "8" and "--lora_dir" in fast
    assert plain[plain.index("--mode") + 1] == "streaming"


class FakeRunpod:
    """RunPod's /run + /status API backed by the real handler."""

    def __init__(self, worker, gpu):
        self.worker, self.gpu, self.jobs, self.requests = worker, gpu, {}, []

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, headers.get("Authorization")))
        if method == "POST" and url.endswith("/run"):
            job = f"job{len(self.jobs) + 1}"
            self.jobs[job] = self.worker.handle(body, _deps(self.worker, self.gpu))
            return 200, {"id": job, "status": "IN_QUEUE"}
        job = url.rsplit("/", 1)[-1]
        return 200, {"id": job, "status": "COMPLETED", "output": self.jobs[job], "executionTime": 90_000}


API_ENV = {"RUNPOD_API_KEY": "rp-key", "RUNPOD_INFINITETALK_ENDPOINT": "ep123"}


def test_adapter_and_worker_agree_and_gpu_time_is_booked(worker):
    fake = FakeRunpod(worker, FakeGpu())
    dub = engines.make_lipsync("infinitetalk", cap_usd=5.0, env=API_ENV, http=fake, sleep=lambda s: None)
    url = dub(video_url=VIDEO, audio=b"mp3", seconds=10)
    assert url.startswith("https://cdn.menivor.test/render-workers/infinitetalk/")
    assert fake.requests[0][1] == "https://api.runpod.ai/v2/ep123/run" and fake.requests[0][2] == "Bearer rp-key"


def test_worker_error_becomes_a_plain_failure(worker):
    fake = FakeRunpod(worker, FakeGpu())
    dub = engines.make_lipsync("infinitetalk", cap_usd=5.0, env={**API_ENV}, http=fake, sleep=lambda s: None)
    with pytest.raises(engines.LipsyncError) as err:
        dub(video_url="https://elsewhere.test/a.mp4", audio=b"mp3", seconds=10)
    assert "allowed media host" in err.value.message


def test_missing_keys_are_reported_before_any_call():
    with pytest.raises(engines.LipsyncError):
        engines.make_lipsync("infinitetalk", cap_usd=5.0, env={})


def test_lipsync_translation_runs_end_to_end_on_infinitetalk(worker, tmp_path):
    gpu = FakeGpu()
    fake = FakeRunpod(worker, gpu)
    plan = {"video_url": VIDEO, "seconds": 8, "source_language": "en", "voice_id": "voice_designed_1",
            "engine": "infinitetalk", "captions": True, "transcript": "Stop overpaying. Try Brewly.",
            "targets": [{"code": "de", "label": "German"}], "output_prefix": "studio/lipsync/abc", "usd": 1.0}
    uploaded = []

    def fetch(url, dest):
        Path(dest).write_bytes(b"video:" + url.encode())
        return dest

    def tts(voice_id, text, out):
        Path(out).write_bytes(text.encode())
        return out

    deps = pipeline.PipelineDeps(
        fetch=fetch, transcribe=lambda path, lang: [], translate=lambda lines, label: [f"[{label}] {x}" for x in lines],
        tts=tts, lipsync=engines.make_lipsync("infinitetalk", cap_usd=2.0, env=API_ENV, http=fake,
                                              sleep=lambda s: None),
        burn=lambda video, cues, out: (Path(out).write_bytes(Path(video).read_bytes()), out)[1],
        upload=lambda path, key, ct: uploaded.append((Path(path).read_bytes(), key)),
        media_url=lambda key: f"https://media.menivor.test/{key}")
    out = pipeline.run_plan(plan, deps=deps)
    assert out["outputs"][0]["video_url"] == "https://media.menivor.test/studio/lipsync/abc/de.mp4"
    assert uploaded[0][0].startswith(b"video:https://cdn.menivor.test/render-workers/infinitetalk/")
    assert gpu.specs and gpu.calls[1] == ("download", VIDEO)
