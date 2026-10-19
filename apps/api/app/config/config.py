import copy
import errno
import os
import shutil
import socket
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

import toml
from loguru import logger

from app import __version__

# Product configuration, storage, migrations and vendored engine roots remain
# repository-level resources.  The API package itself is now at apps/api/app.
root_dir = str(Path(__file__).resolve().parents[4])

# Load a repo-root ``.env`` for local (non-Compose) runs BEFORE any config value
# is read from the environment below (e.g. ``NEON_DATABASE_URL`` for Neon). Only
# variables absent from ``os.environ`` are applied, so Compose/explicit exports
# always win. Guarded so a missing/malformed file never blocks startup.
try:
    from app.core.env import load_local_dotenv

    load_local_dotenv(root_dir)
except Exception as _dotenv_exc:  # pragma: no cover - dotenv load is best-effort
    logger.debug(f"local dotenv load skipped: {_dotenv_exc}")

# ``REELFORGE_CONFIG_FILE`` points the process at an alternate config file. The
# test session uses it to load a throwaway copy of ``config.example.toml`` so a
# developer's local ``config.toml`` (pilot gates, real provider keys) can never
# change test outcomes. Unset in every deployed environment.
config_file = os.environ.get("REELFORGE_CONFIG_FILE") or f"{root_dir}/config.toml"
_CONTAINER_CGROUP_MARKERS = ("docker", "containerd", "kubepods", "libpod", "podman")
_DOCKER_HOST_GATEWAY_NAME = "host.docker.internal"
_config_save_lock = threading.RLock()
_pending_config_lock = threading.RLock()
_pending_config_updates = {}
_pending_config_save_requested = False
_pending_config_flush_scheduled = False
_MISSING = object()
_DELETE = object()


class _SynchronizedConfig(dict):
    """保持 dict 使用方式不变，同时让运行期配置写操作服从同一把锁。"""

    def __setitem__(self, key, value):
        # Streamlit 每次整页 rerun 都会把当前控件值重新写回配置。视频任务持有
        # runtime_config_lock 时，如果值没有变化，这次写入没有任何副作用，也
        # 不应让刷新后的页面卡在表单中途。真正改变配置的写入仍进入下方锁，
        # 因而不能在正在生成的视频中途切换 Provider、密钥或其它全局设置。
        current = super().get(key, _MISSING)
        if current is not _MISSING and current == value:
            return
        with _config_save_lock:
            super().__setitem__(key, value)

    def __delitem__(self, key):
        with _config_save_lock:
            super().__delitem__(key)

    def clear(self):
        if not self:
            return
        with _config_save_lock:
            super().clear()

    def pop(self, key, default=_MISSING):
        # ``pop(key, default)`` 在 key 不存在时同样不会改变配置。WebUI 使用
        # 这种写法表达“采用默认策略”，刷新时必须允许它直接完成。
        if key not in self:
            if default is _MISSING:
                raise KeyError(key)
            return default
        with _config_save_lock:
            if default is _MISSING:
                return super().pop(key)
            return super().pop(key, default)

    def setdefault(self, key, default=None):
        # 与 __setitem__ 相同，已存在 key 的 setdefault 是只读操作。提前返回
        # 可以让只读取默认配置的页面刷新不受长任务配置锁影响。
        current = super().get(key, _MISSING)
        if current is not _MISSING:
            return current
        with _config_save_lock:
            return super().setdefault(key, default)

    def update(self, *args, **kwargs):
        changes = dict(*args, **kwargs)
        if all(
            (current := dict.get(self, key, _MISSING)) is not _MISSING
            and current == value
            for key, value in changes.items()
        ):
            return
        with _config_save_lock:
            super().update(changes)


def _pending_update_key(config_section, key):
    """为进程内固定配置分区生成待更新键。"""
    return id(config_section), key


def update_config_nonblocking(config_section, key, value):
    """
    非阻塞更新 WebUI 的运行期配置。

    视频生成会持有 ``runtime_config_lock``，确保同一任务不会在执行中途切换
    Provider、密钥或语音配置。Streamlit 控件发生变化时不能等待这把长任务锁，
    否则浏览器会表现为页面冻结。锁空闲时立即更新；锁繁忙时只保留每个配置项
    的最新值，并在当前任务释放锁时统一应用。

    返回 True 表示值已经生效，False 表示已进入待更新队列。
    """
    # 所有更新都先进入同一队列，再尝试获取配置锁。这样多个页面同时修改同一
    # 配置项时，写入队列的先后顺序就是最终顺序，不会出现较早线程在获取锁后
    # 把较新线程已经排队的值误删掉。
    with _pending_config_lock:
        _pending_config_updates[_pending_update_key(config_section, key)] = (
            config_section,
            key,
            copy.deepcopy(value),
        )

    acquired = _config_save_lock.acquire(blocking=False)
    if not acquired:
        # 调用方通常会在本次 Streamlit rerun 末尾请求保存，但不能依赖这一步
        # 一定执行。例如页面中途异常或更新恰好发生在任务退出保存阶段时，仍需
        # 有后台刷新线程保证排队值最终生效。
        _schedule_deferred_config_flush()
        return False

    try:
        _apply_pending_config_updates_locked()
        return config_section.get(key, _MISSING) == value
    finally:
        _config_save_lock.release()


def delete_config_nonblocking(config_section, key):
    """
    非阻塞删除 WebUI 配置项。

    “使用默认值”需要真正移除配置项，而不是写入空字符串。视频任务占用配置
    锁时，删除意图会覆盖同一配置项之前排队的更新，并在任务结束后执行。
    """
    with _pending_config_lock:
        _pending_config_updates[_pending_update_key(config_section, key)] = (
            config_section,
            key,
            _DELETE,
        )

    acquired = _config_save_lock.acquire(blocking=False)
    if not acquired:
        _schedule_deferred_config_flush()
        return False

    try:
        _apply_pending_config_updates_locked()
        return key not in config_section
    finally:
        _config_save_lock.release()


