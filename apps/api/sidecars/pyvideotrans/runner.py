"""Long-lived HTTP runner for the pyvideotrans sidecar (stdlib only).

Why: the default sidecar mode is a one-shot ``docker run`` from the Celery
worker, which needs the docker socket inside the worker. On a shared box that
socket is root on the host, and the worker handles untrusted media. This runner
lets the sidecar run as its own compose service instead: the worker POSTs the
fixed ``vtv`` CLI arguments, the runner executes the same entrypoint
(``menivor-pvt-entrypoint`` -> ``cli.py``) on a shared work dir, and returns the
exit code and a log tail. The worker never touches docker.

Licence boundary is unchanged: Menivor exchanges files and a JSON request with
a separate program; nothing here imports pyvideotrans.

    GET  /healthz   {"ok": true, "busy": false}
    POST /run       Authorization: Bearer $DUB_RUNNER_TOKEN
                    {"args": ["--task", "vtv", ...], "env": {"PVT_LLM_KEY": "..."}, "timeout_s": 3600}
                    200 {"returncode": 0, "log_tail": "..."}
                    409 busy, 504 timeout, 400 bad request, 401 bad token

Env: DUB_RUNNER_TOKEN (required), DUB_RUNNER_WORK_ROOT (default /srv/menivor/dub),
DUB_RUNNER_PORT (8090), DUB_RUNNER_MAX_TIMEOUT_S (3600), DUB_RUNNER_ENTRYPOINT.
"""

from __future__ import annotations

import hmac
import json
import os
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED_ENV = frozenset({"PVT_ELEVENLABS_KEY", "PVT_LLM_API", "PVT_LLM_KEY", "PVT_LLM_MODEL"})
PATH_FLAGS = ("--name", "--output-dir")
MAX_BODY = 64 * 1024
MAX_ARGS = 64
MAX_ARG_LEN = 512
LOG_TAIL = 4000
DEFAULT_WORK_ROOT = "/srv/menivor/dub"
DEFAULT_ENTRYPOINT = "/usr/local/bin/menivor-pvt-entrypoint"


class BadRequest(ValueError):
    """The request is malformed or points outside the work root."""


def _inside(path: str, root: str) -> bool:
    real_root = os.path.realpath(root)
    real = os.path.realpath(path)
    return real == real_root or real.startswith(real_root + os.sep)


def validate_request(body: object, work_root: str, max_timeout_s: int) -> tuple[list[str], dict[str, str], int]:
    """Return ``(args, env, timeout_s)`` for a valid run request, else raise :class:`BadRequest`."""
    if not isinstance(body, dict):
        raise BadRequest("body must be a JSON object")
    args = body.get("args")
    if not isinstance(args, list) or not args or len(args) > MAX_ARGS:
        raise BadRequest("args must be a non-empty list")
    if not all(isinstance(a, str) and 0 < len(a) <= MAX_ARG_LEN for a in args):
        raise BadRequest("every arg must be a short non-empty string")
    if args[:2] != ["--task", "vtv"]:
        raise BadRequest("only --task vtv is allowed")
    for flag in PATH_FLAGS:
        if flag not in args:
            raise BadRequest(f"{flag} is required")
        idx = args.index(flag)
        if idx + 1 >= len(args) or not _inside(args[idx + 1], work_root):
            raise BadRequest(f"{flag} must be inside the work root")
    env = body.get("env") or {}
    if not isinstance(env, dict) or not set(env) <= ALLOWED_ENV:
        raise BadRequest("env may only carry the PVT_* secrets")
    if not all(isinstance(v, str) for v in env.values()):
        raise BadRequest("env values must be strings")
    try:
        timeout_s = int(body.get("timeout_s") or max_timeout_s)
    except (TypeError, ValueError) as exc:
        raise BadRequest("timeout_s must be an integer") from exc
    return list(args), dict(env), max(60, min(timeout_s, max_timeout_s))


