import glob
import os
import pathlib
from typing import Union

from fastapi import BackgroundTasks, Depends, Request, UploadFile
from fastapi.params import File
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

from app.config import config
from app.controllers import base
from app.controllers.manager.base_manager import TaskQueueFullError
from app.controllers.manager.memory_manager import InMemoryTaskManager
from app.controllers.manager.redis_manager import RedisTaskManager
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.models.schema import (
    AudioRequest,
    BgmRetrieveResponse,
    BgmUploadResponse,
    SubtitleRequest,
    TaskResponse,
    TaskVideoRequest,
    VideoMaterialUploadResponse,
    VideoMaterialRetrieveResponse
)
from app.services import bgm as bgm_service
from app.services import state as sm
from app.services import task as tm
from app.utils import file_security, utils

from app.domains.legacy.access import (
    USER_UPLOAD_DIR,
    owns_task,
    record_task_owner,
    require_caller,
    require_legacy_generation,
    user_upload_subdir,
)

# Every legacy route requires an authenticated caller (Clerk JWT or a personal /
# device API key). Handlers that need the id re-declare the same dependency;
# FastAPI caches it per request, so the principal is resolved once.
router = new_router(dependencies=[Depends(require_caller)])

_enable_redis = config.app.get("enable_redis", False)
_redis_host = config.app.get("redis_host", "localhost")
_redis_port = config.app.get("redis_port", 6379)
_redis_db = config.app.get("redis_db", 0)
_redis_password = config.app.get("redis_password", None)
_max_concurrent_tasks = config.app.get("max_concurrent_tasks", 5)
_max_queued_tasks = config.app.get("max_queued_tasks", 100)

redis_url = f"redis://:{_redis_password}@{_redis_host}:{_redis_port}/{_redis_db}"
# 根据配置选择合适的任务管理器
if _enable_redis:
    task_manager = RedisTaskManager(
        max_concurrent_tasks=_max_concurrent_tasks,
        redis_url=redis_url,
        max_queued_tasks=_max_queued_tasks,
    )
else:
    task_manager = InMemoryTaskManager(
        max_concurrent_tasks=_max_concurrent_tasks,
        max_queued_tasks=_max_queued_tasks,
    )


def _sanitize_upload_filename(filename: str, request_id: str) -> str:
    # 浏览器或客户端有时会附带目录信息，甚至可能夹带 ../ 这类穿越片段。
    # 这里只保留纯文件名，避免上传接口把文件写到目标目录之外。
    normalized_name = (filename or "").replace("\\", "/").split("/")[-1].strip()
    if not normalized_name or normalized_name in {".", ".."}:
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: invalid filename",
        )
    return normalized_name


def _resolve_path_within_directory(base_dir: str, unsafe_path: str, request_id: str) -> str:
    try:
        return file_security.resolve_path_within_directory(base_dir, unsafe_path)
    except ValueError as exc:
        logger.warning(
            f"reject unsafe file path, request_id: {request_id}, path: {unsafe_path}, "
            f"error: {str(exc)}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=404 if str(exc) == "file does not exist" else 403,
            message=f"{request_id}: invalid file path",
        )


def _public_task_data(task: dict) -> dict:
    """复制任务状态并移除仅用于服务端进程协调的内部字段。"""
    public_task = dict(task)
    public_task.pop("cross_post_owner", None)
    return public_task


def _task_file_to_uri(file: str, endpoint: str, task_dir: str, request_id: str) -> str:
    if not isinstance(file, str):
        return file

    if file.startswith(("http://", "https://")):
        return file

    try:
        resolved_path = file_security.resolve_path_within_directory(task_dir, file)
    except ValueError as exc:
        # 任务状态理论上只应保存任务目录内的产物路径。这里不再继续拼接 URL，
        # 避免把异常路径包装成可访问链接；同时保留原值，便于排查历史脏数据。
        logger.warning(
            f"skip unsafe task output path, request_id: {request_id}, path: {file}, "
            f"error: {str(exc)}"
        )
        return file

    relative_path = os.path.relpath(resolved_path, task_dir).replace("\\", "/")
    uri_path = f"tasks/{relative_path}"
    if endpoint:
        return f"{endpoint.rstrip('/')}/{uri_path}"
    return f"/{uri_path}"