def _apply_pending_config_updates_locked():
    """在持有配置写锁时应用 WebUI 暂存的最新配置值。"""
    with _pending_config_lock:
        updates = list(_pending_config_updates.values())
        _pending_config_updates.clear()
        # 应用配置时继续持有待更新锁。读取“当前值 + 待更新值”快照的线程由此
        # 只能看到应用前或应用后的完整状态，不会读到只更新了一半的配置集合。
        for config_section, key, value in updates:
            if value is _DELETE:
                config_section.pop(key, None)
            else:
                config_section[key] = value
    return bool(updates)


def snapshot_config_with_pending(config_section):
    """
    返回配置分区的有效快照，并合并尚未应用的 WebUI 更新。

    视频任务持锁期间不能改写全局配置，但用户仍可准备下一条内容。LLM 请求
    使用这个快照后，界面中刚选择的 Provider、模型和密钥会参与新请求，同时
    不会改变正在执行的视频任务。
    """
    with _pending_config_lock:
        snapshot = dict(config_section)
        section_id = id(config_section)
        for (pending_section_id, key), (_, _, value) in _pending_config_updates.items():
            if pending_section_id != section_id:
                continue
            if value is _DELETE:
                snapshot.pop(key, None)
            else:
                snapshot[key] = copy.deepcopy(value)
    return snapshot


def _flush_pending_config_locked(*, suppress_save_errors):
    """在持有配置写锁时应用并保存当前所有待处理配置。"""
    global _pending_config_save_requested

    updates_applied = _apply_pending_config_updates_locked()
    with _pending_config_lock:
        save_requested = _pending_config_save_requested
        _pending_config_save_requested = False

    if not updates_applied and not save_requested:
        return True

    try:
        save_config()
        return True
    except Exception as exc:
        # 内存中的配置已经成功应用，保存失败时只保留待保存标记。视频任务不应
        # 因配置文件暂时不可写而被改判失败；下一次页面交互会再次触发保存。
        with _pending_config_lock:
            _pending_config_save_requested = True
        if not suppress_save_errors:
            raise
        logger.exception(f"failed to save deferred runtime config: {exc}")
        return False


def _run_deferred_config_flush():
    """等待长任务释放配置锁，并可靠清空期间积累的配置更新。"""
    global _pending_config_flush_scheduled

    while True:
        with _config_save_lock:
            flush_succeeded = _flush_pending_config_locked(
                suppress_save_errors=True
            )

        with _pending_config_lock:
            has_pending_work = bool(
                _pending_config_updates or _pending_config_save_requested
            )
            if not flush_succeeded or not has_pending_work:
                _pending_config_flush_scheduled = False
                return


def _schedule_deferred_config_flush():
    """保证同一时间最多只有一个后台线程等待刷新配置。"""
    global _pending_config_flush_scheduled

    with _pending_config_lock:
        if _pending_config_flush_scheduled:
            return
        _pending_config_flush_scheduled = True

    threading.Thread(
        target=_run_deferred_config_flush,
        name="mpt-config-flush",
        daemon=True,
    ).start()


def try_save_config():
    """
    非阻塞保存 WebUI 配置，锁繁忙时交由当前长任务结束后保存。

    普通 API、CLI 和维护脚本仍可调用 ``save_config`` 获得原来的阻塞写入语义；
    只有 Streamlit rerun 使用本函数，避免页面为等待视频任务而长时间无响应。
    """
    global _pending_config_save_requested

    with _pending_config_lock:
        _pending_config_save_requested = True

    acquired = _config_save_lock.acquire(blocking=False)
    if not acquired:
        _schedule_deferred_config_flush()
        return False

    try:
        return _flush_pending_config_locked(suppress_save_errors=False)
    finally:
        _config_save_lock.release()


@contextmanager
def runtime_config_lock():
    """
    在一次依赖全局配置的完整操作期间阻止其它 WebUI 会话改写配置。

    当前项目默认绑定本地回环地址，配置仍然是单用户全局配置。这个轻量锁主要
    保护生成、试听等长操作，避免另一个标签页在操作中途切换 Provider 或密钥。
    """
    with _config_save_lock:
        # 如果上一个短操作释放锁时后台刷新线程尚未获得调度，新任务必须在读取
        # Provider、密钥等全局配置前先应用队列，不能继续使用旧配置执行整条流水线。
        _flush_pending_config_locked(suppress_save_errors=True)
        try:
            yield
        finally:
            _flush_pending_config_locked(suppress_save_errors=True)


@contextmanager
def try_runtime_config_lock():
    """
    尝试获取运行期配置锁，并立即返回是否成功。

    WebUI 试听属于用户主动触发的短操作，不应在后台视频任务持锁时等待数分钟。
    调用方可以在未获取锁时就近提示用户稍后重试；成功获取后仍能保证试听期间
    Provider、密钥和模型配置不会被其它会话修改。
    """
    acquired = _config_save_lock.acquire(blocking=False)
    try:
        if acquired:
            _flush_pending_config_locked(suppress_save_errors=True)
        yield acquired
    finally:
        if acquired:
            _flush_pending_config_locked(suppress_save_errors=True)
            _config_save_lock.release()


def is_running_in_container(
    dockerenv_path: str = "/.dockerenv",
    containerenv_path: str = "/run/.containerenv",
    cgroup_path: str = "/proc/1/cgroup",
) -> bool:
    """
    判断当前进程是否运行在容器内。

    这个判断主要用于 Ollama 默认地址选择：
    - 普通本机运行时，`localhost` 指向用户机器本身；
    - Docker 容器内，`localhost` 指向容器自己，访问宿主机 Ollama
      通常需要使用 `host.docker.internal`。

    不能只判断 `/proc/1/cgroup` 是否存在，因为普通 Linux 也会有这个文件。
    这里只在检测到明确的容器标记时返回 True，避免误伤非 Docker Linux 用户。
    参数保留为可注入路径，便于单元测试覆盖不同运行环境。
    """
    if os.path.isfile(dockerenv_path) or os.path.isfile(containerenv_path):
        return True

    try:
        with open(cgroup_path, mode="r", encoding="utf-8") as fp:
            cgroup_content = fp.read().lower()
    except OSError:
        return False

    return any(marker in cgroup_content for marker in _CONTAINER_CGROUP_MARKERS)


