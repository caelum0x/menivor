"""The ONLY boundary to pyvideotrans: a one-shot ``docker run --rm`` subprocess.

pyvideotrans is GPL-3.0. Menivor never imports it. The worker writes the input
video into a per-job work dir, runs the pinned container image against it over
its CLI (``cli.py --task vtv``) and reads the output files back from disk. That
is arm's-length use of a separate program, so no GPL code lands in our Python
process or in any shipped mobile/web binary.

Secrets (ElevenLabs key, Relay key) are passed as *inherited* environment
variables (``-e NAME`` with the value only in the child's env), so they never
appear in the ``docker`` argv or in ``ps`` output. The container entrypoint
(``apps/api/sidecars/pyvideotrans/entrypoint.sh``) copies them into
pyvideotrans' ``params.json`` before running the CLI.

HTTP mode: with ``DUB_SIDECAR_URL`` set, the worker does not run docker at
all. The sidecar image runs as a long-lived compose service
(``apps/api/sidecars/pyvideotrans/runner.py``) that shares the work dir at the
same path; the worker POSTs the same fixed CLI arguments with a bearer token
(``DUB_SIDECAR_TOKEN``) and secrets in the JSON body. This keeps the docker
socket (root on the host) out of the worker that handles untrusted media.

One dub at a time per host: :func:`host_lock` takes a non-blocking ``flock`` on
a lock file. The Celery task retries later instead of holding a worker slot
when another dub is running (a CPU box can't run two whisper+ffmpeg jobs).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

from loguru import logger

from app.domains.dub import catalog

CONTAINER_WORKDIR = "/work"
INPUT_NAME = "input.mp4"
OUTPUT_DIRNAME = "out"

DEFAULT_TIMEOUT_S = 3600
DEFAULT_CPUS = "2"
DEFAULT_MEMORY = "4g"
DEFAULT_MODELS_VOLUME = "menivor-pyvideotrans-models"
# Translation through Relay is billed to the Anthropic credits behind it.
DEFAULT_TRANSLATE_MODEL = "claude-haiku-4-5-20251001"

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9_.-]")


class SidecarBusy(RuntimeError):
    """Another dub already holds the host lock; retry later."""


class SidecarError(RuntimeError):
    """The container failed, timed out, or produced no dubbed video."""


@dataclass(frozen=True)
class SidecarSettings:
    image: str
    network: str = ""
    cpus: str = DEFAULT_CPUS
    memory: str = DEFAULT_MEMORY
    timeout_s: int = DEFAULT_TIMEOUT_S
    models_volume: str = DEFAULT_MODELS_VOLUME
    docker_bin: str = "docker"
    lock_path: str = "/tmp/menivor-dub.lock"
    work_root: str = "/tmp/menivor-dub"
    # When the worker itself runs in a container that talks to the host docker
    # daemon, bind-mount sources must be HOST paths. ``host_work_root`` is the
    # host path that ``work_root`` is mounted from (empty = same path).
    host_work_root: str = ""
    # HTTP mode (see module doc): the runner service URL and its bearer token.
    url: str = ""
    token: str = field(default="", repr=False)


def settings_from_config(env: Mapping[str, str] | None = None) -> SidecarSettings:
    """Read sidecar settings (env first, then ``[app]`` config)."""
    source = os.environ if env is None else env

    def pick(env_name: str, cfg_name: str, default: str) -> str:
        value = str(source.get(env_name, "") or "").strip()
        if value:
            return value
        if env is None:
            try:
                from app.config import config

                cfg_value = str(config.app.get(cfg_name, "") or "").strip()
                if cfg_value:
                    return cfg_value
            except Exception:  # noqa: BLE001 - config optional
                pass
        return default

    try:
        timeout = int(pick("DUB_SIDECAR_TIMEOUT_S", "dub_sidecar_timeout_s", str(DEFAULT_TIMEOUT_S)))
    except ValueError:
        timeout = DEFAULT_TIMEOUT_S
    return SidecarSettings(
        image=catalog.sidecar_image(env),
        network=pick("DUB_SIDECAR_NETWORK", "dub_sidecar_network", ""),
        cpus=pick("DUB_SIDECAR_CPUS", "dub_sidecar_cpus", DEFAULT_CPUS),
        memory=pick("DUB_SIDECAR_MEMORY", "dub_sidecar_memory", DEFAULT_MEMORY),
        timeout_s=max(60, timeout),
        models_volume=pick("DUB_SIDECAR_MODELS_VOLUME", "dub_sidecar_models_volume", DEFAULT_MODELS_VOLUME),
        docker_bin=pick("DUB_DOCKER_BIN", "dub_docker_bin", "docker"),
        lock_path=pick("DUB_LOCK_PATH", "dub_lock_path", "/tmp/menivor-dub.lock"),
        work_root=pick("DUB_WORK_ROOT", "dub_work_root", "/tmp/menivor-dub"),
        host_work_root=pick("DUB_HOST_WORK_ROOT", "dub_host_work_root", ""),
        url=pick("DUB_SIDECAR_URL", "dub_sidecar_url", "").rstrip("/"),
        token=str(source.get("DUB_SIDECAR_TOKEN", "") or "").strip(),
    )


def container_name(job_id: str) -> str:
    return "menivor-dub-" + _SAFE_NAME.sub("-", str(job_id or "job"))[:48]


def host_path_for(settings: SidecarSettings, local_dir: str) -> str:
    """Map a worker-local work dir to the path the docker daemon sees."""
    if not settings.host_work_root:
        return local_dir
    rel = os.path.relpath(local_dir, settings.work_root)
    if rel.startswith(".."):
        raise SidecarError("work dir is outside the configured work root")
    return os.path.join(settings.host_work_root, rel)


def secret_env(plan: Mapping[str, Any], relay: Mapping[str, str] | None) -> dict[str, str]:
    """Environment the container needs, keyed by the names the entrypoint reads.

    Values are passed through the child process env only (never argv).
    """
    env: dict[str, str] = {}
    if plan.get("voice_engine") == catalog.VOICE_ENGINE_ELEVENLABS:
        env["PVT_ELEVENLABS_KEY"] = _elevenlabs_key()
    if plan.get("translation") == "relay" and relay:
        env["PVT_LLM_API"] = relay.get("api", "")
        env["PVT_LLM_KEY"] = relay.get("key", "") or "none"
        env["PVT_LLM_MODEL"] = relay.get("model", "")
    return env


def _elevenlabs_key() -> str:
    try:
        from app.config import config

        value = str(config.elevenlabs.get("api_key", "") or "").strip()
    except Exception:  # noqa: BLE001
        value = ""
    return value or str(os.environ.get("ELEVENLABS_API_KEY", "") or "").strip()


def relay_target(env: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """OpenAI-compatible Relay target for translation, or ``None`` (free Google path)."""
    try:
        from app.domains.railyard.config import get_relay_config
        from app.domains.railyard.relay import to_tensorzero_model_name
    except Exception:  # noqa: BLE001 - relay package optional
        return None
    source = catalog._relay_env(env)
    cfg = get_relay_config(source)
    if not cfg.configured or not cfg.openai_base_url:
        return None
    model = str(source.get("DUB_TRANSLATE_MODEL", "") or "").strip() or DEFAULT_TRANSLATE_MODEL
    return {
        "api": cfg.openai_base_url,
        "key": cfg.api_key or "",
        "model": to_tensorzero_model_name(model),
    }


def build_command(
    settings: SidecarSettings,
    *,
    job_id: str,
    host_dir: str,
    plan: Mapping[str, Any],
    secret_names: tuple[str, ...] = (),
    user: str = "",
) -> list[str]:
    """Return the full ``docker run`` argv (pure; unit-tested)."""
    if not settings.image:
        raise SidecarError("pyvideotrans image is not configured (PYVIDEOTRANS_IMAGE)")
    argv = [
        settings.docker_bin, "run", "--rm",
        "--name", container_name(job_id),
        "--cpus", settings.cpus,
        "--memory", settings.memory,
        "--security-opt", "no-new-privileges",
        "-v", f"{host_dir}:{CONTAINER_WORKDIR}",
    ]
    if user:
        argv += ["--user", user]
    if settings.models_volume:
        argv += ["-v", f"{settings.models_volume}:/app/models"]
    if settings.network:
        argv += ["--network", settings.network]
    for name in secret_names:
        argv += ["-e", name]  # value inherited from the child env, never in argv
    return [*argv, settings.image, *cli_args(CONTAINER_WORKDIR, plan)]


def cli_args(work_dir: str, plan: Mapping[str, Any]) -> list[str]:
    """The fixed ``vtv`` CLI arguments for a job dir as the engine sees it (pure)."""
    tts_type = catalog.TTS_ELEVENLABS if plan.get("voice_engine") == catalog.VOICE_ENGINE_ELEVENLABS else catalog.TTS_EDGE
    translate_type = (
        catalog.TRANSLATE_OPENAI_COMPATIBLE if plan.get("translation") == "relay" else catalog.TRANSLATE_GOOGLE
    )
    return [
        "--task", "vtv",
        "--name", f"{work_dir}/{INPUT_NAME}",
        "--output-dir", f"{work_dir}/{OUTPUT_DIRNAME}",
        "--source_language_code", str(plan["source_language"]),
        "--target_language_code", str(plan["target_language"]),
        "--recogn_type", str(catalog.RECOGN_FASTER_WHISPER),
        "--model_name", str(plan.get("whisper_model") or catalog.DEFAULT_WHISPER_MODEL),
        "--translate_type", str(translate_type),
        "--tts_type", str(tts_type),
        "--voice_role", str(plan["voice"]),
        "--voice_autorate",
        "--subtitle_type", str(catalog.SUBTITLE_SOFT),
        "--log-level", "INFO",
    ]


def _worker_user() -> str:
    """Run the container as the worker's uid:gid so it can clean the work dir."""
    try:
        return f"{os.getuid()}:{os.getgid()}"
    except AttributeError:  # pragma: no cover - non-POSIX
        return ""