def _chown_tree(path: str) -> None:
    """Give outputs back to the owner of the job dir so the worker can delete them."""
    if not hasattr(os, "geteuid") or os.geteuid() != 0 or not os.path.isdir(path):
        return
    st = os.stat(path)
    for dirpath, dirnames, filenames in os.walk(path):
        for name in [*dirnames, *filenames]:
            try:
                os.lchown(os.path.join(dirpath, name), st.st_uid, st.st_gid)
            except OSError:
                pass


def run_cli(entrypoint: str, args: list[str], secrets: dict[str, str], timeout_s: int) -> dict:
    """Run the CLI in its own process group; kill the whole group on timeout."""
    env = {k: v for k, v in os.environ.items() if k not in ALLOWED_ENV and not k.startswith("DUB_RUNNER_")}
    env.update({k: v for k, v in secrets.items() if v})
    proc = subprocess.Popen(  # noqa: S603 - fixed entrypoint, validated args, no shell
        [entrypoint, *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        return {"timeout": True, "returncode": -9, "log_tail": (out or "")[-LOG_TAIL:]}
    return {"timeout": False, "returncode": proc.returncode, "log_tail": (out or "")[-LOG_TAIL:]}


class Runner:
    def __init__(self, token: str, work_root: str, max_timeout_s: int, entrypoint: str) -> None:
        if len(token) < 24:
            raise SystemExit("DUB_RUNNER_TOKEN must be set (24+ characters)")
        self.token = token
        self.work_root = work_root
        self.max_timeout_s = max_timeout_s
        self.entrypoint = entrypoint
        self.lock = threading.Lock()
        self.run_cli = run_cli

    def authorized(self, header: str | None) -> bool:
        presented = (header or "").removeprefix("Bearer ").strip()
        return hmac.compare_digest(presented.encode(), self.token.encode())

    def handle_run(self, body: object) -> tuple[int, dict]:
        try:
            args, env, timeout_s = validate_request(body, self.work_root, self.max_timeout_s)
        except BadRequest as exc:
            return 400, {"error": str(exc)}
        if not self.lock.acquire(blocking=False):
            return 409, {"error": "busy"}
        try:
            out = self.run_cli(self.entrypoint, args, env, timeout_s)
            _chown_tree(os.path.dirname(os.path.realpath(args[args.index("--output-dir") + 1])))
        finally:
            self.lock.release()
        if out.get("timeout"):
            return 504, {"error": "timeout", "log_tail": out.get("log_tail", "")}
        return 200, {"returncode": out["returncode"], "log_tail": out.get("log_tail", "")}


def make_handler(runner: Runner) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "menivor-dub-runner"

        def _send(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                self._send(200, {"ok": True, "busy": runner.lock.locked()})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/run":
                return self._send(404, {"error": "not found"})
            if not runner.authorized(self.headers.get("Authorization")):
                return self._send(401, {"error": "unauthorized"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._send(400, {"error": "body size"})
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                return self._send(400, {"error": "invalid json"})
            status, payload = runner.handle_run(body)
            self._send(status, payload)

        def log_message(self, fmt: str, *args: object) -> None:
            sys.stderr.write("dub-runner: " + (fmt % args) + "\n")

    return Handler


def main() -> None:
    runner = Runner(
        token=os.environ.get("DUB_RUNNER_TOKEN", ""),
        work_root=os.environ.get("DUB_RUNNER_WORK_ROOT", DEFAULT_WORK_ROOT),
        max_timeout_s=int(os.environ.get("DUB_RUNNER_MAX_TIMEOUT_S", "3600")),
        entrypoint=os.environ.get("DUB_RUNNER_ENTRYPOINT", DEFAULT_ENTRYPOINT),
    )
    port = int(os.environ.get("DUB_RUNNER_PORT", "8090"))
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(runner)).serve_forever()  # noqa: S104 - internal network only


if __name__ == "__main__":
    main()