def _can_resolve_hostname(hostname: str) -> bool:
    try:
        socket.gethostbyname(hostname)
    except OSError:
        return False
    return True


def _decode_linux_route_gateway(hex_gateway: str) -> str:
    # /proc/net/route 里的 Gateway 是 16 进制小端序，例如 010011AC 表示
    # 172.17.0.1。这里单独解析，是为了在原生 Linux Docker 没有
    # host.docker.internal DNS 记录时，还能尝试访问容器默认网关上的宿主机。
    if len(hex_gateway) != 8:
        raise ValueError("invalid gateway length")

    octets = [
        str(int(hex_gateway[index : index + 2], 16)) for index in range(6, -1, -2)
    ]
    return ".".join(octets)


def get_container_default_gateway_ip(route_path: str = "/proc/net/route") -> str:
    """
    读取 Linux 容器里的默认网关 IP。

    Docker Desktop 通常提供 `host.docker.internal`，但原生 Linux Docker
    默认不一定提供这个 DNS 名称。默认网关通常可以作为访问宿主机服务的
    兜底地址；如果用户的 Ollama 只监听 127.0.0.1，则仍需要用户让
    Ollama 监听宿主机网卡或手动配置 `ollama_base_url`。
    """
    try:
        with open(route_path, mode="r", encoding="utf-8") as fp:
            route_lines = fp.readlines()
    except OSError:
        return ""

    for line in route_lines[1:]:
        fields = line.strip().split()
        if len(fields) < 3:
            continue

        destination = fields[1]
        gateway = fields[2]
        if destination != "00000000" or gateway == "00000000":
            continue

        try:
            return _decode_linux_route_gateway(gateway)
        except ValueError:
            logger.warning(f"invalid container gateway route entry: {line.strip()}")
            return ""

    return ""


def get_default_ollama_base_url() -> str:
    """
    返回 Ollama 的默认 OpenAI-compatible base_url。

    用户显式配置 `ollama_base_url` 时不会走这里；这里只处理“未配置时的
    最佳默认值”。容器内默认指向宿主机，普通本机运行默认指向 localhost。
    """
    if not is_running_in_container():
        return "http://localhost:11434/v1"

    if _can_resolve_hostname(_DOCKER_HOST_GATEWAY_NAME):
        return f"http://{_DOCKER_HOST_GATEWAY_NAME}:11434/v1"

    gateway_ip = get_container_default_gateway_ip()
    if gateway_ip:
        logger.info(
            "host.docker.internal is not resolvable, fallback to container "
            f"default gateway for Ollama: {gateway_ip}"
        )
        return f"http://{gateway_ip}:11434/v1"

    logger.warning(
        "failed to resolve host.docker.internal and container default gateway; "
        "fallback to host.docker.internal for Ollama"
    )
    return f"http://{_DOCKER_HOST_GATEWAY_NAME}:11434/v1"


def load_config():
    # fix: IsADirectoryError: [Errno 21] Is a directory: '/MoneyPrinterTurbo/config.toml'
    if os.path.isdir(config_file):
        shutil.rmtree(config_file)

    if not os.path.isfile(config_file):
        example_file = f"{root_dir}/config.example.toml"
        if os.path.isfile(example_file):
            shutil.copyfile(example_file, config_file)
            logger.info("copy config.example.toml to config.toml")

    logger.info(f"load config from file: {config_file}")

    try:
        _config_ = toml.load(config_file)
    except Exception as e:
        logger.warning(f"load config failed: {str(e)}, try to load as utf-8-sig")
        with open(config_file, mode="r", encoding="utf-8-sig") as fp:
            _cfg_content = fp.read()
            _config_ = toml.loads(_cfg_content)
    return _config_


def save_config():
    """
    原子保存运行时配置。

    Streamlit 的不同会话可能在相近时间触发配置保存。直接覆盖 config.toml 时，
    另一个线程可能读取到只写了一部分的 TOML 内容。这里使用进程内可重入锁串行化
    保存，并先写入同目录临时文件，再通过 os.replace 原子替换目标文件。

    Docker Desktop 单文件 bind mount 会把 config.toml 本身作为挂载点，
    Linux 内核不允许通过 rename/replace 替换挂载点，因此会返回 EBUSY。
    该场景下只能在锁内原地覆盖文件；其它异常仍然抛出，避免掩盖权限、磁盘
    或路径错误。

    这仍然保留项目现有的单用户全局配置语义，不额外引入复杂的多用户配置系统；
    主要用于避免多标签页或快速 rerun 时损坏配置文件。
    """
    with _config_save_lock:
        config_to_save = dict(_cfg)
        config_to_save["app"] = dict(app)
        config_to_save["azure"] = dict(azure)
        config_to_save["siliconflow"] = dict(siliconflow)
        config_to_save["elevenlabs"] = dict(elevenlabs)
        config_to_save["chatterbox"] = dict(chatterbox)
        config_to_save["heygen"] = dict(heygen)
        config_to_save["anthropic"] = dict(anthropic)
        config_to_save["r2"] = dict(r2)
        config_to_save["neon"] = dict(neon)
        config_to_save["runpod"] = dict(runpod)
        config_to_save["comfyui"] = dict(comfyui)
        config_to_save["comfyui_local"] = dict(comfyui_local)
        config_to_save["rocketride"] = dict(rocketride)
        config_to_save["stripe"] = dict(stripe)
        config_to_save["iyzico"] = dict(iyzico)
        config_to_save["creem"] = dict(creem)
        config_to_save["polar"] = dict(polar)
        config_to_save["dodo"] = dict(dodo)
        config_to_save["paddle"] = dict(paddle)
        config_to_save["sentry"] = dict(sentry)
        config_to_save["rago"] = dict(rago)
        config_to_save["ui"] = dict(ui)
        serialized_config = toml.dumps(config_to_save)

        # WebUI 完整 rerun 结束时会调用保存。内容没有变化时直接返回，避免每次
        # 点击普通控件都产生一次磁盘写入和 fsync。
        try:
            with open(config_file, mode="r", encoding="utf-8") as f:
                if f.read() == serialized_config:
                    _cfg.clear()
                    _cfg.update(config_to_save)
                    return
        except (OSError, UnicodeError):
            pass

        temp_path = ""
        try:
            fd, temp_path = tempfile.mkstemp(
                prefix=".config-",
                suffix=".toml.tmp",
                dir=root_dir,
            )
            with os.fdopen(fd, mode="w", encoding="utf-8") as f:
                f.write(serialized_config)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.replace(temp_path, config_file)
            except OSError as exc:
                if exc.errno != errno.EBUSY:
                    raise

                logger.warning(
                    "atomic config replacement is unavailable for the mounted "
                    f"file, fallback to in-place write: {config_file}"
                )
                with open(config_file, mode="w", encoding="utf-8") as f:
                    f.write(serialized_config)
                    f.flush()
                    os.fsync(f.fileno())
            _cfg.clear()
            _cfg.update(config_to_save)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)