@contextlib.contextmanager
def host_lock(path: str) -> Iterator[None]:
    """Non-blocking exclusive host lock; raises :class:`SidecarBusy` when held."""
    import fcntl

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")  # noqa: SIM115 - released in finally
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SidecarBusy("another dub is running on this host") from exc
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


def _run_process(argv: list[str], env: dict[str, str], timeout_s: int) -> subprocess.CompletedProcess:
    """Process seam (monkeypatched in tests)."""
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


def _force_remove(settings: SidecarSettings, job_id: str) -> None:
    try:
        subprocess.run(  # noqa: S603
            [settings.docker_bin, "rm", "-f", container_name(job_id)],
            capture_output=True, timeout=60, check=False,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort cleanup
        logger.warning(f"dub: could not remove container for {job_id}: {exc}")


@dataclass
class SidecarResult:
    video_path: str
    subtitle_paths: dict[str, str] = field(default_factory=dict)  # lang code -> path
    log_tail: str = ""


def _http_post(url: str, token: str, payload: dict[str, Any], timeout_s: int) -> tuple[int, dict[str, Any]]:
    """HTTP seam (monkeypatched in tests): POST JSON, return ``(status, body)``."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(  # noqa: S310 - internal runner URL from config
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read() or b"{}")
        except ValueError:
            body = {}
        return exc.code, body


# pyvideotrans failures the uploader can fix: (log marker, message shown on the job).
_KNOWN_ENGINE_FAILURES: tuple[tuple[str, str], ...] = (
    (
        "No human voice detected",
        "We couldn't hear anyone speaking in this video, so there was nothing to dub. "
        "Upload a clip where someone talks clearly. Your credit was refunded.",
    ),
)


def engine_failure_message(code: int, tail: str) -> str:
    """The job error for a non-zero engine exit: a plain fix when we know it."""
    for marker, message in _KNOWN_ENGINE_FAILURES:
        if marker in (tail or ""):
            return message
    return f"dub engine failed (exit {code})"


def _run_http(
    settings: SidecarSettings,
    *,
    job_id: str,
    work_dir: str,
    plan: Mapping[str, Any],
    secrets: Mapping[str, str],
) -> str:
    """Run the CLI through the sidecar runner service; return the log tail."""
    if not settings.token:
        raise SidecarError("dub runner token is not configured (DUB_SIDECAR_TOKEN)")
    payload = {"args": cli_args(work_dir, plan), "env": dict(secrets), "timeout_s": settings.timeout_s}
    logger.info(f"dub: running pyvideotrans via runner for job={job_id!r} url={settings.url}")
    try:
        status, body = _http_post(f"{settings.url}/run", settings.token, payload, settings.timeout_s + 60)
    except OSError as exc:
        raise SidecarError(f"dub runner is unreachable: {exc.__class__.__name__}") from exc
    tail = str(body.get("log_tail") or "")[-2000:]
    if status == 409:
        raise SidecarBusy("the dub runner is busy")
    if status == 504:
        raise SidecarError(f"dub timed out after {settings.timeout_s}s")
    if status != 200:
        raise SidecarError(f"dub runner refused the job ({status}: {body.get('error') or 'error'})")
    code = int(body.get("returncode", -1))
    if code != 0:
        logger.error(f"dub: runner exit {code} for job={job_id!r}: {tail}")
        raise SidecarError(engine_failure_message(code, tail))
    return tail


def collect_outputs(out_dir: str, plan: Mapping[str, Any]) -> SidecarResult:
    """Find the dubbed mp4 + srt files pyvideotrans wrote to ``out_dir``.

    pyvideotrans v4.13 writes ``<target_dir>/<noextname>.mp4`` plus
    ``<source>.srt`` and ``<target>.srt`` (``task/trans_create.py``).
    """
    root = Path(out_dir)
    if not root.is_dir():
        raise SidecarError("sidecar produced no output directory")
    videos = sorted(
        (p for p in root.rglob("*.mp4") if p.is_file() and p.stat().st_size > 0),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not videos:
        raise SidecarError("sidecar produced no dubbed video")
    subs: dict[str, str] = {}
    for code in (str(plan.get("target_language") or ""), str(plan.get("source_language") or "")):
        if not code:
            continue
        matches = [p for p in root.rglob(f"{code}.srt") if p.is_file() and p.stat().st_size > 0]
        if matches:
            subs[code] = str(matches[0])
    return SidecarResult(video_path=str(videos[0]), subtitle_paths=subs)


def run_dub(
    *,
    job_id: str,
    work_dir: str,
    plan: Mapping[str, Any],
    settings: SidecarSettings | None = None,
) -> SidecarResult:
    """Run the container on ``work_dir/input.mp4``; return the collected outputs.

    Caller must hold :func:`host_lock`. Raises :class:`SidecarError` on a
    non-zero exit, a timeout (the container is force-removed) or empty output.
    """
    settings = settings or settings_from_config()
    relay = relay_target() if plan.get("translation") == "relay" else None
    # Relay removed since the job was created: fall back to the free path
    # instead of handing the CLI an OpenAI-compatible engine with no endpoint.
    plan = {**plan, "translation": "relay" if relay else "google"}
    secrets = secret_env(plan, relay)
    # Only forward names that actually have a value.
    secrets = {k: v for k, v in secrets.items() if v}
    if settings.url:
        tail = _run_http(settings, job_id=job_id, work_dir=work_dir, plan=plan, secrets=secrets)
        result = collect_outputs(os.path.join(work_dir, OUTPUT_DIRNAME), plan)
        result.log_tail = tail
        return result
    argv = build_command(
        settings,
        job_id=job_id,
        host_dir=host_path_for(settings, work_dir),
        plan=plan,
        secret_names=tuple(sorted(secrets)),
        user=_worker_user(),
    )
    child_env = {**os.environ, **secrets}
    logger.info(f"dub: running pyvideotrans sidecar for job={job_id!r} image={settings.image}")
    try:
        proc = _run_process(argv, child_env, settings.timeout_s)
    except subprocess.TimeoutExpired as exc:
        _force_remove(settings, job_id)
        raise SidecarError(f"dub timed out after {settings.timeout_s}s") from exc
    except FileNotFoundError as exc:
        raise SidecarError("docker is not installed on this worker") from exc
    tail = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-2000:]
    if proc.returncode != 0:
        logger.error(f"dub: sidecar exit {proc.returncode} for job={job_id!r}: {tail}")
        raise SidecarError(engine_failure_message(proc.returncode, tail))
    result = collect_outputs(os.path.join(work_dir, OUTPUT_DIRNAME), plan)
    result.log_tail = tail
    return result


__all__ = [
    "SidecarBusy",
    "SidecarError",
    "engine_failure_message",
    "SidecarResult",
    "SidecarSettings",
    "build_command",
    "cli_args",
    "collect_outputs",
    "container_name",
    "host_lock",
    "host_path_for",
    "relay_target",
    "run_dub",
    "secret_env",
    "settings_from_config",
]