def _parse_byte_range(
    range_header: str | None, file_size: int, request_id: str
) -> tuple[int, int]:
    """解析单段 HTTP Range，并把无效或越界请求稳定转换成 416。"""
    if file_size <= 0:
        raise HttpException(
            task_id=request_id,
            status_code=416,
            message=f"{request_id}: requested range is not satisfiable",
        )

    if not range_header:
        return 0, file_size - 1

    try:
        # 视频播放器这里只需要单段 bytes range。拒绝多段请求可以避免返回体
        # 与 Content-Range 不一致，也避免异常字符串落入 int() 产生 500。
        if not range_header.startswith("bytes=") or "," in range_header:
            raise ValueError("unsupported range format")
        start_text, end_text = range_header[6:].split("-", 1)
        if not start_text and not end_text:
            raise ValueError("empty range")

        if not start_text:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError("invalid suffix length")
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
            if start < 0 or start >= file_size or end < start:
                raise ValueError("range outside file")
            end = min(end, file_size - 1)
    except (TypeError, ValueError) as exc:
        logger.warning(
            f"reject invalid video range, request_id: {request_id}, "
            f"range: {range_header}, file_size: {file_size}, error: {str(exc)}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=416,
            message=f"{request_id}: requested range is not satisfiable",
        ) from exc

    return start, end


_MATERIAL_SUFFIXES = ("mp4", "mov", "avi", "flv", "mkv", "jpg", "jpeg", "png")


def _normalized_rel(path: str) -> str:
    return str(path or "").replace("\\", "/").lstrip("./").lstrip("/")


def _is_foreign_upload(path: str, user_id: str) -> bool:
    """Whether ``path`` points into another user's private upload namespace."""
    rel = _normalized_rel(path)
    if "/" + USER_UPLOAD_DIR + "/" in "/" + rel:
        own_prefix = user_upload_subdir(user_id) + "/"
        return not rel.startswith(own_prefix)
    return False


def _scope_material_paths(body, user_id: str, request_id: str) -> None:
    """Reject task inputs that reference another user's private uploads."""
    paths: list[str] = []
    bgm_file = getattr(body, "bgm_file", "") or ""
    if bgm_file:
        paths.append(str(bgm_file))
    for material in getattr(body, "video_materials", None) or []:
        url = getattr(material, "url", "") or ""
        if url and not str(url).startswith(("http://", "https://")):
            paths.append(str(url))
    for path in paths:
        if os.path.isabs(path) or _is_foreign_upload(path, user_id):
            raise HttpException(
                task_id=request_id,
                status_code=403,
                message=f"{request_id}: material path is not accessible",
            )


def _require_task_file_owner(file_path: str, user_id: str, request_id: str) -> None:
    """``/stream`` and ``/download`` paths are ``<task_id>/<file>``: owner only."""
    task_id = _normalized_rel(file_path).split("/", 1)[0]
    if not task_id or not owns_task(task_id, user_id):
        # 404 rather than 403 so foreign task ids are not confirmed to exist.
        raise HttpException(
            task_id=request_id,
            status_code=404,
            message=f"{request_id}: file not found",
        )


@router.post("/videos", response_model=TaskResponse, summary="Generate a short video")
def create_video(
    background_tasks: BackgroundTasks,
    request: Request,
    body: TaskVideoRequest,
    user_id: str = Depends(require_caller),
):
    return create_task(request, body, stop_at="video", user_id=user_id)


@router.post("/subtitle", response_model=TaskResponse, summary="Generate subtitle only")
def create_subtitle(
    background_tasks: BackgroundTasks,
    request: Request,
    body: SubtitleRequest,
    user_id: str = Depends(require_caller),
):
    return create_task(request, body, stop_at="subtitle", user_id=user_id)


@router.post("/audio", response_model=TaskResponse, summary="Generate audio only")
def create_audio(
    background_tasks: BackgroundTasks,
    request: Request,
    body: AudioRequest,
    user_id: str = Depends(require_caller),
):
    return create_task(request, body, stop_at="audio", user_id=user_id)


def create_task(
    request: Request,
    body: Union[TaskVideoRequest, SubtitleRequest, AudioRequest],
    stop_at: str,
    user_id: str,
):
    request_id = base.get_task_id(request)
    # Unmetered generation on the operator's provider keys: off unless enabled.
    require_legacy_generation(request_id)
    _scope_material_paths(body, user_id, request_id)
    task_id = utils.get_uuid()
    try:
        task = {
            "task_id": task_id,
            "request_id": request_id,
            "params": body.model_dump(),
        }
        record_task_owner(task_id, user_id)
        sm.state.update_task(task_id)
        task_manager.add_task(tm.start, task_id=task_id, params=body, stop_at=stop_at)
        logger.success(f"Task created: {utils.to_json(task)}")
        return utils.get_response(200, task)
    except TaskQueueFullError as e:
        sm.state.delete_task(task_id)
        logger.warning(
            f"reject task because queue is full, request_id: {request_id}, task_id: {task_id}"
        )
        raise HttpException(
            task_id=task_id, status_code=429, message=f"{request_id}: {str(e)}"
        )
    except ValueError as e:
        raise HttpException(
            task_id=task_id, status_code=400, message=f"{request_id}: {str(e)}"
        )