_cfg = load_config()
app = _SynchronizedConfig(_cfg.get("app", {}))
whisper = _cfg.get("whisper", {})
proxy = _cfg.get("proxy", {})
azure = _SynchronizedConfig(_cfg.get("azure", {}))
siliconflow = _SynchronizedConfig(_cfg.get("siliconflow", {}))
elevenlabs = _SynchronizedConfig(_cfg.get("elevenlabs", {}))
chatterbox = _SynchronizedConfig(_cfg.get("chatterbox", {}))
# ReelForge sections: HeyGen avatar provider, Anthropic (Claude via litellm),
# Cloudflare R2 object storage, and Neon/Postgres persistence.
heygen = _SynchronizedConfig(_cfg.get("heygen", {}))
anthropic = _SynchronizedConfig(_cfg.get("anthropic", {}))
r2 = _SynchronizedConfig(_cfg.get("r2", {}))
neon = _SynchronizedConfig(_cfg.get("neon", {}))
# RunPod Serverless powers the LatentSync talking-head tier (behind the same
# TalkingHeadProvider Protocol as HeyGen). Secrets come from config/env only.
runpod = _SynchronizedConfig(_cfg.get("runpod", {}))
# comfyui-deploy powers the AI B-roll studio (text/image -> motion clip), behind
# the BrollGenProvider Protocol. base_url + api_key + per-mode deployment ids;
# secrets come from config/env only, never hardcoded.
comfyui = _SynchronizedConfig(_cfg.get("comfyui", {}))
# Native/local ComfyUI (the $0-wallet local generation path) — kept SEPARATE from
# the [comfyui] comfyui-deploy remote section above so the two paths never
# collide. ``url`` is a LOCAL/LAN ComfyUI server (native /prompt + /history +
# /view API); ``backend_selector`` (WAN_CAMERA_BACKEND) chooses local vs remote
# for the wan_camera route. Secrets are not needed (no cloud credential).
comfyui_local = _SynchronizedConfig(_cfg.get("comfyui_local", {}))
# RocketRide runs one editor-authored .pipe against either an operator-configured
# local/on-prem URI or managed cloud URI. Public render specs select only the
# target name and never supply connection details or credentials.
rocketride = _SynchronizedConfig(_cfg.get("rocketride", {}))
# Backend-owned Pixelle powers the managed-API AI B-roll path (Kling/Seedance/Wan
# single-clip t2v/i2v) behind the BrollGenProvider Protocol. Credentials are
# consumed by the dedicated generation worker rather than an HTTP sidecar.
pixelle = _SynchronizedConfig(_cfg.get("pixelle", {}))
# Billing providers: Stripe (global) and iyzico (TR local cards). Secrets and
# plan price ids live here only; nothing is hardcoded in the billing services.
stripe = _SynchronizedConfig(_cfg.get("stripe", {}))
iyzico = _SynchronizedConfig(_cfg.get("iyzico", {}))
# Creem (creem.io) and Polar (polar.sh): merchant-of-record checkout platforms
# alongside Stripe/iyzico. Secrets and per-plan product/price ids live here only;
# nothing is hardcoded in the billing services.
creem = _SynchronizedConfig(_cfg.get("creem", {}))
polar = _SynchronizedConfig(_cfg.get("polar", {}))
# Dodo Payments (dodopayments.com) and Paddle Billing: merchant-of-record
# alternatives to Creem. Inactive unless MENIVOR_PAYMENTS_PROVIDER selects them.
dodo = _SynchronizedConfig(_cfg.get("dodo", {}))
paddle = _SynchronizedConfig(_cfg.get("paddle", {}))
# Clerk (web sign-in). Verification needs a JWKS source: the Frontend API
# ``issuer`` (``<issuer>/.well-known/jwks.json``), an explicit ``jwks_url``, or
# the Backend API JWKS authorized by ``secret_key`` (works even when the
# Frontend API domain is unreachable from the server). Env wins over config.toml.
clerk = _SynchronizedConfig(_cfg.get("clerk", {}))
for _clerk_key, _clerk_env in (
    ("issuer", "CLERK_ISSUER"),
    ("jwks_url", "CLERK_JWKS_URL"),
    ("audience", "CLERK_AUDIENCE"),
    ("secret_key", "CLERK_SECRET_KEY"),
):
    clerk[_clerk_key] = os.getenv(_clerk_env, clerk.get(_clerk_key, ""))
# RevenueCat is the native-app entitlement authority. Its secret REST API key is
# server-only and is used to verify protected export/share actions against the
# same backend user id supplied to the mobile SDK.
revenuecat = _SynchronizedConfig(_cfg.get("revenuecat", {}))
# Sentry error/performance monitoring (CTO locked decision). Fully optional:
# when [sentry].dsn is empty, app/telemetry/sentry.py runs as a NO-OP so no key
# is required to ship. Secrets/DSN come from config/env only, never hardcoded.
sentry = _SynchronizedConfig(_cfg.get("sentry", {}))
# Mint-settlement rail (ADR-0001/0002). When [mint].server_url is empty the
# ReelForge wallet uses the local microdollar ledger unchanged; when set (with
# api_key + treasury_account) job spend is held/captured/released on the live
# mint-server over HTTP. Secrets from env/config only, never hardcoded.
mint = _SynchronizedConfig(_cfg.get("mint", {}))
# Rago (Lago-compatible) usage-metering rail. ADDITIVE + env-gated: when
# [rago].url is empty the wallet does not meter to Rago at all; when set (with
# api_key) a settled job's measured media/LLM spend is reported as a usage event
# to POST /api/v1/events so the same spend is visible in Rago alongside the
# Mint/local money rail. A metering failure is logged and swallowed, never
# failing the job. Secrets from env/config only, never hardcoded.
rago = _SynchronizedConfig(_cfg.get("rago", {}))
ui = _SynchronizedConfig(
    _cfg.get(
        "ui",
        {
            "hide_log": False,
        },
    )
)

hostname = socket.gethostname()

log_level = _cfg.get("log_level", "DEBUG")
listen_host = _cfg.get("listen_host", "0.0.0.0")
listen_port = _cfg.get("listen_port", 8080)
project_name = _cfg.get("project_name", "Menivor")
project_description = _cfg.get(
    "project_description",
    "Menivor API: turn a product link into short vertical video ads.",
)
project_version = _cfg.get("project_version", __version__)
reload_debug = False

app["redis_host"] = os.getenv(
    "MPT_APP_REDIS_HOST",
    os.getenv("REDIS_HOST", app.get("redis_host", "localhost")),
)

# ReelForge [app] defaults. Use setdefault so an explicit config.toml/env value
# is never clobbered (the base MPT app may run a different LLM provider).
app.setdefault("llm_provider", "litellm")
app.setdefault("litellm_model_name", "anthropic/claude-sonnet-5")
# Env override for the script LLM (litellm ``<provider>/<model>`` id), e.g.
# ``groq/openai/gpt-oss-120b`` (free tier, key in GROQ_API_KEY) or
# ``anthropic/claude-sonnet-5`` (ANTHROPIC_API_KEY). When set it routes script
# generation through litellm regardless of the config.toml ``llm_provider``,
# so a deploy can pick its script model from env alone. Mirrored by the
# stdlib preflight (``app.core.launch_preflight.LLM_MODEL_ENV``).
if os.getenv("REELFORGE_LLM_MODEL", "").strip():
    app["llm_provider"] = "litellm"
    app["litellm_model_name"] = os.getenv("REELFORGE_LLM_MODEL", "").strip()

# Celery broker/backend default to the composed Redis URL from the existing
# [app] redis_* keys (§3.3: do NOT create a separate [redis] section).
_redis_auth = f":{app.get('redis_password', '')}@" if app.get("redis_password", "") else ""
_default_redis_url = (
    f"redis://{_redis_auth}{app.get('redis_host', 'localhost')}:"
    f"{app.get('redis_port', 6379)}/{app.get('redis_db', 0)}"
)
app.setdefault("celery_broker_url", _default_redis_url)
app.setdefault("celery_result_backend", _default_redis_url)
# Launch defaults intentionally fail closed.  A production credential being
# present must never activate a public surface without both an explicit mode and
# an approval switch owned by the release operator.
app["reelforge_launch_mode"] = os.getenv(
    "REELFORGE_LAUNCH_MODE", app.get("reelforge_launch_mode", "internal_pilot")
)
app["reelforge_public_launch_approved"] = os.getenv(
    "REELFORGE_PUBLIC_LAUNCH_APPROVED",
    str(app.get("reelforge_public_launch_approved", False)),
).lower() in {"1", "true", "yes", "on"}
app["reelforge_checkout_enabled"] = os.getenv(
    "REELFORGE_CHECKOUT_ENABLED", str(app.get("reelforge_checkout_enabled", False))
).lower() in {"1", "true", "yes", "on"}
app["reelforge_publishing_enabled"] = os.getenv(
    "REELFORGE_PUBLISHING_ENABLED", str(app.get("reelforge_publishing_enabled", False))
).lower() in {"1", "true", "yes", "on"}
app["reelforge_signup_enabled"] = os.getenv(
    "REELFORGE_SIGNUP_ENABLED", str(app.get("reelforge_signup_enabled", False))
).lower() in {"1", "true", "yes", "on"}

# Long->short clipping: social-platform (YouTube/TikTok/Vimeo/Twitch/X) link
# ingestion. Fail closed — a "paste a link" source is accepted only when this
# flag is explicitly enabled AND the optional ``yt_dlp`` dependency is installed
# (an absent dependency degrades to a clean 503). Env wins, then config.toml,
# then False. See app/domains/clipping/platform_source.py.
app["reelforge_clipping_platform_ingest_enabled"] = os.getenv(
    "REELFORGE_CLIPPING_PLATFORM_INGEST_ENABLED",
    str(app.get("reelforge_clipping_platform_ingest_enabled", False)),
).lower() in {"1", "true", "yes", "on"}
# Upper bound (seconds) on an ingested platform source's duration so an
# hours-long stream can never be pulled into a worker. 0/blank => 4h default.
app.setdefault("reelforge_clipping_max_source_duration_s", 14_400)
# Optional additional per-job USD spend cap for platform-ingest jobs (0 => rely
# on the standard wallet quote ceiling only). Enforced at request time.
app.setdefault("reelforge_clipping_platform_spend_cap_usd", 0)

# Route ElevenLabs TTS through the /with-timestamps adapter by default so
# karaoke captions and avatar-duration validation share one timing authority.
elevenlabs.setdefault("word_timestamps", True)