# ``/tasks`` (list / detail / cancel) is served by the caller-scoped task queue
# in :mod:`app.domains.legacy.task_queue`, which merges product jobs with the
# caller's own legacy tasks.


@router.get(
    "/musics", response_model=BgmRetrieveResponse, summary="Retrieve local BGM files"
)
def get_bgm_list(request: Request, user_id: str = Depends(require_caller)):
    bgm_list = []
    for file in bgm_service.list_bgm_files():
        filename = os.path.basename(file)
        bgm_list.append(
            {
                "name": filename,
                "size": os.path.getsize(file),
                # 只返回文件名，避免把服务器绝对路径暴露给调用方。服务端会
                # 在 storage/bgm 和 resource/songs 两个白名单目录中重新解析。
                "file": filename,
            }
        )
    # The caller's own private uploads (never other users').
    own_rel = user_upload_subdir(user_id)
    own_dir = os.path.join(bgm_service.uploaded_bgm_dir(create=True), own_rel)
    if os.path.isdir(own_dir):
        for name in sorted(os.listdir(own_dir), key=str.lower):
            if name.startswith("."):
                continue
            if pathlib.Path(name).suffix.lower() not in bgm_service.SUPPORTED_BGM_EXTENSIONS:
                continue
            full = os.path.join(own_dir, name)
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            bgm_list.append(
                {"name": name, "size": os.path.getsize(full), "file": f"{own_rel}/{name}"}
            )
    response = {"files": bgm_list}
    return utils.get_response(200, response)


@router.post(
    "/musics",
    response_model=BgmUploadResponse,
    summary="Upload a background music file",
    description=(
        "Validate an MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, or WMA file up to "
        "30 MB and store it under an immutable UUID filename in storage/bgm."
    ),
    responses={
        400: {"description": "The filename, format, size, or audio stream is invalid"},
        500: {"description": "FFmpeg validation or persistent storage is unavailable"},
    },
)
def upload_bgm_file(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(require_caller),
):
    request_id = base.get_task_id(request)
    try:
        stored_name = bgm_service.save_bgm_upload(file.filename, file.file)
        # Move the validated upload into the caller's private namespace so it is
        # listed only for them (and task inputs can be owner-checked).
        own_rel = user_upload_subdir(user_id)
        upload_root = bgm_service.uploaded_bgm_dir(create=True)
        own_dir = os.path.join(upload_root, own_rel)
        os.makedirs(own_dir, exist_ok=True)
        os.replace(
            os.path.join(upload_root, stored_name), os.path.join(own_dir, stored_name)
        )
        safe_filename = f"{own_rel}/{stored_name}"
    except bgm_service.BgmUploadError as exc:
        # 上传失败通常可以由用户更换文件后恢复，因此记录 request_id 和明确原因，
        # 但不输出文件内容或绝对路径，避免日志泄露用户数据。
        logger.warning(
            f"background music upload rejected: request_id={request_id}, error={str(exc)}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=400,
            message=f"{request_id}: {str(exc)}",
        )
    except (bgm_service.BgmServiceError, OSError) as exc:
        # 工具链或存储故障属于服务端问题，不能伪装成用户文件错误。日志保留
        # request_id 和内部原因，HTTP 响应只返回稳定文案，避免暴露服务器路径。
        logger.error(
            f"background music upload failed: request_id={request_id}, error={str(exc)}"
        )
        raise HttpException(
            task_id=request_id,
            status_code=500,
            message=f"{request_id}: background music validation is unavailable",
        )

    response = {"file": safe_filename}
    return utils.get_response(200, response)