# Secret env overrides (mirror the redis_host precedence pattern above):
# environment wins, then config.toml value, then empty string.
anthropic["api_key"] = os.getenv("ANTHROPIC_API_KEY", anthropic.get("api_key", ""))
elevenlabs["api_key"] = os.getenv("ELEVENLABS_API_KEY", elevenlabs.get("api_key", ""))
heygen["api_key"] = os.getenv("HEYGEN_API_KEY", heygen.get("api_key", ""))
def _first_env(*names: str, default: str = "") -> str:
    """First env var that is set *and* non-empty, else ``default``.

    ``os.getenv(KEY, fallback)`` returns ``""`` when ``KEY`` is set but blank, so
    a deliberately-blank override (e.g. ``REELFORGE_R2_BUCKET_NAME=`` in a stacked
    ``.env``) would *shadow* a real ``R2_BUCKET_NAME`` and silently disable R2.
    Treating an empty string as "unset" makes the override chain fall through to
    the next candidate so real credentials are never masked by a stale blank.
    """
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip() != "":
            return value
    return default


r2.update(
    {
        "account_id": _first_env("R2_ACCOUNT_ID", default=r2.get("account_id", "")),
        "access_key_id": _first_env(
            "R2_ACCESS_KEY_ID", default=r2.get("access_key_id", "")
        ),
        "secret_access_key": _first_env(
            "R2_SECRET_ACCESS_KEY", default=r2.get("secret_access_key", "")
        ),
        "bucket": _first_env(
            "REELFORGE_R2_BUCKET_NAME",
            "R2_BUCKET_NAME",
            "R2_BUCKET",
            default=r2.get("bucket", ""),
        ),
        "endpoint_url": _first_env(
            "R2_S3_ENDPOINT", default=r2.get("endpoint_url", "")
        ),
        "public_base_url": _first_env(
            "R2_PUBLIC_BASE_URL", default=r2.get("public_base_url", "")
        ),
    }
)
_database_url = os.getenv(
    "REELFORGE_DATABASE_URL",
    os.getenv(
        "NEON_DATABASE_URL",
        os.getenv("DATABASE_URL", neon.get("database_url", "")),
    ),
)
if _database_url.startswith("postgres://"):
    _database_url = "postgresql+psycopg://" + _database_url[len("postgres://") :]
elif _database_url.startswith("postgresql://"):
    _database_url = "postgresql+psycopg://" + _database_url[len("postgresql://") :]
neon["database_url"] = _database_url

# RunPod (LatentSync tier) secrets: environment wins, then config.toml, then
# empty. timeout_s defaults to the provider's 30-minute hard cap when unset.
runpod["endpoint_id"] = os.getenv("RUNPOD_ENDPOINT_ID", runpod.get("endpoint_id", ""))
runpod["api_key"] = os.getenv("RUNPOD_API_KEY", runpod.get("api_key", ""))
runpod.setdefault("timeout_s", 1800)

# comfyui-deploy (AI B-roll studio) secrets + deployment ids: environment wins,
# then config.toml, then empty. ``base_url`` is the comfyui-deploy instance
# (hosted or self-hosted); ``deployment_id`` is the default text->video workflow,
# ``deployment_id_i2v`` the optional image->video one. timeout_s defaults to the
# provider's 30-minute hard cap when unset.
comfyui["base_url"] = os.getenv("COMFYUI_BASE_URL", comfyui.get("base_url", ""))
comfyui["api_key"] = os.getenv("COMFYUI_API_KEY", comfyui.get("api_key", ""))
comfyui["deployment_id"] = os.getenv(
    "COMFYUI_DEPLOYMENT_ID", comfyui.get("deployment_id", "")
)
comfyui["deployment_id_i2v"] = os.getenv(
    "COMFYUI_DEPLOYMENT_ID_I2V", comfyui.get("deployment_id_i2v", "")
)
comfyui["allowed_deployment_ids"] = os.getenv(
    "COMFYUI_ALLOWED_DEPLOYMENT_IDS", comfyui.get("allowed_deployment_ids", "")
)
comfyui.setdefault("timeout_s", 1800)

# Native/local ComfyUI overrides: environment wins, then config.toml, then
# default. ``url`` empty => local path disabled; ``backend_selector`` defaults to
# "remote" so the existing hosted wan_camera path is preserved unless a caller
# explicitly opts in with WAN_CAMERA_BACKEND=local.
comfyui_local["url"] = os.getenv("COMFYUI_LOCAL_URL", comfyui_local.get("url", ""))
comfyui_local["backend_selector"] = os.getenv(
    "WAN_CAMERA_BACKEND", comfyui_local.get("backend_selector", "remote")
)
comfyui_local.setdefault("timeout_s", 1800)
comfyui_local.setdefault("poll_interval_s", 3)

# RocketRide target and pipeline allowlist. URI/key/path values are server-only;
# render requests can select ``local`` or ``managed`` but cannot override them.
rocketride["local_uri"] = os.getenv(
    "ROCKETRIDE_LOCAL_URI", rocketride.get("local_uri", "")
)
rocketride["local_api_key"] = os.getenv(
    "ROCKETRIDE_LOCAL_API_KEY", rocketride.get("local_api_key", "")
)
rocketride["managed_uri"] = os.getenv(
    "ROCKETRIDE_MANAGED_URI", rocketride.get("managed_uri", "")
)
rocketride["managed_api_key"] = os.getenv(
    "ROCKETRIDE_MANAGED_API_KEY", rocketride.get("managed_api_key", "")
)
rocketride["pipeline_root"] = os.getenv(
    "ROCKETRIDE_PIPELINE_ROOT", rocketride.get("pipeline_root", "pipelines/rocketride")
)
rocketride["pipeline_file"] = os.getenv(
    "ROCKETRIDE_PIPELINE_FILE", rocketride.get("pipeline_file", "")
)
rocketride.setdefault("ttl_seconds", 3600)
rocketride.setdefault("connect_timeout_seconds", 60)
rocketride.setdefault("pipeline_trace_level", "")

# Pixelle is backend-owned. VideoClient executes directly in the generation
# worker; ``base_url`` is retained only for an explicitly configured legacy
# migration adapter and is never required by the in-process provider.
pixelle["base_url"] = os.getenv("PIXELLE_LEGACY_BASE_URL", pixelle.get("base_url", ""))
pixelle["enabled"] = os.getenv("PIXELLE_ENABLED", str(pixelle.get("enabled", True))).lower() in {"1", "true", "yes"}
pixelle["model"] = os.getenv("PIXELLE_MODEL", pixelle.get("model", "kling-v3"))
pixelle["allowed_models"] = os.getenv(
    "PIXELLE_ALLOWED_MODELS", pixelle.get("allowed_models", "")
)
pixelle.setdefault("timeout_s", 600)

# Billing secrets + plan price ids. Environment wins, then config.toml, then
# empty string — never hardcode a secret in source. Stripe plan price ids map to
# the per-plan keys read by app/services/billing/plans.py (``<key>_price_id``).
stripe["secret_key"] = os.getenv("STRIPE_SECRET_KEY", stripe.get("secret_key", ""))
stripe["webhook_secret"] = os.getenv(
    "STRIPE_WEBHOOK_SECRET", stripe.get("webhook_secret", "")
)
stripe["starter_price_id"] = os.getenv(
    "STRIPE_PRICE_STARTER", stripe.get("starter_price_id", "")
)
stripe["pro_price_id"] = os.getenv("STRIPE_PRICE_PRO", stripe.get("pro_price_id", ""))
iyzico["api_key"] = os.getenv("IYZICO_API_KEY", iyzico.get("api_key", ""))
iyzico["secret_key"] = os.getenv("IYZICO_SECRET_KEY", iyzico.get("secret_key", ""))
iyzico["base_url"] = os.getenv("IYZICO_BASE_URL", iyzico.get("base_url", ""))

# Creem (creem.io): merchant-of-record checkout. api_key + webhook_secret from
# env (env wins, then config.toml, then empty). Per-plan product ids are read by
# app/services/billing/plans.py (``<key>_product_id``).
creem["api_key"] = os.getenv("CREEM_API_KEY", creem.get("api_key", ""))
creem["webhook_secret"] = os.getenv(
    "CREEM_WEBHOOK_SECRET", creem.get("webhook_secret", "")
)
# One-time credit-pack product ids (product ids are not secret). Read by
# app/services/billing/plans.py as ``<pack>_product_id``.
for _pack_key in ("starter", "pro"):
    creem[f"{_pack_key}_product_id"] = os.getenv(
        f"CREEM_PRODUCT_ID_{_pack_key.upper()}",
        creem.get(f"{_pack_key}_product_id", ""),
    )
# Where Creem sends the buyer after paying. Creem appends signed params
# (checkout_id, order_id, product_id, request_id, signature) that the web page
# forwards to POST /billing/creem/confirm, so credits land without a webhook.
creem["success_url"] = os.getenv(
    "CREEM_SUCCESS_URL",
    creem.get("success_url", "") or "https://menivor.com/billing?checkout=return",
)
# The $1 card check that unlocks the free signup reels on the web (credited 1:1
# as reel credit). Not a secret; created by tools/ops/create_creem_products.py.
creem["card_check_product_id"] = os.getenv(
    "CREEM_PRODUCT_ID_CARD_CHECK", creem.get("card_check_product_id", "")
)
# Public web origin used to build per-checkout return URLs (never derived from
# the incoming request, which sits behind a proxy).
creem["web_base_url"] = os.getenv(
    "MENIVOR_WEB_URL", creem.get("web_base_url", "") or "https://menivor.com"
)

# Polar (polar.sh): merchant-of-record checkout. access_token + webhook_secret
# from env (env wins, then config.toml, then empty). Per-plan price ids are read
# by app/services/billing/plans.py (``<key>_price_id``).
polar["access_token"] = os.getenv(
    "POLAR_ACCESS_TOKEN", polar.get("access_token", "")
)
polar["webhook_secret"] = os.getenv(
    "POLAR_WEBHOOK_SECRET", polar.get("webhook_secret", "")
)

# Recurring WORKSPACE plan ids (read by app/services/billing/workspace_plans.py).
# Kept separate from the one-time pack ids above: a recurring price cannot be sold
# as a one-time pack and vice versa. One id per plan per interval, e.g.
# STRIPE_PRICE_TEAM_STARTER_MONTH / CREEM_PRODUCT_TEAM_PRO_YEAR /
# POLAR_PRODUCT_TEAM_STARTER_YEAR.
for _team_plan in ("starter", "pro"):
    for _team_interval in ("month", "year"):
        _suffix = f"TEAM_{_team_plan.upper()}_{_team_interval.upper()}"
        _stripe_key = f"team_{_team_plan}_{_team_interval}_price_id"
        stripe[_stripe_key] = os.getenv(
            f"STRIPE_PRICE_{_suffix}", stripe.get(_stripe_key, "")
        )
        _product_key = f"team_{_team_plan}_{_team_interval}_product_id"
        creem[_product_key] = os.getenv(
            f"CREEM_PRODUCT_{_suffix}", creem.get(_product_key, "")
        )
        polar[_product_key] = os.getenv(
            f"POLAR_PRODUCT_{_suffix}", polar.get(_product_key, "")
        )
creem["base_url"] = os.getenv("CREEM_API_BASE_URL", creem.get("base_url", ""))

# Dodo Payments (merchant of record). Secrets from env only; product ids are not
# secret (created by tools/ops/create_dodo_products.py). DODO_ENVIRONMENT picks
# test_mode (https://test.dodopayments.com) or live_mode (https://live...).
dodo["api_key"] = os.getenv("DODO_API_KEY", dodo.get("api_key", ""))
dodo["webhook_secret"] = os.getenv("DODO_WEBHOOK_SECRET", dodo.get("webhook_secret", ""))
dodo["environment"] = os.getenv("DODO_ENVIRONMENT", dodo.get("environment", "live_mode"))
dodo["base_url"] = os.getenv("DODO_API_BASE_URL", dodo.get("base_url", ""))
# The Menivor brand on a shared Dodo business: webhooks for other brands are ignored.
dodo["brand_id"] = os.getenv("DODO_BRAND_ID", dodo.get("brand_id", ""))
# Premium voice / AI-video credit packs (separate SKUs from reel credits).
for _dodo_key in ("card_check", "starter", "pro", "premium_voice_25", "ai_video_2000"):
    dodo[f"{_dodo_key}_product_id"] = os.getenv(
        f"DODO_PRODUCT_ID_{_dodo_key.upper()}", dodo.get(f"{_dodo_key}_product_id", "")
    )