@router.get(
    "/video_materials", response_model=VideoMaterialRetrieveResponse, summary="Retrieve local video materials"
)
def get_video_materials_list(request: Request, user_id: str = Depends(require_caller)):
    local_videos_dir = utils.storage_dir("local_videos", create=True)
    own_rel = user_upload_subdir(user_id)
    own_dir = os.path.join(local_videos_dir, own_rel)
    files = []
    # Operator-provided stock at the library root plus the caller's own uploads.
    for directory in (local_videos_dir, own_dir):
        if not os.path.isdir(directory):
            continue
        for suffix in _MATERIAL_SUFFIXES:
            files.extend(glob.glob(os.path.join(directory, f"*.{suffix}")))
    # 文件系统枚举顺序不稳定，直接返回会导致“顺序拼接”在不同机器或不同
    # 时刻表现不一致。这里统一按文件名排序，至少保证服务端返回顺序可预测。
    files.sort(key=lambda file_path: os.path.basename(file_path).lower())
    video_materials_list = []
    for file in files:
        filename = os.path.basename(file)
        video_materials_list.append(
            {
                "name": filename,
                "size": os.path.getsize(file),
                # 与 BGM 一样，只返回相对路径；创建任务时再在 local_videos
                # 白名单目录内解析，避免 API 泄露宿主机绝对路径。
                "file": (
                    f"{own_rel}/{filename}"
                    if os.path.dirname(file) == own_dir
                    else filename
                ),
            }
        )
    response = {"files": video_materials_list}
    return utils.get_response(200, response)


@router.post(
    "/video_materials",
    response_model=VideoMaterialUploadResponse,
    summary="Upload the video material file to the local videos directory",
)
def upload_video_material_file(
    request: Request,
    file: UploadFile = File(...),
    user_id: str = Depends(require_caller),
):
    request_id = base.get_task_id(request)
    safe_filename = _sanitize_upload_filename(file.filename, request_id)
    # check file ext
    allowed_suffixes = _MATERIAL_SUFFIXES
    suffix = pathlib.Path(safe_filename).suffix.lower().lstrip(".")
    # 按完整扩展名校验，既兼容 .MOV 这类大写后缀，也避免 photojpg 这种没有
    # 点号的文件名因为 endswith("jpg") 被误当成合法图片。
    if suffix in allowed_suffixes:
        local_videos_dir = utils.storage_dir("local_videos", create=True)
        own_rel = user_upload_subdir(user_id)
        own_dir = os.path.join(local_videos_dir, own_rel)
        os.makedirs(own_dir, exist_ok=True)
        save_path = os.path.join(own_dir, safe_filename)
        # save file (into the caller's private namespace; same name overwrites
        # only the caller's own copy)
        with open(save_path, "wb+") as buffer:
            file.file.seek(0)
            buffer.write(file.file.read())
        response = {"file": f"{own_rel}/{safe_filename}"}
        return utils.get_response(200, response)

    raise HttpException(
        "", status_code=400, message=f"{request_id}: Only files with extensions {', '.join(allowed_suffixes)} can be uploaded"
    )

@router.get("/stream/{file_path:path}")
async def stream_video(
    request: Request, file_path: str, user_id: str = Depends(require_caller)
):
    request_id = base.get_task_id(request)
    _require_task_file_owner(file_path, user_id, request_id)
    tasks_dir = utils.task_dir()
    video_path = _resolve_path_within_directory(tasks_dir, file_path, request_id)
    range_header = request.headers.get("Range")
    video_size = os.path.getsize(video_path)
    start, end = _parse_byte_range(range_header, video_size, request_id)
    length = end - start + 1

    def file_iterator(file_path, offset=0, bytes_to_read=None):
        with open(file_path, "rb") as f:
            f.seek(offset, os.SEEK_SET)
            remaining = bytes_to_read or video_size
            while remaining > 0:
                bytes_to_read = min(4096, remaining)
                data = f.read(bytes_to_read)
                if not data:
                    break
                remaining -= len(data)
                yield data

    response = StreamingResponse(
        file_iterator(video_path, start, length), media_type="video/mp4"
    )
    response.headers["Content-Range"] = f"bytes {start}-{end}/{video_size}"
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Length"] = str(length)
    response.status_code = 206  # Partial Content

    return response


@router.get("/download/{file_path:path}")
async def download_video(
    request: Request, file_path: str, user_id: str = Depends(require_caller)
):
    """
    download video
    :param request: Request request
    :param file_path: video file path, eg: /cd1727ed-3473-42a2-a7da-4faafafec72b/final-1.mp4
    :return: video file
    """
    request_id = base.get_task_id(request)
    _require_task_file_owner(file_path, user_id, request_id)
    tasks_dir = utils.task_dir()
    video_path = _resolve_path_within_directory(tasks_dir, file_path, request_id)
    file_path = pathlib.Path(video_path)
    filename = file_path.stem
    extension = file_path.suffix
    headers = {"Content-Disposition": f"attachment; filename={filename}{extension}"}
    return FileResponse(
        path=video_path,
        headers=headers,
        filename=f"{filename}{extension}",
        media_type=f"video/{extension[1:]}",
    )