for _dodo_plan in ("creator", "pro", "agency"):
    for _dodo_interval in ("month", "year"):
        _dodo_plan_key = f"plan_{_dodo_plan}_{_dodo_interval}_product_id"
        dodo[_dodo_plan_key] = os.getenv(
            f"DODO_PRODUCT_ID_PLAN_{_dodo_plan.upper()}_{_dodo_interval.upper()}",
            dodo.get(_dodo_plan_key, ""),
        )

# Paddle Billing (merchant of record). Scaffold: packs + card check via
# transactions; price ids (pri_...) are not secret.
paddle["api_key"] = os.getenv("PADDLE_API_KEY", paddle.get("api_key", ""))
paddle["webhook_secret"] = os.getenv("PADDLE_WEBHOOK_SECRET", paddle.get("webhook_secret", ""))
paddle["environment"] = os.getenv("PADDLE_ENVIRONMENT", paddle.get("environment", "production"))
paddle["base_url"] = os.getenv("PADDLE_API_BASE_URL", paddle.get("base_url", ""))
for _paddle_key in ("card_check", "starter", "pro"):
    paddle[f"{_paddle_key}_price_id"] = os.getenv(
        f"PADDLE_PRICE_ID_{_paddle_key.upper()}", paddle.get(f"{_paddle_key}_price_id", "")
    )

# RevenueCat: the REST key is a SECRET server credential. Public iOS/Android SDK
# keys belong only in the Expo build and are intentionally not read here.
revenuecat["secret_api_key"] = os.getenv(
    "REVENUECAT_SECRET_API_KEY", revenuecat.get("secret_api_key", "")
)
revenuecat["entitlement_id"] = os.getenv(
    "REVENUECAT_PRO_ENTITLEMENT_ID",
    revenuecat.get("entitlement_id", "pro"),
)
revenuecat["api_base_url"] = os.getenv(
    "REVENUECAT_API_BASE_URL",
    revenuecat.get("api_base_url", "https://api.revenuecat.com/v1"),
)
try:
    revenuecat["timeout_seconds"] = float(
        os.getenv(
            "REVENUECAT_TIMEOUT_SECONDS",
            revenuecat.get("timeout_seconds", 5),
        )
        or 5
    )
except (TypeError, ValueError):
    revenuecat["timeout_seconds"] = 5.0

# Sentry: DSN + environment override from env (env wins, then config.toml, then
# empty). Empty dsn keeps monitoring disabled — no key needed to ship.
# traces_sample_rate defaults to 0.0 (errors only, no perf sampling) unless set.
sentry["dsn"] = os.getenv("SENTRY_DSN", sentry.get("dsn", ""))
sentry["environment"] = os.getenv(
    "SENTRY_ENVIRONMENT", sentry.get("environment", "")
)
sentry.setdefault("traces_sample_rate", 0.0)

# Mint-settlement: env wins, then config.toml, then default. Empty server_url
# keeps the rail disabled (local ledger). api_key -> x-api-key header;
# treasury_account -> capture `to`; timeout_seconds -> per-request HTTP timeout.
mint["server_url"] = os.getenv("MINT_SERVER_URL", mint.get("server_url", ""))
mint["api_key"] = os.getenv("MINT_API_KEY", mint.get("api_key", ""))
mint["attestation_public_keys_json"] = os.getenv(
    "MINT_ATTESTATION_PUBLIC_KEYS_JSON",
    mint.get("attestation_public_keys_json", ""),
)
mint["treasury_account"] = os.getenv(
    "MINT_TREASURY_ACCOUNT", mint.get("treasury_account", "")
)
try:
    mint["timeout_seconds"] = float(
        os.getenv("MINT_TIMEOUT_SECONDS", mint.get("timeout_seconds", 10)) or 10
    )
except (TypeError, ValueError):
    mint["timeout_seconds"] = 10.0
# Launch-flag stage machinery (see domains/wallet/mint_stage.py). `stage` flips
# the wallet local -> canary -> on without a code change; empty defaults to "on"
# when the rail is fully configured, else the wallet stays on the local ledger.
# `rollout_percent` (0-100) is the deterministic per-owner canary slice.
mint["stage"] = os.getenv("MINT_STAGE", mint.get("stage", ""))
try:
    mint["rollout_percent"] = int(
        os.getenv("MINT_ROLLOUT_PERCENT", mint.get("rollout_percent", 0)) or 0
    )
except (TypeError, ValueError):
    mint["rollout_percent"] = 0

# Rago usage metering: env wins, then config.toml, then default. Empty url keeps
# metering disabled (no-op). api_key -> Bearer token; metric_code ->
# billable_metric.code the settled spend is charged on; external_subscription_id
# -> optional fixed subscription (else the wallet owner key is used);
# timeout_seconds -> per-request HTTP timeout.
rago["url"] = os.getenv("RAGO_URL", rago.get("url", ""))
rago["api_key"] = os.getenv("RAGO_API_KEY", rago.get("api_key", ""))
rago["metric_code"] = os.getenv(
    "RAGO_METRIC_CODE", rago.get("metric_code", "reel_ai_credits")
)
rago["external_subscription_id"] = os.getenv(
    "RAGO_EXTERNAL_SUBSCRIPTION_ID", rago.get("external_subscription_id", "")
)
try:
    rago["timeout_seconds"] = float(
        os.getenv("RAGO_TIMEOUT_SECONDS", rago.get("timeout_seconds", 10)) or 10
    )
except (TypeError, ValueError):
    rago["timeout_seconds"] = 10.0

ffmpeg_path = app.get("ffmpeg_path", "")
if ffmpeg_path and os.path.isfile(ffmpeg_path):
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

logger.info(f"{project_name} v{project_version}")
