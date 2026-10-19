import re
import warnings
from enum import Enum
from typing import Any, List, Literal, Optional, Union

import pydantic
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import config

# 忽略 Pydantic 的特定警告
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message="Field name.*shadows an attribute in parent.*",
)


class VideoConcatMode(str, Enum):
    random = "random"
    sequential = "sequential"


class VideoTransitionMode(str, Enum):
    none = None
    shuffle = "Shuffle"
    fade_in = "FadeIn"
    fade_out = "FadeOut"
    slide_in = "SlideIn"
    slide_out = "SlideOut"
    zoom_in = "ZoomIn"
    zoom_out = "ZoomOut"


class VideoAspect(str, Enum):
    landscape = "16:9"
    portrait = "9:16"
    square = "1:1"

    def to_resolution(self):
        if self == VideoAspect.landscape:
            return 1920, 1080
        elif self == VideoAspect.portrait:
            return 1080, 1920
        elif self == VideoAspect.square:
            return 1080, 1080
        raise ValueError(f"unsupported video aspect: {self}")


class _Config:
    arbitrary_types_allowed = True


@pydantic.dataclasses.dataclass(config=_Config)
class MaterialInfo:
    provider: str = "pexels"
    url: str = ""
    duration: int = 0
    # 在线素材搜索会附带经过筛选的公开来源信息，供搜索缓存和任务记录复用。
    # 本地上传素材不需要填写；写入任务文件前仍会按字段白名单重新构造，
    # 避免外部请求传入的签名 URL、凭据或无关字段进入持久化数据。
    source_info: Optional[dict[str, Any]] = None


class VideoParams(BaseModel):
    """
    {
      "video_subject": "",
      "video_aspect": "横屏 16:9（西瓜视频）",
      "voice_name": "女生-晓晓",
      "bgm_name": "random",
      "font_name": "STHeitiMedium 黑体-中",
      "text_color": "#FFFFFF",
      "font_size": 60,
      "stroke_color": "#000000",
      "stroke_width": 1.5
    }
    """

    video_subject: str
    video_script: str = ""  # Script used to generate the video
    video_terms: Optional[str | list] = None  # Keywords used to generate the video
    video_aspect: Optional[VideoAspect] = VideoAspect.portrait.value
    video_concat_mode: Optional[VideoConcatMode] = VideoConcatMode.random.value
    video_transition_mode: Optional[VideoTransitionMode] = None
    video_clip_duration: int = Field(default=5, ge=1)
    video_clip_speed: Optional[float] = 1.0
    match_materials_to_script: bool = False
    video_count: int = Field(default=1, ge=1)

    video_source: Optional[str] = "pexels"
    video_materials: Optional[List[MaterialInfo]] = (
        None  # Materials used to generate the video
    )

    custom_audio_file: Optional[str] = (
        None  # Custom audio file path, will ignore TTS and can still use Whisper subtitles
    )
    video_language: Optional[str] = ""  # auto detect

    voice_name: Optional[str] = ""
    voice_volume: Optional[float] = 1.0
    voice_rate: Optional[float] = 1.0
    bgm_type: Optional[str] = "random"
    bgm_file: Optional[str] = ""
    bgm_volume: Optional[float] = 0.2
    # 视频配乐供应商共用提示词，WebUI 新任务统一写入该字段。保留下面的
    # Sonilo 专用字段以兼容旧任务记录和现有 CLI 参数。
    video_music_prompt: str = Field(default="", max_length=2000)
    sonilo_bgm_prompt: str = Field(default="", max_length=2000)

    subtitle_enabled: Optional[bool] = True
    subtitle_position: Optional[str] = config.ui.get(
        "subtitle_position", "bottom"
    )  # top, bottom, center, custom
    custom_position: float = config.ui.get("custom_position", 70.0)
    font_name: Optional[str] = "STHeitiMedium.ttc"
    text_fore_color: Optional[str] = "#FFFFFF"
    text_background_color: Union[bool, str] = False
    rounded_subtitle_background: bool = False

    font_size: int = 60
    stroke_color: Optional[str] = "#000000"
    stroke_width: float = 1.5
    n_threads: Optional[int] = 2
    paragraph_number: int = Field(default=1, ge=1, le=10)
    video_script_prompt: str = Field(default="", max_length=2000)
    custom_system_prompt: str = Field(default="", max_length=8000)


class SubtitleRequest(BaseModel):
    video_script: str
    video_language: Optional[str] = ""
    voice_name: Optional[str] = "zh-CN-XiaoxiaoNeural-Female"
    voice_volume: Optional[float] = 1.0
    voice_rate: Optional[float] = 1.2
    bgm_type: Optional[str] = "random"
    bgm_file: Optional[str] = ""
    bgm_volume: Optional[float] = 0.2
    subtitle_position: Optional[str] = config.ui.get("subtitle_position", "bottom")
    font_name: Optional[str] = "STHeitiMedium.ttc"
    text_fore_color: Optional[str] = "#FFFFFF"
    text_background_color: Union[bool, str] = False
    rounded_subtitle_background: bool = False
    font_size: int = 60
    stroke_color: Optional[str] = "#000000"
    stroke_width: float = 1.5
    video_source: Optional[str] = "local"
    subtitle_enabled: Optional[str] = "true"


class AudioRequest(BaseModel):
    video_script: str
    video_language: Optional[str] = ""
    voice_name: Optional[str] = "zh-CN-XiaoxiaoNeural-Female"
    voice_volume: Optional[float] = 1.0
    voice_rate: Optional[float] = 1.2
    bgm_type: Optional[str] = "random"
    bgm_file: Optional[str] = ""
    bgm_volume: Optional[float] = 0.2
    video_source: Optional[str] = "local"


class VideoScriptParams:
    """
    {
      "video_subject": "春天的花海",
      "video_language": "",
      "paragraph_number": 1,
      "video_script_prompt": "",
      "custom_system_prompt": ""
    }
    """

    video_subject: Optional[str] = "春天的花海"
    video_language: Optional[str] = ""
    paragraph_number: int = Field(default=1, ge=1, le=10)
    video_script_prompt: str = Field(default="", max_length=2000)
    custom_system_prompt: str = Field(default="", max_length=8000)


class VideoTermsParams:
    """
    {
      "video_subject": "",
      "video_script": "",
      "amount": 5,
      "match_materials_to_script": false
    }
    """

    video_subject: Optional[str] = "春天的花海"
    video_script: Optional[str] = (
        "春天的花海，如诗如画般展现在眼前。万物复苏的季节里，大地披上了一袭绚丽多彩的盛装。金黄的迎春、粉嫩的樱花、洁白的梨花、艳丽的郁金香……"
    )
    amount: Optional[int] = 5
    match_materials_to_script: bool = False


class VideoSocialMetadataParams:
    """
    {
      "video_subject": "A day in Shanghai",
      "video_script": "",
      "language": "auto",
      "platform": "tiktok"
    }
    """

    video_subject: Optional[str] = Field(default="A day in Shanghai", max_length=500)
    video_script: Optional[str] = Field(default="", max_length=8000)
    language: Optional[str] = Field(default="auto", max_length=64)
    platform: Optional[str] = Field(default="tiktok", max_length=64)


class BaseResponse(BaseModel):
    status: int = 200
    message: Optional[str] = "success"
    data: Any = None


class TaskVideoRequest(VideoParams, BaseModel):
    pass


class TaskQueryRequest(BaseModel):
    pass


class VideoScriptRequest(VideoScriptParams, BaseModel):
    pass


class VideoTermsRequest(VideoTermsParams, BaseModel):
    pass


class VideoSocialMetadataRequest(VideoSocialMetadataParams, BaseModel):
    pass


######################################################################################################
######################################################################################################
######################################################################################################
######################################################################################################
class TaskResponse(BaseResponse):
    class TaskResponseData(BaseModel):
        task_id: str

    data: TaskResponseData

    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {"task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558"},
            },
        }


class TaskStatusData(BaseModel):
    """任务查询对外保证的稳定字段；历史和扩展字段继续原样透传。"""

    model_config = ConfigDict(extra="allow")

    task_id: str
    state: int
    progress: int = 0
    videos: Optional[List[str]] = None
    combined_videos: Optional[List[str]] = None
    failed_stage: Optional[str] = None
    error: Optional[str] = None
    cross_post_state: Optional[
        Literal["pending", "processing", "complete", "failed"]
    ] = None
    cross_post_results: Optional[List[dict[str, Any]]] = None
    cross_post_error: Optional[str] = None


class TaskListData(BaseModel):
    """分页任务列表结构。"""

    tasks: List[TaskStatusData]
    total: int
    page: int
    page_size: int


class TaskQueryResponse(BaseResponse):
    """
    任务查询会返回生成状态和可选的跨平台发布状态。

    生成失败时包含 `failed_stage` 和 `error`；生成完成后如果启用了自动发布，
    `cross_post_state` 会依次进入 pending、processing、complete 或 failed。
    """

    data: TaskStatusData

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": 200,
                    "message": "success",
                    "data": {
                        "task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558",
                        "state": 1,
                        "progress": 100,
                        "videos": ["/tasks/example/final-1.mp4"],
                        "cross_post_state": "complete",
                        "cross_post_results": [{"success": True}],
                    },
                },
                {
                    "status": 200,
                    "message": "success",
                    "data": {
                        "task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558",
                        "state": -1,
                        "progress": 30,
                        "failed_stage": "audio",
                        "error": "TTS request timed out",
                    },
                },
            ],
        }
    )


class TaskListResponse(BaseResponse):
    """任务列表使用独立响应模型，避免与单任务查询混用文档结构。"""

    data: TaskListData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "tasks": [
                        {
                            "task_id": "6c85c8cc-a77a-42b9-bc30-947815aa0558",
                            "state": 4,
                            "progress": 50,
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 10,
                },
            }
        }
    )


class TaskDeletionResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "state": 1,
                    "progress": 100,
                    "videos": [
                        "http://127.0.0.1:8080/tasks/6c85c8cc-a77a-42b9-bc30-947815aa0558/final-1.mp4"
                    ],
                    "combined_videos": [
                        "http://127.0.0.1:8080/tasks/6c85c8cc-a77a-42b9-bc30-947815aa0558/combined-1.mp4"
                    ],
                },
            },
        }


class VideoScriptResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "video_script": "春天的花海，是大自然的一幅美丽画卷。在这个季节里，大地复苏，万物生长，花朵争相绽放，形成了一片五彩斑斓的花海..."
                },
            },
        }


class VideoTermsResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {"video_terms": ["sky", "tree"]},
            },
        }


class VideoSocialMetadataResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "title": "A Day in Shanghai You Should Not Miss",
                    "caption": "Save this quick Shanghai inspiration and follow for more short travel ideas.",
                    "hashtags": ["#shorts", "#travel", "#shanghai", "#viral", "#fyp"],
                },
            },
        }


class BgmRetrieveResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "files": [
                        {
                            "name": "4fca18fce7344f3aa824777a40d45c8c.mp3",
                            "size": 1891269,
                            "file": "4fca18fce7344f3aa824777a40d45c8c.mp3",
                        }
                    ]
                },
            },
        }


class BgmUploadResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {"file": "4fca18fce7344f3aa824777a40d45c8c.mp3"},
            },
        }


class VideoMaterialRetrieveResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "files": [
                        {
                            "name": "example.mp4",
                            "size": 12345678,
                            "file": "/MoneyPrinterTurbo/resource/videos/example.mp4",
                        }
                    ]
                },
            },
        }


class VideoMaterialUploadResponse(BaseResponse):
    class Config:
        json_schema_extra = {
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "file": "/MoneyPrinterTurbo/resource/videos/example.mp4",
                },
            },
        }


######################################################################################################
# ReelForge v1 API models (INTEGRATION_CONTRACT.md §5)
#
# These request/response models back ``app/controllers/v1/jobs.py``. Response
# ``data`` models use ``ConfigDict(extra="allow")`` so handlers can attach
# optional/forward-compatible fields (e.g. ``result_url``) without breaking the
# schema — mirroring the existing ``TaskStatusData`` convention above.
######################################################################################################


# MIME types this app actually accepts for client-side uploads. The presigned
# ``content_type`` is signed verbatim into the R2 PUT, so an unrestricted value
# (e.g. ``text/html``) would let a client stage arbitrary content under our
# bucket — the allowlist below is the trust boundary for that field.
ALLOWED_UPLOAD_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "audio/mpeg",
        "audio/wav",
        "image/png",
        "image/jpeg",
    }
)


class PresignRequest(BaseModel):
    """Request body for ``POST /api/v1/uploads/presign`` (§5.1)."""

    filename: str = Field(..., min_length=1, max_length=512)
    content_type: str = Field(..., min_length=1, max_length=200)
    size: int = Field(..., ge=1)

    @field_validator("content_type")
    @classmethod
    def _validate_content_type(cls, value: str) -> str:
        """Reject any MIME outside the media-type allowlist (§5.1 security).

        Normalises to the bare, lower-cased type (dropping any ``; charset=...``
        parameters) so the value signed into the R2 PUT is canonical.
        """
        normalized = value.split(";")[0].strip().lower()
        if normalized not in ALLOWED_UPLOAD_CONTENT_TYPES:
            allowed = ", ".join(sorted(ALLOWED_UPLOAD_CONTENT_TYPES))
            raise ValueError(f"unsupported content_type '{value}'; allowed: {allowed}")
        return normalized


class PresignData(BaseModel):
    """Presigned upload payload returned to the client (§5.1)."""

    model_config = ConfigDict(extra="allow")

    upload_url: str
    get_url: str
    key: str
    headers: dict[str, str] = Field(default_factory=dict)


class PresignResponse(BaseResponse):
    data: PresignData


class GenerationCapabilities(BaseModel):
    """Generation features available to the authenticated client."""

    reels: bool
    broll: bool


class CanonicalGenerationRoutes(BaseModel):
    """Stable route roots clients use for generation workflows."""

    reels: str
    broll: str


class PilotLimits(BaseModel):
    """Non-sensitive pilot limits suitable for client presentation."""

    pilot_enabled: bool
    max_credits_per_request: Optional[int] = None


class PilotCapabilities(BaseModel):
    """Shared read-only capability document for every first-party client."""

    mode: Literal["internal_pilot", "standard"]
    generation: GenerationCapabilities
    canonical_routes: CanonicalGenerationRoutes
    limits: PilotLimits
    # Additive product contract. Clients may use this to render only approved
    # B-roll modes; raw model/checkpoint controls never cross the API boundary.
    engine: dict[str, Any] = Field(default_factory=dict)
    product: dict[str, Any] = Field(default_factory=dict)
    launch: dict[str, Any] = Field(default_factory=dict)


class PilotCapabilitiesResponse(BaseResponse):
    data: PilotCapabilities


class RegisterUploadRequest(BaseModel):
    """Request body for ``POST /api/v1/uploads/register``.

    Records a freshly-uploaded object (an ``uploads/<uuid>`` key from
    {@link presign}) as an :class:`Asset` OWNED by the caller, so a later feature
    (custom avatar, i2v B-roll reference) can verify ownership via the BOLA guard.
    ``key`` MUST be in the non-enumerable ``uploads/`` namespace — a ``jobs/...``
    artifact key is rejected so a caller can never claim another creator's
    per-job output as their own upload.
    """

    key: str = Field(..., min_length=1, max_length=512)
    kind: str = Field(default="image", max_length=40)


class RegisterUploadData(BaseModel):
    """The persisted asset id + key for a registered upload."""

    model_config = ConfigDict(extra="allow")

    asset_id: str
    key: str
    kind: str = "image"


class RegisterUploadResponse(BaseResponse):
    data: RegisterUploadData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "asset_id": "asset_abc123",
                    "key": "uploads/abc.mp4",
                    "kind": "video",
                },
            }
        }
    )


# ------------------------------------------------------------------------------------ #
# Phase-6 Creator-Studio input allowlists (§6)
#
# ``caption_style`` resolves against a *static, in-code* preset registry
# (``captions.presets.CAPTION_STYLE_PRESETS``). ``get_caption_style`` silently
# falls back to the default preset for any unknown id, so a misspelled id would
# otherwise pass validation, debit a credit, and render in the wrong style with
# a 200. We therefore enforce the same allowlist the catalog endpoint exposes at
# the request boundary — before the credit debit — so a bad id fails fast.
#
# ``music_id`` resolves against a *dynamic, filesystem* catalog
# (``resource/songs`` via ``music._scan``); ``get_music_path`` returns ``None``
# for any unknown id, silently producing a music-less video. Because that catalog
# is deployment-specific we validate the id *shape* the catalog can ever mint (a
# lowercase ``[a-z0-9]`` slug joined by single hyphens, no path separators)
# rather than coupling the DTO to filesystem state; traversal payloads,
# whitespace, and other unmintable ids are rejected at the boundary.
# ------------------------------------------------------------------------------------ #

_MUSIC_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _valid_caption_style_ids() -> Optional[frozenset]:
    """Return the caption-style preset allowlist, or ``None`` when unavailable.

    Degrades open (``None``) if the preset registry cannot be imported so the
    request model never hard-fails on an optional service import; callers treat
    ``None`` as "cannot validate — accept" mirroring the catalog endpoint's
    degrade-to-empty behaviour.
    """
    try:
        from app.services.captions.presets import CAPTION_STYLE_PRESETS

        return frozenset(CAPTION_STYLE_PRESETS.keys())
    except Exception:  # noqa: BLE001 - degrade open if presets are unavailable.
        return None


def _validate_caption_style(value: Optional[str]) -> Optional[str]:
    """Reject an unknown ``caption_style`` id up-front (§6).

    ``None``/empty pass through unchanged (the pipeline applies the default
    preset). A non-empty id is checked against the static preset allowlist so a
    misspelled id fails fast with a client error instead of silently rendering
    in the default style after a credit has been charged.
    """
    if value is None:
        return value
    style_id = value.strip()
    if not style_id:
        return value
    allowed = _valid_caption_style_ids()
    if allowed is not None and style_id not in allowed:
        raise ValueError(
            f"unknown caption_style {style_id!r}; expected one of "
            f"{sorted(allowed)} (see GET /api/v1/catalog/caption-styles)"
        )
    return value


def _validate_music_id(value: Optional[str]) -> Optional[str]:
    """Reject a structurally-invalid ``music_id`` up-front (§6).

    Background-music ids are lowercase ``[a-z0-9]`` slugs joined by single
    hyphens (derived from track filenames in ``music._scan``). Enforcing that
    shape at the DTO boundary rejects traversal payloads, whitespace and other
    ids the catalog can never mint — which would otherwise be persisted verbatim
    and silently drop the background track at compose time. ``None``/empty pass
    through unchanged (no background music).
    """
    if value is None:
        return value
    music_id = value.strip()
    if not music_id:
        return value
    if not _MUSIC_ID_PATTERN.match(music_id):
        raise ValueError(
            f"invalid music_id {music_id!r}; expected a lowercase '[a-z0-9-]' "
            "track slug (see GET /api/v1/catalog/music)"
        )
    return value


# AI-BGM provider ids the pipeline can dispatch to (mirrors
# ``task._VIDEO_MUSIC_PROVIDERS``). ``""`` is a sentinel meaning "auto-select the
# first enabled provider" and is accepted alongside these.
_AI_BGM_PROVIDERS: frozenset[str] = frozenset({"elevenlabs", "sonilo"})


def _validate_bgm_provider(value: Optional[str]) -> Optional[str]:
    """Reject an unknown AI-BGM provider id up-front.

    ``None`` (omitted) and ``""`` (auto-select the first enabled provider) pass
    through unchanged; any other value must name a supported AI-music integration
    (``elevenlabs`` / ``sonilo``, see ``GET /api/v1/catalog/music-generators``).
    Validating at the DTO boundary turns a bad provider into a clean 422 instead
    of a silently-ignored request field.
    """
    if value is None:
        return value
    provider = value.strip().lower()
    if not provider:
        return value
    if provider not in _AI_BGM_PROVIDERS:
        raise ValueError(
            f"unknown bgm_provider {provider!r}; expected one of "
            f"{sorted(_AI_BGM_PROVIDERS)} (see GET /api/v1/catalog/music-generators)"
        )
    return provider


# Fake-camera motion presets the editing pass can bake into the screen recording
# (mirrors ``app.services.editing.motion.MOTION_PRESETS`` — kept as a local
# frozenset so the schema module never drags in the ffmpeg/editing stack, exactly
# like ``_AI_BGM_PROVIDERS`` mirrors the task provider list). ``"none"`` is the
# explicit no-op default; the rest each render a subtle synthetic camera move.
_CAMERA_MOTION_PRESETS: frozenset[str] = frozenset(
    {"none", "ken_burns", "push_in", "pull_out", "whip_pan"}
)


def _validate_camera_motion(value: Optional[str]) -> Optional[str]:
    """Reject an unknown ``camera_motion`` preset up-front.

    Two rendering systems key off this one field and BOTH are accepted:

    * **legacy pre-compose editing pass** (``app.services.editing.motion``) —
      ``ken_burns`` / ``push_in`` / ``pull_out`` baked into the screen recording;
    * **Higgsfield-class compose-stage VFX render** (``app.domains.catalog.presets``
      → ``app.services.compose.vfx``) — the 20-move catalog (``dolly_in`` /
      ``crash_zoom_in`` / ``orbit_360`` / ``whip_pan`` …) spliced into the
      filtergraph.

    ``None`` (field omitted) passes through unchanged; ``""`` normalises to the
    ``"none"`` no-op. Validating at the DTO boundary turns a bad preset into a
    clean 422 instead of a silent no-op deep in the compose stage. The catalog is
    imported lazily (per request, never at module import) so this schema module
    never drags in the heavy ``catalog`` package/router at import time.
    """
    if value is None:
        return value
    preset = value.strip().lower()
    if not preset:
        return "none"
    if preset in _CAMERA_MOTION_PRESETS:
        return preset
    # Not a legacy preset — try the Higgsfield-class camera-motion catalog.
    try:
        from app.domains.catalog import presets as _presets
    except Exception as exc:  # pragma: no cover - defensive (catalog unavailable)
        raise ValueError(
            f"unknown camera_motion {preset!r}; expected one of "
            f"{sorted(_CAMERA_MOTION_PRESETS)}"
        ) from exc
    try:
        return _presets.validate_camera_motion(preset)
    except _presets.PresetError as exc:
        raise ValueError(str(exc)) from exc


def _validate_effects(value: Optional[list[str]]) -> Optional[list[str]]:
    """Normalise + reject an unknown ``effects`` (Effects-Mix VFX stack) up-front.

    ``None`` (field omitted) passes through unchanged. Otherwise the stack is
    deduped (order-preserving), capped, and every id validated against the
    reviewed VFX catalog (``app.domains.catalog.presets``) — an unknown id or an
    over-cap stack is a clean 422 at the request boundary rather than a silent
    skip in the compose stage. The catalog is imported lazily so this schema
    module never drags the heavy ``catalog`` package/router at import time.
    """
    if value is None:
        return value
    from app.domains.catalog import presets as _presets

    try:
        return _presets.validate_effects_stack(list(value))
    except _presets.PresetError as exc:
        raise ValueError(str(exc)) from exc


class JobCreateRequest(BaseModel):
    """Request body for ``POST /api/v1/jobs`` (§5.1).

    ``params`` carries a ``ReelForgeParams``-shaped mapping (validated by the
    dataclass in ``app/services/reelforge.py`` at handler time). Optional
    top-level ``avatar_id`` / ``voice_id`` overrides are folded into ``params``
    by the controller.
    """

    model_config = ConfigDict(extra="allow")

    params: dict[str, Any] = Field(default_factory=dict)
    # Optional first-party acquisition provenance. This is deliberately narrow:
    # only a server-scored trend can be attributed, and values are bounded before
    # they enter Job.params. Publish telemetry later reuses the same fields.
    source_kind: Optional[Literal["trend"]] = None
    source_id: Optional[str] = Field(default=None, max_length=128)
    source_label: Optional[str] = Field(default=None, max_length=200)
    # Durable diffusion provenance. When present the server resolves this
    # caller-owned row and replaces loose client source labels with the bound
    # trend observation + forecast values before persisting Job.params.
    forecast_id: Optional[str] = Field(default=None, min_length=1, max_length=32)
    avatar_id: Optional[str] = None
    voice_id: Optional[str] = None
    # Creator-studio tweaks (Phase 6). All optional with safe ``None`` defaults so
    # existing clients are unaffected. ``caption_style`` folds into the validated
    # ``ReelForgeParams`` (it is a dataclass field); ``music_id`` /
    # ``webhook_url`` / ``webhook_secret`` are threaded into the persisted
    # ``Job.params`` JSON for the compose / notification stages (they are not
    # ``ReelForgeParams`` fields and are dropped from the strict DTO by design).
    caption_style: Optional[str] = Field(default=None, max_length=64)
    music_id: Optional[str] = Field(default=None, max_length=128)
    webhook_url: Optional[str] = Field(default=None, max_length=2048)
    webhook_secret: Optional[str] = Field(default=None, max_length=256)
    # AI background music (Phase: AI-BGM). Both optional with safe ``None``
    # defaults so existing clients are unaffected. ``music_prompt`` is a text
    # brief the chosen provider (``elevenlabs`` / ``sonilo``) turns into a custom
    # royalty-free BGM track; ``bgm_provider`` picks the provider ("" / ``None``
    # => the first enabled one). Both are real ``ReelForgeParams`` dataclass
    # fields, so the controller folds them into the validated render DTO and they
    # flow to the compose stage as ``music_path`` (best-effort — a music failure
    # never fails the job). The generous length cap here is a cheap guardrail; the
    # provider-specific ``MAX_PROMPT_LENGTH`` is enforced in the pipeline preflight.
    music_prompt: Optional[str] = Field(default=None, max_length=4000)
    bgm_provider: Optional[str] = Field(default=None, max_length=32)
    # AI B-roll cutaways. Optional R2 keys of short stock clips (typically chosen
    # from ``POST /jobs/{job_id}/broll/suggest``) spliced as a brief MUTED intro
    # (before the hook) and/or outro (after) around the composed reel. Both are
    # optional with safe ``None`` defaults so existing clients are unaffected.
    # They are real ``ReelForgeParams`` dataclass fields, so the controller folds
    # them into the validated render DTO and they flow to the compose stage
    # (best-effort: a B-roll failure never fails the job). A client-supplied key is
    # validated against the caller's own jobs by the ReelForge ownership guard at
    # consumption time (``_assert_owned_r2_key`` inside the compose stage), so a
    # caller cannot splice another creator's per-job artifact.
    broll_intro_key: Optional[str] = Field(default=None, max_length=1024)
    broll_outro_key: Optional[str] = Field(default=None, max_length=1024)
    # Bring Your Own Voiceover (BYOV): the R2 key of the creator's OWN uploaded
    # narration audio (staged via ``POST /uploads/presign`` with an
    # ``audio/mpeg`` / ``audio/wav`` content-type). When set the pipeline skips
    # TTS / voice-clone entirely — ``stage_tts`` downloads this audio, transcribes
    # it with faster-whisper for the §8 single-authority WORD timings (captions),
    # and the same audio drives the avatar lip-sync + duration. Optional with a
    # safe ``None`` default so existing clients are unaffected; it is a real
    # ``ReelForgeParams`` dataclass field, so the controller folds it into the
    # validated render DTO. The key is client-supplied and validated against the
    # caller's own jobs by the ReelForge ownership guard (``_assert_owned_r2_key``)
    # at consumption time, so a caller cannot reference another creator's artifact.
    # No credit change: a BYOV reel costs the same as a TTS reel.
    voiceover_key: Optional[str] = Field(default=None, max_length=1024)
    # Batch variants (§5a): how many independent reels to fan out from this
    # request. ``1`` (default) is the classic single-job path; ``2``/``3`` are
    # rendered as N independent jobs at the API layer (no DB/pipeline change) —
    # each with a temperature-0.9 script so the outputs differ. Bounded 1..3 so
    # a single request cannot debit an unbounded number of credits.
    variants: int = Field(default=1, ge=1, le=3)
    # ToS / AI-disclosure toggle (§5d). When ``True`` the render marks the
    # output as AI/synthetic media in the cross-post metadata (YouTube's
    # ``containsSyntheticMedia`` flag plus a human-readable disclosure note for
    # the other platforms). Defaults to ``False`` to keep behavior unchanged.
    tos_disclosure: bool = False
    # Auto-tighten (Submagic-style "Remove Silences" retention pre-step). When
    # ``True`` the raw screen recording is pre-processed with a pure-FFmpeg pass
    # that removes dead air (silent AND static stretches) BEFORE the compose
    # smart-handling / speed-ramp. It is a real ``ReelForgeParams`` field, so the
    # controller folds it into the validated render DTO and it is persisted in
    # ``Job.params`` (no migration). The pass is best-effort and degrade-safe (an
    # entirely silent/static clip or a tool failure returns the original
    # unchanged) and NEVER touches the voiceover/caption timeline — the final reel
    # duration is still governed by the script/TTS. Defaults to ``False`` so
    # existing clients are unaffected.
    auto_tighten: bool = False
    # Editing-polish suite (opt-in, default-off, degrade-safe pre-compose passes).
    # All three are real ``ReelForgeParams`` fields, so the controller folds them
    # into the validated render DTO and they are persisted in ``Job.params`` (no
    # migration). Each runs ONLY on the background SCREEN recording / AVATAR clip
    # and never on the voiceover/caption timeline, so the golden caption-drift gate
    # is unaffected with any flag on; each degrades to the ORIGINAL clip on failure
    # so it can never fail the job. Default off/none => byte-for-byte the current
    # path.
    #   * ``auto_zoom`` — scene-driven "punch-in" zooms on the screen recording.
    #   * ``camera_motion`` — synthetic "fake camera motion" preset baked into the
    #     screen recording (``none``/``ken_burns``/``push_in``/``pull_out``/
    #     ``whip_pan``); validated against the enum below.
    #   * ``remove_bg`` — neural (rembg, OPTIONAL) background matting of the avatar,
    #     composited over chroma green for the existing compose chromakey.
    auto_zoom: bool = False
    camera_motion: Optional[str] = Field(default=None, max_length=32)
    remove_bg: bool = False
    #   * ``effects`` — Higgsfield-class **Effects Mix**: a stackable list of
    #     reviewed VFX preset ids (``glitch`` / ``light_leak`` / ``datamosh`` …)
    #     rendered at the compose stage (``app.services.compose.vfx``). Deduped,
    #     capped, and validated against the catalog below; ``None`` (omitted) is
    #     no VFX (byte-for-byte the current path).
    #   * ``vfx_intensity`` — 0..100 strength applied to the selected
    #     camera-motion + VFX fragments (default 50).
    effects: Optional[list[str]] = Field(default=None)
    vfx_intensity: int = Field(default=50, ge=0, le=100)
    # Shared Workspace Credits: when set, this job debits the named workspace's
    # SHARED credit pool instead of the caller's personal balance. The caller
    # must be a member of the workspace (enforced in the controller — a
    # non-member is rejected with 403). Left ``None`` (the default) the job
    # keeps the classic per-user debit path, so existing clients are unaffected.
    workspace_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("variants")
    @classmethod
    def _validate_variants(cls, value: int) -> int:
        """Clamp/reject ``variants`` outside the supported 1..3 batch range."""
        if value < 1 or value > 3:
            raise ValueError("variants must be between 1 and 3 (inclusive)")
        return value

    @field_validator("caption_style")
    @classmethod
    def _validate_caption_style_field(cls, value: Optional[str]) -> Optional[str]:
        """Reject an unknown ``caption_style`` id before the credit debit (§6)."""
        return _validate_caption_style(value)

    @field_validator("music_id")
    @classmethod
    def _validate_music_id_field(cls, value: Optional[str]) -> Optional[str]:
        """Reject a structurally-invalid ``music_id`` before the credit debit (§6)."""
        return _validate_music_id(value)

    @field_validator("bgm_provider")
    @classmethod
    def _validate_bgm_provider_field(cls, value: Optional[str]) -> Optional[str]:
        """Reject an unknown AI-BGM provider before the credit debit.

        ``None`` (field omitted) and ``""`` (auto-select the first enabled
        provider) are both allowed; any other value must name a supported
        AI-music integration (``elevenlabs`` / ``sonilo``). Validating here means
        a bad provider is a clean 422 at the request boundary instead of a silent
        no-op deep in the pipeline.
        """
        return _validate_bgm_provider(value)

    @field_validator("camera_motion")
    @classmethod
    def _validate_camera_motion_field(cls, value: Optional[str]) -> Optional[str]:
        """Reject an unknown ``camera_motion`` preset before the credit debit."""
        return _validate_camera_motion(value)

    @field_validator("effects")
    @classmethod
    def _validate_effects_field(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        """Reject an unknown/over-cap ``effects`` stack before the credit debit."""
        return _validate_effects(value)


class JobData(BaseModel):
    """Public job status envelope (§5.1).

    Only ``job_id``/``state``/``progress`` are guaranteed on create; status
    reads add ``stages`` and, when present, ``failed_stage`` / ``error`` /
    ``result_url``.

    When a batch request fans out into multiple variants (``variants > 1``),
    the create response carries every spawned job id in ``job_ids`` while
    ``job_id`` stays populated with the first one for backward compatibility,
    plus a shared ``batch_id`` linking the variants for joint review
    (``GET /api/v1/batches/{batch_id}``); for a single job (``variants == 1``)
    both ``job_ids`` and ``batch_id`` are left ``None``.
    """

    model_config = ConfigDict(extra="allow")

    job_id: str
    kind: Optional[str] = None
    state: int
    progress: int = 0
    stages: Optional[dict[str, Any]] = None
    failed_stage: Optional[str] = None
    error: Optional[str] = None
    result_url: Optional[str] = None
    # Durable R2 keys are returned for server-side handoffs (cover generation,
    # publishing, and attaching generated media). Browser/native playback must
    # use the matching presigned URL fields; clients never need R2 credentials.
    poster_key: Optional[str] = None
    poster_url: Optional[str] = None
    preview_key: Optional[str] = None
    preview_url: Optional[str] = None
    cover_key: Optional[str] = None
    cover_url: Optional[str] = None
    # Additive presentation metadata derived from the persisted job params and
    # finalized script. These keep all clients from reverse-engineering the
    # internal ``params`` JSON shape.
    language: Optional[str] = None
    hook: Optional[str] = None
    created_at: Optional[str] = None
    # Server-derived creator-path readiness. These booleans come from persisted
    # job params/script; clients do not infer that footage or a brief exists.
    source_footage_ready: Optional[bool] = None
    brief_ready: Optional[bool] = None
    job_ids: Optional[List[str]] = None
    batch_id: Optional[str] = None
    # Echoed on create/status responses so API, workers, and client logs can be
    # correlated during the internal pilot. Additive for existing clients.
    correlation_id: Optional[str] = None
    retry_eligible: Optional[bool] = None


class JobResponse(BaseResponse):
    data: JobData

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": 200,
                    "message": "success",
                    "data": {"job_id": "b1c2...", "state": 4, "progress": 0},
                },
                {
                    "status": 200,
                    "message": "success",
                    "data": {
                        "job_id": "b1c2...",
                        "state": 1,
                        "progress": 100,
                        "stages": {"script": "complete", "tts": "complete"},
                        "result_url": "https://r2.example.com/jobs/b1c2/final.mp4?X-Amz-...",
                    },
                },
            ]
        }
    )


class JobListData(BaseModel):
    """Envelope for ``GET /api/v1/jobs`` — the caller's own jobs, newest first."""

    model_config = ConfigDict(extra="allow")

    jobs: List[JobData] = Field(default_factory=list)


class JobListResponse(BaseResponse):
    data: JobListData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "jobs": [
                        {"job_id": "b1c2...", "state": 4, "progress": 50},
                        {"job_id": "a9d8...", "state": 1, "progress": 100},
                    ]
                },
            }
        }
    )


class BatchJobData(BaseModel):
    """One variant's status inside a batch-review listing (Phase-10).

    Only the fields a batch-review UI needs: the job id, its live
    ``state``/``progress``, and — when the render has finished — a presigned
    ``result_url`` plus the ``poster_key`` of its thumbnail frame. Both are
    optional (a still-processing variant has neither). ``extra="allow"`` mirrors
    the ``JobData`` convention so forward-compatible fields can be attached
    without a schema break.
    """

    model_config = ConfigDict(extra="allow")

    job_id: str
    state: int
    progress: int = 0
    result_url: Optional[str] = None
    poster_key: Optional[str] = None
    poster_url: Optional[str] = None
    preview_key: Optional[str] = None
    preview_url: Optional[str] = None
    cover_key: Optional[str] = None
    cover_url: Optional[str] = None


class BatchData(BaseModel):
    """Envelope for ``GET /api/v1/batches/{batch_id}`` — the batch's variants.

    ``jobs`` lists every variant of the batch owned by the caller (oldest first,
    so ``job_id`` — the first created variant — leads), enabling a side-by-side
    review of the N reels a single ``variants`` request fanned out.
    """

    model_config = ConfigDict(extra="allow")

    batch_id: str
    jobs: List[BatchJobData] = Field(default_factory=list)


class BatchResponse(BaseResponse):
    """``GET /api/v1/batches/{batch_id}`` — a batch of variant jobs for review."""

    data: BatchData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "batch_id": "9f8e7d...",
                    "jobs": [
                        {
                            "job_id": "b1c2...",
                            "state": 1,
                            "progress": 100,
                            "result_url": "https://r2.example.com/jobs/b1c2/final.mp4?X-Amz-...",
                            "poster_key": "jobs/b1c2/poster.jpg",
                        },
                        {"job_id": "a9d8...", "state": 4, "progress": 40},
                    ],
                },
            }
        }
    )


class AvatarListResponse(BaseResponse):
    """List of avatars (merged presets + provider catalog); ``data`` is a list."""

    data: List[dict[str, Any]]


class VoiceListResponse(BaseResponse):
    """Normalised ElevenLabs voices; ``data`` is a list of dicts."""

    data: List[dict[str, Any]]


class MeData(BaseModel):
    """Authenticated user profile summary (§5.1)."""

    model_config = ConfigDict(extra="allow")

    user_id: str
    email: str
    credits: int = 0
    jobs_count: int = 0
    is_staff: bool = False


class MeResponse(BaseResponse):
    data: MeData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "user_id": "b1c2...",
                    "email": "user@example.com",
                    "credits": 42,
                    "jobs_count": 7,
                },
            }
        }
    )


######################################################################################################
# ReelForge Creator Studio models (Phase 6): re-run-with-tweaks + catalogs
#
# ``RerunRequest`` backs ``POST /api/v1/jobs/{job_id}/rerun`` — it clones a
# source job's params and applies a small set of optional overrides before
# creating a fresh job. The catalog response models back the read-only
# ``GET /api/v1/catalog/*`` endpoints in ``app/controllers/v1/catalog.py``;
# each ``data`` payload is a plain list of dicts (mirroring ``AvatarListResponse``
# / ``VoiceListResponse``) so the catalog services own the exact item shape.
######################################################################################################


class RerunOverrides(BaseModel):
    """Optional per-field tweaks applied when re-running a job (Phase 6).

    Every field is optional; only the ones a client sets replace the source
    job's stored value. ``voice_id`` is normalised to the ``elevenlabs:<id>``
    ``voice_name`` form by the controller (matching ``JobCreateRequest``).
    """

    avatar_id: Optional[str] = Field(default=None, max_length=256)
    voice_id: Optional[str] = Field(default=None, max_length=256)
    layout: Optional[str] = Field(default=None, max_length=64)
    caption_style: Optional[str] = Field(default=None, max_length=64)
    music_id: Optional[str] = Field(default=None, max_length=128)
    language: Optional[str] = Field(default=None, max_length=64)

    @field_validator("caption_style")
    @classmethod
    def _validate_caption_style_field(cls, value: Optional[str]) -> Optional[str]:
        """Reject an unknown ``caption_style`` override before the re-run debit (§6)."""
        return _validate_caption_style(value)

    @field_validator("music_id")
    @classmethod
    def _validate_music_id_field(cls, value: Optional[str]) -> Optional[str]:
        """Reject a structurally-invalid ``music_id`` override before the re-run debit (§6)."""
        return _validate_music_id(value)

    # Opening-hook angle for a fresh variation (Autopost batches). Only applies
    # when Menivor writes the script; a re-run of a reel with the creator's own
    # script is refused with 409 instead of silently producing a duplicate.
    hook_style: Optional[str] = Field(default=None, max_length=40)

    @field_validator("hook_style")
    @classmethod
    def _validate_hook_style_field(cls, value: Optional[str]) -> Optional[str]:
        """Canonicalize the hook angle; an unknown one is a 422 before any debit."""
        if value is None or not str(value).strip():
            return None
        from app.domains.experiments.hook_styles import HookStyleError, normalize_hook_style

        try:
            return normalize_hook_style(value) or None
        except HookStyleError as exc:
            raise ValueError(str(exc)) from exc


class RerunRequest(BaseModel):
    """Request body for ``POST /api/v1/jobs/{job_id}/rerun`` (Phase 6).

    ``overrides`` is optional: an empty/absent body re-runs the source job with
    its original params (a clean re-render), while any supplied field tweaks the
    corresponding param on the new job.
    """

    overrides: Optional[RerunOverrides] = None


class DubRequest(BaseModel):
    """Request body for ``POST /api/v1/jobs/{job_id}/dub`` (multi-language dubbing).

    ``languages`` lists the target language codes to dub the source reel into —
    the source SCRIPT is translated per language and the normal pipeline is
    re-run (TTS via the ElevenLabs multilingual model, captions from the new
    timestamps, avatar, compose) reusing the source's screen recording / avatar /
    voice / layout / caption style. Every code is validated against
    ``translate.is_supported_language`` at handler time (400 on any unknown /
    empty code) and one credit is debited per language. The N dubbed jobs share
    one ``batch_id`` so they surface together in ``GET /api/v1/batches/{id}``.
    """

    languages: List[str] = Field(default_factory=list)


class DubData(BaseModel):
    """Envelope for a successful dub fan-out.

    ``batch_id`` is the single shared id linking the N dubbed jobs (one per
    requested language) for joint review via ``GET /api/v1/batches/{batch_id}``;
    ``job_ids`` and ``languages`` are positionally aligned (``job_ids[i]`` is the
    job dubbing into ``languages[i]``).
    """

    model_config = ConfigDict(extra="allow")

    batch_id: str
    job_ids: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)


class DubResponse(BaseResponse):
    """``POST /api/v1/jobs/{job_id}/dub`` — the fanned-out multi-language batch."""

    data: DubData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "batch_id": "9f8e7d...",
                    "job_ids": ["b1c2...", "a9d8...", "c3e4..."],
                    "languages": ["es", "fr", "de"],
                },
            }
        }
    )


# --------------------------------------------------------------------------- #
# AI B-roll cutaways (POST /api/v1/jobs/{job_id}/broll/suggest)
# --------------------------------------------------------------------------- #
#: Hard cap on how many B-roll clips a single suggestion request may fetch. Kept
#: in sync with ``app.services.broll.MAX_BROLL_AMOUNT`` — duplicated here (rather
#: than imported) so this pure-schema module never pulls in the heavier service
#: layer just to bound a field.
_MAX_BROLL_AMOUNT: int = 12


class BrollSuggestRequest(BaseModel):
    """Request body for ``POST /api/v1/jobs/{job_id}/broll/suggest``.

    Both fields are optional so a bare ``{}`` body works: ``source`` selects the
    backend — a stock provider (``pexels`` / ``pixabay`` / ...; the service
    defaults it) or ``"ai"`` to generate motion clips via the ``broll_gen``
    provider (ComfyUI/Wan) — and ``amount`` caps how many clips to fetch
    (1..``_MAX_BROLL_AMOUNT``; the AI path is capped tighter for GPU cost). The
    reel's search keywords / prompts are derived server-side from the *job's own*
    subject/script, never from the client, so no free-text prompt is accepted here.
    """

    source: Optional[str] = Field(default=None, max_length=32)
    amount: Optional[int] = Field(default=None, ge=1, le=_MAX_BROLL_AMOUNT)


class BrollClip(BaseModel):
    """One suggested B-roll cutaway clip.

    ``broll_key`` is the R2 object key of the fetched clip, always written under
    the requesting job's own ``jobs/<job_id>/broll/`` prefix (owned by that job).
    ``duration`` may be ``0.0`` when it could not be probed.
    """

    model_config = ConfigDict(extra="allow")

    broll_key: str
    duration: float = 0.0
    source: str = ""
    term: str = ""


class BrollSuggestData(BaseModel):
    """Envelope for a B-roll suggestion response: the list of suggested clips.

    ``clips`` may be empty — B-roll is best-effort, so a provider/LLM failure
    yields an empty list rather than an error.
    """

    model_config = ConfigDict(extra="allow")

    clips: List[BrollClip] = Field(default_factory=list)


class BrollSuggestResponse(BaseResponse):
    """``POST /api/v1/jobs/{job_id}/broll/suggest`` — suggested cutaway clips."""

    data: BrollSuggestData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "clips": [
                        {
                            "broll_key": "jobs/b1c2.../broll/9f8e7d.mp4",
                            "duration": 5.0,
                            "source": "pexels",
                            "term": "city skyline",
                        }
                    ]
                },
            }
        }
    )


class BrollGenerateRequest(BaseModel):
    """Request body for canonical ``POST /api/v1/generation/broll/generate``.

    Unlike the job-scoped ``suggest`` route (which derives prompts server-side),
    the studio accepts a **free-text** ``prompt`` — it *is* the product primitive.
    The prompt is length-capped and moderated server-side before any GPU spend.

    * ``prompt`` (required) — the motion description (1..500 chars).
    * ``mode`` — ``"t2v"`` (default) or ``"i2v"``; ``i2v`` requires ``image_key``.
    * ``image_key`` — an R2 key the caller OWNS (validated server-side, never an
      arbitrary URL) used as the i2v reference frame.
    * ``aspect`` — output aspect (defaults to portrait 1080x1920).
    * ``workflow_id`` — optional comfyui-deploy deployment / motion preset id.
    * ``seed`` — optional determinism seed.
    """

    prompt: str = Field(..., min_length=1, max_length=500)
    mode: Optional[str] = Field(default="t2v", max_length=8)
    image_key: Optional[str] = Field(default=None, max_length=512)
    aspect: Optional[VideoAspect] = None
    workflow_id: Optional[str] = Field(default=None, max_length=128)
    seed: Optional[int] = Field(default=None, ge=0)


class BrollGeneration(BaseModel):
    """One studio generation's lifecycle snapshot (a ``Job(kind='broll_gen')``).

    ``generation_id`` is the underlying job id — pollable via
    ``GET /api/v1/generation/broll/generations/{id}``. ``state`` follows the shared job
    states (4 processing, 1 complete, -1 failed); ``broll_key`` is the rendered
    clip's R2 key once complete (empty until then).
    """

    model_config = ConfigDict(extra="allow")

    generation_id: str
    state: int = 0
    progress: int = 0
    broll_key: str = ""
    # Best-effort presigned URL for a completed clip. It is deliberately absent
    # while rendering so clients never try to preview a partial object.
    result_url: str = ""
    duration: float = 0.0
    error: str = ""
    retry_eligible: bool = False
    correlation_id: str = ""


class BrollGenerationResponse(BaseResponse):
    """Canonical B-roll create/poll response envelope."""

    data: BrollGeneration


class BrollGenerationsResponse(BaseResponse):
    """Canonical B-roll history response for the authenticated caller."""

    data: List[BrollGeneration] = Field(default_factory=list)


class BrollPreset(BaseModel):
    """One curated (or user) AI B-roll motion preset for the studio picker.

    ``prompt_template`` is a starter prompt the UI drops into the prompt box (a
    ``{subject}`` placeholder, if present, is filled by the creator);
    ``default_params`` carries motion knobs forwarded to generation; ``mode`` is
    ``t2v`` or ``i2v``.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    description: str = ""
    mode: str = "t2v"
    prompt_template: str = ""
    thumbnail_url: str = ""
    workflow_id: str = ""
    default_params: dict[str, Any] = Field(default_factory=dict)


class BrollPresetsResponse(BaseResponse):
    """``GET /broll/presets`` — the caller's available motion presets."""

    data: List[BrollPreset] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Speak (lipsync) studio — image + narration audio -> talking video. Mirrors the
# B-roll studio DTOs (BrollGenerate*): an async ``Job(kind='speak_lipsync')`` the
# caller polls to completion.
# --------------------------------------------------------------------------- #
class SpeakGenerateRequest(BaseModel):
    """Request body for ``POST /api/v1/generation/speak/generate``.

    * ``image_key`` (required) — an R2 key the caller OWNS (validated
      server-side, never an arbitrary URL): the reference face/photo.
    * ``audio_key`` (required) — an R2 key the caller OWNS: the driving narration.
    * ``provider`` — optional reviewed lipsync provider key (e.g. ``"musetalk"``);
      empty resolves a commercial-safe default deterministically.
    """

    image_key: str = Field(..., min_length=1, max_length=512)
    audio_key: str = Field(..., min_length=1, max_length=512)
    provider: Optional[str] = Field(default=None, max_length=64)


class SpeakGeneration(BaseModel):
    """One speak generation's lifecycle snapshot (a ``Job(kind='speak_lipsync')``).

    ``generation_id`` is the underlying job id — pollable via
    ``GET /api/v1/generation/speak/generations/{id}``. ``state`` follows the shared
    job states; ``talking_video_key`` is the rendered clip's R2 key once complete
    (empty until then).
    """

    model_config = ConfigDict(extra="allow")

    generation_id: str
    state: int = 0
    progress: int = 0
    talking_video_key: str = ""
    result_url: str = ""
    provider: str = ""
    license_class: str = ""
    error: str = ""
    retry_eligible: bool = False
    correlation_id: str = ""


class SpeakGenerationResponse(BaseResponse):
    """Canonical speak create/poll response envelope."""

    data: SpeakGeneration


class SpeakGenerationsResponse(BaseResponse):
    """Canonical speak history response for the authenticated caller."""

    data: List[SpeakGeneration] = Field(default_factory=list)


class SpeakProvidersResponse(BaseResponse):
    """``GET /generation/speak/providers`` — bounded lipsync selectors + licenses."""

    data: dict[str, Any] = Field(default_factory=dict)


class CaptionStylesResponse(BaseResponse):
    """Caption-style catalog; ``data`` is a list of preset descriptors.

    ``data`` defaults to ``[]`` because the shared ``utils.get_response``
    envelope drops a falsy payload — an empty catalog must still validate as an
    empty list rather than a missing field.
    """

    data: List[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "karaoke_yellow",
                        "name": "Karaoke (yellow)",
                        "description": "White spoken words, yellow upcoming.",
                    }
                ],
            }
        }
    )


class MusicCatalogResponse(BaseResponse):
    """Background-music catalog; ``data`` is a list of track descriptors.

    Defaults to ``[]`` so an empty songs directory (or a degraded read) still
    validates against the shared falsy-dropping ``get_response`` envelope.
    """

    data: List[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [{"id": "upbeat", "name": "Upbeat", "filename": "upbeat.mp3"}],
            }
        }
    )


class LayoutCatalogResponse(BaseResponse):
    """Composition-layout catalog; ``data`` is a list of layout descriptors."""

    data: List[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "pip",
                        "name": "Picture-in-picture",
                        "description": "Avatar in a corner bubble over the screen recording.",
                    }
                ],
            }
        }
    )


######################################################################################################
# ReelForge Studio models (Phase 3): on-demand publish + photo→avatar preset
#
# These back ``app/controllers/v1/studio.py``. Response ``data`` models use
# ``ConfigDict(extra="allow")`` so the studio/publish services can attach
# forward-compatible fields without breaking the schema — mirroring the
# ``JobData`` / ``PresignData`` convention.
######################################################################################################


class PublishRequest(BaseModel):
    """Request body for ``POST /api/v1/jobs/{job_id}/publish`` (Phase 3).

    Re-publishes a *completed* job's rendered output to social platforms.
    ``platforms`` selects the targets (e.g. ``["tiktok", "instagram"]``);
    ``youtube_privacy_status`` overrides the YouTube visibility when publishing
    to YouTube.
    """

    platforms: List[str] = Field(default_factory=list)
    youtube_privacy_status: Optional[str] = Field(default=None, max_length=32)


class PublishResponse(BaseResponse):
    """Publish results envelope; ``data`` carries the per-platform outcomes."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "request_id": "b1c2...",
                    "results": [{"platform": "tiktok", "status": "success"}],
                },
            }
        }
    )


class CreateAvatarRequest(BaseModel):
    """Request body for ``POST /api/v1/avatars`` (Phase 3 — custom avatar).

    Creates a USER photo→avatar preset from a previously uploaded selfie
    (``image_key`` is the R2 key of the uploaded photo, which must be an upload
    the caller owns). The image is turned into a HeyGen *talking-photo* avatar
    that lip-syncs the reel's narration. ``display_name`` and ``voice_name``
    (``"elevenlabs:<voice_id>"``) are optional metadata.
    """

    image_key: str = Field(..., min_length=1, max_length=512)
    display_name: Optional[str] = Field(default="", max_length=200)
    voice_name: Optional[str] = Field(default="", max_length=120)


class CreateAvatarData(BaseModel):
    """Persisted ``AvatarPreset`` row serialised to the public envelope.

    ``provider_avatar_id`` carries HeyGen's ``talking_photo_id`` and ``kind`` is
    ``"talking_photo"`` for a creator photo→avatar preset (mirrors
    ``config['kind']``).
    """

    model_config = ConfigDict(extra="allow")

    id: str
    provider: str
    provider_avatar_id: str
    display_name: str = ""
    voice_name: str = ""
    thumbnail_url: str = ""
    kind: str = ""
    is_active: bool = True


class CreateAvatarResponse(BaseResponse):
    data: CreateAvatarData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "id": "b1c2...",
                    "provider": "heygen",
                    "provider_avatar_id": "talking_photo_abc123",
                    "display_name": "My Avatar",
                    "voice_name": "elevenlabs:21m00Tcm4TlvDq8ikWAM",
                    "thumbnail_url": "https://r2.example.com/uploads/abc.png",
                    "kind": "talking_photo",
                    "is_active": True,
                },
            }
        }
    )


######################################################################################################
# ReelForge Brand Voice models (Phase 11 — ElevenLabs Instant Voice Clone)
#
# A creator uploads a short (30-60s) voice sample via the existing
# ``POST /api/v1/uploads/presign`` flow (audio content-type), then passes the
# returned R2 ``key`` as ``sample_key`` here. ElevenLabs Instant Voice Clone
# turns the sample into a private provider voice, selectable as a reel narrator
# via ``voice_name = "elevenlabs:<provider_voice_id>"`` — the format already
# handled by ``app/services/voice.py::tts()``.
#
# CONSENT is mandatory: ``consent`` records the creator's attestation that they
# own or are authorized to use the sampled voice. The controller rejects any
# request without ``consent is True`` (HTTP 400) before doing any provider work.
######################################################################################################


class CloneVoiceRequest(BaseModel):
    """Request body for ``POST /api/v1/voices/clone`` (Phase 11 brand voice).

    ``sample_key`` is the R2 object key of a previously uploaded voice sample
    (via ``POST /api/v1/uploads/presign``). ``consent`` MUST be ``True`` — it
    records the creator's mandatory ownership/authorization attestation.
    """

    name: str = Field(..., min_length=1, max_length=200)
    sample_key: str = Field(..., min_length=1, max_length=512)
    consent: bool = Field(
        ...,
        description="Mandatory attestation that the caller owns/authorizes the voice.",
    )
    description: Optional[str] = Field(default="", max_length=1000)


class VoiceCloneData(BaseModel):
    """Persisted ``UserVoice`` row serialised to the public envelope.

    ``voice_id`` is the narrator selector (``"elevenlabs:<provider_voice_id>"``),
    NOT the internal row id (``id``).
    """

    model_config = ConfigDict(extra="allow")

    id: str
    voice_id: str
    name: str
    status: str = "ready"


class VoiceCloneResponse(BaseResponse):
    data: VoiceCloneData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "id": "b1c2...",
                    "voice_id": "elevenlabs:21m00Tcm4TlvDq8ikWAM",
                    "name": "My Brand Voice",
                    "status": "ready",
                },
            }
        }
    )


class MyVoiceItem(BaseModel):
    """A single cloned voice in the caller's library (``GET /voices/mine``)."""

    model_config = ConfigDict(extra="allow")

    id: str
    voice_id: str
    name: str
    status: str
    created_at: Optional[str] = None


class MyVoicesResponse(BaseResponse):
    data: List[MyVoiceItem] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "b1c2...",
                        "voice_id": "elevenlabs:21m00Tcm4TlvDq8ikWAM",
                        "name": "My Brand Voice",
                        "status": "ready",
                        "created_at": "2026-08-11T10:58:00+00:00",
                    }
                ],
            }
        }
    )


######################################################################################################
# ReelForge billing models (Stripe + iyzico credit purchases)
#
# These back ``app/controllers/v1/billing.py``. Credit packs are locked:
# Free = 3 (signup grant), Starter = 30, Pro = 120. 1 credit = 1 rendered video.
# Response ``data`` models use ``ConfigDict(extra="allow")`` so the billing
# service can attach forward-compatible fields (e.g. ``reference``) without
# breaking the schema — mirroring the ``JobData`` / ``PresignData`` convention.
######################################################################################################

# Payment providers accepted at the checkout boundary. The billing service
# enforces per-provider secret configuration and plan pricing.
SUPPORTED_BILLING_PROVIDERS: frozenset[str] = frozenset(
    {"stripe", "iyzico", "creem", "polar"}
)


class CheckoutRequest(BaseModel):
    """Request body for ``POST /api/v1/billing/checkout``.

    ``provider`` selects the payment rail (Stripe globally, iyzico for TR local
    cards, Creem and Polar as merchant-of-record checkout platforms); ``plan_key``
    selects the credit pack (``"starter"`` | ``"pro"`` — the free plan is a signup
    grant, not a purchase).

    ``workspace_id`` is optional: when present the caller is buying the pack for
    a workspace's SHARED credit pool rather than their personal balance. The API
    layer requires the caller to be an ``admin`` (or higher) of that workspace
    before a checkout session is created, and the id is threaded into the provider
    session metadata so the webhook funds the pool (supported on Stripe, Creem and
    Polar). ``None``/empty means a personal purchase (unchanged behaviour).
    """

    provider: str = Field(..., min_length=1, max_length=32)
    plan_key: str = Field(..., min_length=1, max_length=64)
    workspace_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("workspace_id")
    @classmethod
    def _normalize_workspace_id(cls, value: Optional[str]) -> Optional[str]:
        """Trim ``workspace_id``; collapse empty/whitespace to ``None``.

        A blank string must never be treated as a workspace target (that would
        fund nothing and skip the admin gate), so it is normalised to ``None``
        meaning "personal purchase".
        """
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str) -> str:
        """Normalise the provider id (trim + lower-case).

        Membership is enforced at the controller boundary against
        :data:`SUPPORTED_BILLING_PROVIDERS` so an unknown provider maps to a clean
        ``400`` (rather than a schema-level ``422``); this validator only
        canonicalises the value so ``"Stripe"`` / ``" CREEM "`` resolve correctly.
        """
        return value.strip().lower()

    @field_validator("plan_key")
    @classmethod
    def _validate_plan_key(cls, value: str) -> str:
        """Normalise ``plan_key`` to its stable lower-cased identifier."""
        return value.strip().lower()


class CheckoutData(BaseModel):
    """Hosted-checkout payload returned to the client."""

    model_config = ConfigDict(extra="allow")

    checkout_url: str


class CheckoutResponse(BaseResponse):
    data: CheckoutData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_...",
                },
            }
        }
    )


class Plan(BaseModel):
    """Public description of a purchasable credit plan (§ billing).

    ``credits`` are locked by contract; ``price_usd`` and provider ids may be
    overridden via config. Extra provider fields (``stripe_price_id``,
    ``iyzico_amount``, ``is_purchasable``) are allowed through for clients that
    render them.
    """

    model_config = ConfigDict(extra="allow")

    key: str
    display_name: str
    credits: int
    price_usd: float = 0.0


class PlansResponse(BaseResponse):
    """Public credit-plan catalogue; ``data`` is a list of plans."""

    data: List[Plan]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "key": "free",
                        "display_name": "Free",
                        "credits": 3,
                        "price_usd": 0.0,
                    },
                    {
                        "key": "starter",
                        "display_name": "Starter",
                        "credits": 30,
                        "price_usd": 49.0,
                    },
                    {
                        "key": "pro",
                        "display_name": "Pro",
                        "credits": 120,
                        "price_usd": 149.0,
                    },
                ],
            }
        }
    )


class ProvidersData(BaseModel):
    """Enabled payment providers payload for the checkout UI.

    ``providers`` lists the provider ids (subset of ``stripe`` / ``iyzico`` /
    ``creem`` / ``polar``) whose required secrets are configured, so the client
    renders only the rails that will actually work.
    """

    model_config = ConfigDict(extra="allow")

    providers: List[str]


class ProvidersResponse(BaseResponse):
    """Enabled payment providers; ``data.providers`` is a list of provider ids."""

    data: ProvidersData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {"providers": ["stripe", "iyzico", "creem", "polar"]},
            }
        }
    )


######################################################################################################
# ReelForge growth models (Phase 7): creator insights, referral loop, saved presets
#
# These back ``app/controllers/v1/me.py``. Every ``data`` payload is strictly
# per-caller (the controller scopes each query to the authenticated user). The
# ``*Data`` models use ``ConfigDict(extra="allow")`` so the underlying growth
# services (``insights`` / ``referrals`` / preset repository) can attach
# forward-compatible fields without breaking the schema — mirroring the
# ``MeData`` / ``JobData`` convention.
######################################################################################################


class InsightsData(BaseModel):
    """A single creator's dashboard analytics (scoped to the caller)."""

    model_config = ConfigDict(extra="allow")

    user_id: str
    jobs_total: int = 0
    jobs_by_state: dict[str, int] = Field(default_factory=dict)
    credits_balance: int = 0
    credits_spent: int = 0
    total_cost_usd: float = 0.0
    avg_render_ms: float = 0.0
    videos_generated: int = 0


class InsightsResponse(BaseResponse):
    """``GET /api/v1/me/insights`` — per-user analytics summary."""

    data: InsightsData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "user_id": "b1c2...",
                    "jobs_total": 12,
                    "jobs_by_state": {"complete": 9, "failed": 1, "processing": 2},
                    "credits_balance": 18,
                    "credits_spent": 12,
                    "total_cost_usd": 3.42,
                    "avg_render_ms": 48213.0,
                    "videos_generated": 9,
                },
            }
        }
    )


class AnalyticsData(BaseModel):
    """A single creator's BI analytics dashboard (strictly caller-scoped).

    Mirrors the output of :func:`app.services.analytics.creator_analytics`
    (funnel, cost-over-time, credit burn + live balance, render-time
    percentiles, usage breakdowns and totals) merged with the caller's most-used
    templates/hooks under ``top_content``. ``ConfigDict(extra="allow")`` keeps
    the payload forward-compatible — the service may attach new nested metrics
    without a schema change breaking serialisation.
    """

    model_config = ConfigDict(extra="allow")

    user_id: str
    days: int = 30
    funnel: dict[str, int] = Field(default_factory=dict)
    cost_by_day: list[dict[str, Any]] = Field(default_factory=list)
    credits: dict[str, Any] = Field(default_factory=dict)
    render_time: dict[str, Any] = Field(default_factory=dict)
    by_layout: dict[str, int] = Field(default_factory=dict)
    by_language: dict[str, int] = Field(default_factory=dict)
    by_variants: dict[str, int] = Field(default_factory=dict)
    totals: dict[str, Any] = Field(default_factory=dict)
    top_content: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class AnalyticsResponse(BaseResponse):
    """``GET /api/v1/me/analytics`` — the caller's BI analytics dashboard."""

    data: AnalyticsData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "user_id": "b1c2...",
                    "days": 30,
                    "funnel": {
                        "created": 12,
                        "completed": 9,
                        "failed": 1,
                        "published": 8,
                    },
                    "cost_by_day": [{"date": "2026-08-01", "cost_usd": 0.85}],
                    "credits": {
                        "balance": 50,
                        "spent": 50,
                        "burn_by_day": [{"date": "2026-08-01", "spent": 30}],
                    },
                    "render_time": {
                        "p50_ms": 2000.0,
                        "p90_ms": 4000.0,
                        "avg_ms": 2333.0,
                        "samples": 3,
                    },
                    "by_layout": {"pip": 9, "split": 3},
                    "by_language": {"en": 10, "tr": 2},
                    "by_variants": {"1": 8, "2": 4},
                    "totals": {
                        "jobs_total": 12,
                        "videos_generated": 9,
                        "total_cost_usd": 3.42,
                    },
                    "top_content": {
                        "templates": [{"name": "hook_pov", "count": 5}],
                        "hooks": [{"hook": "5 AI tools", "count": 3}],
                    },
                },
            }
        }
    )


class ReferralData(BaseModel):
    """A user's referral code and lifetime referral performance."""

    model_config = ConfigDict(extra="allow")

    code: str
    referred_count: int = 0
    credits_earned: int = 0


class ReferralResponse(BaseResponse):
    """``GET /api/v1/me/referral`` — the caller's referral code + stats."""

    data: ReferralData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "code": "MFRGGZDF",
                    "referred_count": 3,
                    "credits_earned": 30,
                },
            }
        }
    )


class RedeemRequest(BaseModel):
    """Request body for ``POST /api/v1/me/referral/redeem``.

    ``code`` is another user's referral code. Redemption grants credits to both
    the referrer and the redeeming (referee) user, guarded against self-referral
    and double-redemption by :func:`app.services.referrals.redeem_referral`.
    """

    code: str = Field(..., min_length=1, max_length=32)


class RedeemResponse(BaseResponse):
    """``POST /api/v1/me/referral/redeem`` — redemption result envelope."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "ok": True,
                    "referrer_id": "a0...",
                    "referee_id": "b1...",
                    "referrer_grant": 10,
                    "referee_grant": 5,
                    "referrer_balance": 40,
                    "referee_balance": 8,
                },
            }
        }
    )


class PresetCreateRequest(BaseModel):
    """Request body for ``POST /api/v1/me/presets``.

    Saves a reusable, named wizard/job configuration for the caller. ``config``
    is an opaque JSON map the frontend can spread back onto a create-job payload.
    """

    name: str = Field(..., min_length=1, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)


class PresetData(BaseModel):
    """A saved user preset serialised to the public envelope (caller-scoped)."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class PresetResponse(BaseResponse):
    """``POST /api/v1/me/presets`` — a single saved preset."""

    data: PresetData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "id": "c3d4...",
                    "name": "My POV template",
                    "config": {"layout": "hook_intro", "caption_style": "bold_violet"},
                    "created_at": "2026-08-11T09:26:03+00:00",
                },
            }
        }
    )


class PresetListResponse(BaseResponse):
    """``GET /api/v1/me/presets`` — the caller's saved presets, newest first.

    ``data`` defaults to ``[]`` because the shared ``utils.get_response``
    envelope drops a falsy payload — an empty list must still validate.
    """

    data: List[PresetData] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "c3d4...",
                        "name": "My POV template",
                        "config": {"layout": "hook_intro"},
                        "created_at": "2026-08-11T09:26:03+00:00",
                    }
                ],
            }
        }
    )


class PresetDeleteResponse(BaseResponse):
    """``DELETE /api/v1/me/presets/{id}`` — deletion acknowledgement."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {"deleted": True, "id": "c3d4..."},
            }
        }
    )


######################################################################################################
# ReelForge Brand Watermark (per-user logo overlay applied in the compose stage)
#
# Back ``GET /api/v1/me/brand`` and ``PUT /api/v1/me/brand`` in
# ``app/controllers/v1/brand.py``. A creator uploads a transparent PNG logo via
# the existing ``POST /api/v1/uploads/presign`` (image/png) flow; the resulting
# R2 object ``logo_key`` plus a chosen ``position`` corner + ``opacity`` are
# persisted as the caller's per-user :class:`~app.models.db.models.UserBrand`
# singleton and overlaid on their reels by default.
######################################################################################################


class BrandRequest(BaseModel):
    """Request body for ``PUT /api/v1/me/brand`` (partial update).

    Every field is optional so a caller may update just one setting; an omitted
    (``None``) field leaves the persisted value untouched. Values are validated
    at the controller boundary: ``position`` must be one of the four known
    corners and ``opacity`` must fall in ``[0.0, 1.0]`` (both ``400`` otherwise),
    and a supplied ``logo_key`` must reference an upload the caller owns
    (``403`` otherwise). Passing ``logo_key=""`` clears the watermark logo.
    """

    logo_key: Optional[str] = Field(default=None, max_length=512)
    position: Optional[str] = Field(default=None, max_length=20)
    opacity: Optional[float] = None
    enabled: Optional[bool] = None


class BrandData(BaseModel):
    """The caller's brand watermark settings serialised to the public envelope.

    Mirrors the :class:`~app.models.db.models.UserBrand` column defaults so a
    creator who has never configured a brand still receives a sensible, applied
    watermark shape. ``logo_url`` is a short-lived presigned GET URL for the
    stored logo, present only when a ``logo_key`` is set (``None`` otherwise).
    """

    model_config = ConfigDict(extra="allow")

    logo_key: str = ""
    position: str = "bottom_right"
    opacity: float = 0.85
    enabled: bool = True
    logo_url: Optional[str] = None
    updated_at: Optional[str] = None


class BrandResponse(BaseResponse):
    """``GET``/``PUT`` ``/api/v1/me/brand`` — the caller's brand watermark."""

    data: BrandData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "logo_key": "uploads/9f8e7d.png",
                    "position": "bottom_right",
                    "opacity": 0.85,
                    "enabled": True,
                    "logo_url": "https://r2.example/uploads/9f8e7d.png?X-Amz-...",
                    "updated_at": "2026-08-12T09:26:03+00:00",
                },
            }
        }
    )


######################################################################################################
# ReelForge growth catalogs (Phase 7): job templates + hook browser
#
# Back the read-only ``GET /api/v1/catalog/templates`` and
# ``GET /api/v1/catalog/hooks`` endpoints in ``app/controllers/v1/catalog.py``.
# ``data`` shapes are owned by ``app.services.templates`` (a list of template
# dicts / a language-keyed map of hook lines), so the response ``data`` fields
# stay permissive lists/dicts — mirroring the other catalog response models.
######################################################################################################


class TemplateCatalogResponse(BaseResponse):
    """Job-template catalog; ``data`` is a list of template descriptors.

    Defaults to ``[]`` so a degraded read still validates against the shared
    falsy-dropping ``get_response`` envelope.
    """

    data: List[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "app_demo",
                        "name": "App demo",
                        "description": "Show a product/app in action.",
                        "layout": "pip",
                        "caption_style": "karaoke_yellow",
                        "language": "en",
                        "target_duration_s": 30,
                    }
                ],
            }
        }
    )


class HookCatalogResponse(BaseResponse):
    """Hook browser; ``data`` is a language-keyed map of native hook lines.

    Defaults to ``{}`` so a degraded/empty read still validates against the
    shared falsy-dropping ``get_response`` envelope.
    """

    data: dict[str, List[str]] = Field(default_factory=dict)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "en": ["POV: you finally found the app that..."],
                    "tr": ["Bunu daha önce kimse söylemedi ama..."],
                },
            }
        }
    )


######################################################################################################
# SPARK — AI Idea Engine (Phase 18)
#
# Back the auth-gated idea endpoints in ``app/controllers/v1/ideas.py``:
#   * ``POST /api/v1/ideas/generate`` -> N ready-to-shoot viral UGC concepts
#     (:func:`app.services.ideas.generate_ideas`), rate-limited (LLM tokens).
#   * ``POST/GET/DELETE /api/v1/me/ideas`` -> per-user SAVE / LIST / DELETE of a
#     concept (:class:`app.models.db.repositories.SavedIdeaRepository`).
#
# An "idea" is an opaque, JSON-serialisable concept dict produced by the SPARK
# generator. It is modelled permissively (``extra="allow"``) so the concept
# schema can grow without touching this contract; the known fields are declared
# for docs/validation only.
######################################################################################################


class IdeaData(BaseModel):
    """A single SPARK viral-UGC video concept (permissive; schema may grow).

    ``extra="allow"`` keeps the model forward-compatible with new concept fields
    added by the generator without breaking this response contract.
    """

    model_config = ConfigDict(extra="allow")

    title: str = ""
    hook: str = ""
    angle: str = ""
    format: str = ""
    script_outline: List[str] = Field(default_factory=list)
    suggested_layout: Optional[str] = None
    suggested_caption_style: Optional[str] = None
    language: Optional[str] = None
    est_duration_s: Optional[int] = None


class GenerateIdeasRequest(BaseModel):
    """Request body for ``POST /api/v1/ideas/generate``.

    ``app_context`` describes the creator's app/niche and is required; an empty
    value is rejected with a clean ``400`` at the controller (not a ``422``) so
    the error shape matches the rest of the API. ``count`` is clamped into
    ``[1, 10]`` by the generator regardless of the value supplied here.
    """

    app_context: str = Field(default="", max_length=1000)
    audience: Optional[str] = Field(default="", max_length=300)
    count: Optional[int] = Field(default=6, ge=1, le=10)
    language: Optional[str] = Field(default="auto", max_length=64)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "app_context": "A budgeting app for freelancers in Turkey",
                "audience": "20-35 year old freelancers",
                "count": 6,
                "language": "auto",
            }
        }
    )


class IdeasResponse(BaseResponse):
    """``POST /api/v1/ideas/generate`` — the generated concepts.

    ``data`` defaults to ``[]`` because the shared ``utils.get_response``
    envelope drops a falsy payload — an empty list must still validate.
    """

    data: List[IdeaData] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "title": "POV: freelancer tax panic",
                        "hook": "I almost missed my tax deadline again",
                        "angle": "Relatable pain -> the app is the calm fix",
                        "format": "talking head",
                        "script_outline": [
                            "Open on the panic of an unpaid invoice pile.",
                            "Show the app auto-categorising every expense.",
                            "End relieved: taxes sorted in minutes.",
                        ],
                        "suggested_layout": "hook_intro",
                        "suggested_caption_style": "karaoke_yellow",
                        "language": "en",
                        "est_duration_s": 30,
                    }
                ],
            }
        }
    )


class SaveIdeaRequest(BaseModel):
    """Request body for ``POST /api/v1/me/ideas``.

    ``idea`` is the opaque concept dict to persist for the caller (typically one
    item straight out of ``POST /ideas/generate``). It is stored whole; ``title``
    and ``hook`` are denormalised out of it by the repository for list rendering.
    """

    idea: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "idea": {
                    "title": "POV: freelancer tax panic",
                    "hook": "I almost missed my tax deadline again",
                    "angle": "Relatable pain -> the app is the calm fix",
                    "format": "talking head",
                    "script_outline": ["...", "...", "..."],
                    "suggested_layout": "hook_intro",
                    "suggested_caption_style": "karaoke_yellow",
                    "language": "en",
                    "est_duration_s": 30,
                }
            }
        }
    )


class SavedIdeaData(BaseModel):
    """A saved SPARK concept serialised to the public envelope (caller-scoped)."""

    model_config = ConfigDict(extra="allow")

    id: str
    title: str = ""
    hook: str = ""
    idea: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class SavedIdeasResponse(BaseResponse):
    """``GET /api/v1/me/ideas`` — the caller's saved concepts, newest first.

    ``data`` defaults to ``[]`` because the shared ``utils.get_response``
    envelope drops a falsy payload — an empty list must still validate.
    """

    data: List[SavedIdeaData] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "e5f6...",
                        "title": "POV: freelancer tax panic",
                        "hook": "I almost missed my tax deadline again",
                        "idea": {"title": "POV: freelancer tax panic", "hook": "..."},
                        "created_at": "2026-08-11T09:26:03+00:00",
                    }
                ],
            }
        }
    )


######################################################################################################
# ReelForge Hook Performance Loop (creator-entered outcomes -> win-score ranking)
#
# Back the auth-gated, strictly caller-scoped endpoints in
# ``app/controllers/v1/performance.py``. A creator LOGS the real-world metrics a
# posted reel earned (views/likes/comments/shares/saves + watch-through), one row
# per job; those outcomes are aggregated per HOOK and per TEMPLATE into a
# deterministic "win score" that biases the SPARK idea engine. Fully key-free:
# every metric is self-reported, so all numeric inputs are validated + clamped
# (non-negative counts; ``retention_pct`` in ``[0, 100]``) before they are stored.
######################################################################################################


class LogPerformanceRequest(BaseModel):
    """Request body for ``POST /api/v1/jobs/{job_id}/performance``.

    All fields are optional so a creator can log a partial outcome (e.g. views +
    retention only); an omitted field leaves the stored value untouched on
    re-log. Every numeric field is validated at the controller boundary and
    surfaces a clean ``400`` (not a ``422``) when out of range — counts must be
    non-negative and ``retention_pct`` must lie in ``[0, 100]`` — matching the
    error shape used across the rest of the API. ``platform`` is a short,
    creator-entered persona string (e.g. ``tiktok`` | ``instagram`` | ``youtube``)
    that the repository normalizes/lower-cases and bounds.
    """

    platform: Optional[str] = Field(default=None, max_length=40)
    views: Optional[int] = Field(default=None)
    likes: Optional[int] = Field(default=None)
    comments: Optional[int] = Field(default=None)
    shares: Optional[int] = Field(default=None)
    saves: Optional[int] = Field(default=None)
    retention_pct: Optional[float] = Field(default=None)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "platform": "tiktok",
                "views": 12000,
                "likes": 850,
                "comments": 42,
                "shares": 30,
                "saves": 120,
                "retention_pct": 47.5,
            }
        }
    )


class JobPerformanceModel(BaseModel):
    """One logged reel outcome serialised to its public, caller-scoped envelope."""

    model_config = ConfigDict(extra="allow")

    id: str
    job_id: str
    platform: str = "unknown"
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    retention_pct: float = 0.0
    logged_at: Optional[str] = None
    updated_at: Optional[str] = None


class PerformanceListResponse(BaseResponse):
    """``GET /api/v1/me/performance`` — the caller's logged reel outcomes.

    ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
    drops a falsy payload — an empty list must still validate.
    """

    data: List[JobPerformanceModel] = Field(default_factory=list)


class WinningHookModel(BaseModel):
    """One ranked hook with its deterministic, aggregated win score."""

    model_config = ConfigDict(extra="allow")

    hook: str
    win_score: float = 0.0
    reels: int = 0
    views: int = 0
    engagements: int = 0
    avg_retention_pct: float = 0.0


class WinningTemplateModel(BaseModel):
    """One ranked template with its deterministic, aggregated win score."""

    model_config = ConfigDict(extra="allow")

    template: str
    win_score: float = 0.0
    reels: int = 0
    views: int = 0
    engagements: int = 0
    avg_retention_pct: float = 0.0


class WinningHooksResponse(BaseResponse):
    """``GET /api/v1/me/winning-hooks`` — the caller's top hooks by win score.

    ``data`` defaults to ``[]`` (a creator with no logged outcomes has no
    winners) because the shared envelope drops a falsy payload.
    """

    data: List[WinningHookModel] = Field(default_factory=list)


class WinningTemplatesResponse(BaseResponse):
    """``GET /api/v1/me/winning-templates`` — the caller's top templates by win score.

    ``data`` defaults to ``[]`` (a creator with no logged outcomes has no
    winners) because the shared envelope drops a falsy payload.
    """

    data: List[WinningTemplateModel] = Field(default_factory=list)


######################################################################################################
# ReelForge in-app notifications (bell + unread badge + notification center)
#
# Back the auth-gated endpoints in ``app/controllers/v1/notifications.py`` — the
# in-app counterpart to the external webhook (``app/services/webhooks.py``). The
# server best-effort emits a ``Notification`` row on lifecycle / growth events
# (``job_complete`` / ``job_failed`` / ``low_credits`` / ``referral_earned``) and
# the client renders an unread badge + list. All reads are strictly caller-scoped.
######################################################################################################


class NotificationData(BaseModel):
    """One notification serialised to its public, caller-scoped envelope.

    ``data`` is the opaque, per-event payload (e.g. ``job_id``, ``result_url``,
    ``error``, ``balance``, ``credits``); its shape can grow without a schema
    change, so it stays a permissive JSON map. ``extra="allow"`` future-proofs
    the row shape without forcing a model bump.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    kind: str
    title: str
    body: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    read: bool = False
    created_at: Optional[str] = None


class NotificationsResponse(BaseResponse):
    """``GET /api/v1/me/notifications`` — the caller's notifications + unread count.

    ``data`` is an object carrying the (newest-first) notification list plus the
    caller's live ``unread_count`` so the client can render the list and refresh
    the bell badge from a single call.
    """

    class NotificationsData(BaseModel):
        notifications: List[NotificationData] = Field(default_factory=list)
        unread_count: int = 0

    data: NotificationsData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "notifications": [
                        {
                            "id": "f7a8...",
                            "kind": "job_complete",
                            "title": "Your video is ready",
                            "body": "Your reel has finished rendering.",
                            "data": {"job_id": "9b0c...", "result_url": "https://..."},
                            "read": False,
                            "created_at": "2026-08-11T09:26:03+00:00",
                        }
                    ],
                    "unread_count": 1,
                },
            }
        }
    )


class UnreadCountResponse(BaseResponse):
    """``GET /api/v1/me/notifications/unread_count`` — cheap bell-badge poll.

    A dedicated, count-only endpoint so the client can refresh the unread badge
    on a short interval without materialising any notification rows.
    """

    class UnreadCountData(BaseModel):
        unread_count: int = 0

    data: UnreadCountData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {"unread_count": 3},
            }
        }
    )


######################################################################################################
# ReelForge Scheduled Publishing: queue a finished reel to auto-publish at a
# future UTC time (POST /jobs/{id}/schedule, GET/DELETE /me/scheduled).
######################################################################################################


class ScheduleRequest(BaseModel):
    """Request body for ``POST /api/v1/jobs/{job_id}/schedule``.

    Queues a *completed* job to auto-publish to social platforms at a future UTC
    time. ``platforms`` selects the targets (subset of
    ``tiktok | instagram | youtube_shorts``); ``scheduled_at`` is an ISO-8601 UTC
    timestamp; ``youtube_privacy_status`` optionally overrides YouTube visibility.
    """

    platforms: List[str] = Field(default_factory=list)
    scheduled_at: str = Field(..., min_length=1, max_length=64)
    youtube_privacy_status: Optional[str] = Field(default=None, max_length=32)


class ScheduledData(BaseModel):
    """A single scheduled-publish row serialised to the public envelope.

    ``extra="allow"`` so a partial projection (e.g. the ``POST`` result carrying
    only ``id`` / ``scheduled_at`` / ``status``) still validates, while list rows
    may additionally surface ``job_id`` / ``platforms`` / lifecycle metadata.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    scheduled_at: Optional[str] = None
    status: str = "pending"
    job_id: Optional[str] = None
    platforms: List[str] = Field(default_factory=list)


class ScheduledResponse(BaseResponse):
    """``POST /api/v1/jobs/{job_id}/schedule`` — the created schedule."""

    data: Optional[ScheduledData] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "id": "a1b2...",
                    "scheduled_at": "2026-09-01T12:00:00+00:00",
                    "status": "pending",
                },
            }
        }
    )


class ScheduledListResponse(BaseResponse):
    """``GET /api/v1/me/scheduled`` — the caller's schedules, soonest-due first.

    ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
    drops a falsy payload — an empty list must still validate.
    """

    data: List[ScheduledData] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "a1b2...",
                        "job_id": "j0b1...",
                        "platforms": ["tiktok", "instagram"],
                        "scheduled_at": "2026-09-01T12:00:00+00:00",
                        "status": "pending",
                    }
                ],
            }
        }
    )


######################################################################################################
# ReelForge Cover / Thumbnail Generator models
#
# A creator renders a custom 1080x1920 JPG cover for a reel: the job's poster
# frame (``poster_key``, else a style gradient) with the HOOK overlaid as a bold
# headline in a chosen visual style. The result is uploaded to R2 and its key is
# persisted on ``Job.cover_key``. Regenerable with a different headline/style.
######################################################################################################


class CoverRequest(BaseModel):
    """Request body for ``POST /api/v1/jobs/{job_id}/cover``.

    Both fields are optional. ``headline`` overrides the overlaid text; when
    omitted the controller derives it from the job's script hook (its first
    line) or the job's ``video_subject`` param. ``style`` selects a cover preset
    (see ``GET /api/v1/catalog/cover-styles``); an unknown style is rejected with
    HTTP 400 and an omitted style falls back to the default preset.
    """

    # ``max_length`` matches the renderer's ``_MAX_HEADLINE_CHARS`` cap in
    # ``app/services/cover.py``. Making the schema the authoritative constraint
    # means an over-long headline is rejected with HTTP 422 at the boundary
    # rather than silently truncated after a credit is debited.
    headline: Optional[str] = Field(default=None, max_length=180)
    style: Optional[str] = Field(default=None, max_length=64)


class RankedCoverStyle(BaseModel):
    """One catalog style scored by the cover ranker for the reel's headline.

    ``composite`` is the ranker's tunable score (``stop + 0.5*legibility -
    0.75*generic``); the raw ``stop_power`` / ``legibility`` / ``is_generic``
    signals let a picker explain the ranking. ``scored`` is ``False`` for a
    pass-through (degraded) entry with null signals.
    """

    id: str
    name: str
    composite: float
    stop_power: float
    legibility: float
    is_generic: float
    primary_mood: str = ""
    scored: bool = False


class CoverRecommendation(BaseModel):
    """The auto-pick result surfaced alongside a generated cover.

    ``recommended_style`` is the style the ranker would pick for the headline and
    ``ranked`` is every candidate ordered best-first. ``degraded`` is ``True``
    when no ``TYPESAFE_API_KEY`` is configured (or the ranker failed), in which
    case the recommendation falls back to the deterministic default style.
    """

    recommended_style: str
    degraded: bool
    note: str = ""
    ranked: List[RankedCoverStyle] = Field(default_factory=list)


class CoverData(BaseModel):
    """The generated cover descriptor returned to the client.

    ``cover_key`` is the persisted R2 object key; ``cover_url`` is a presigned
    GET URL the UI can render/download immediately; ``style`` echoes the resolved
    preset id that was rendered. ``auto_selected`` is ``True`` when the style was
    auto-picked by the cover ranker (no explicit style supplied and a live
    recommendation was available); ``recommendation`` carries the full ranked list
    when the ranker ran (``null`` when there was no headline to rank on).
    """

    cover_key: str
    cover_url: str
    style: str
    auto_selected: bool = False
    recommendation: Optional[CoverRecommendation] = None


class CoverResponse(BaseResponse):
    """Envelope for a generated cover (``data`` carries the cover descriptor)."""

    data: CoverData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "cover_key": "jobs/j0b1.../cover.jpg",
                    "cover_url": "https://r2.example.com/jobs/j0b1.../cover.jpg?...",
                    "style": "classic",
                },
            }
        }
    )


class CoverStylesResponse(BaseResponse):
    """Cover-style catalog; ``data`` is a list of ``{id, name}`` descriptors.

    Defaults to ``[]`` so an empty/degraded catalog still validates against the
    shared falsy-dropping ``get_response`` envelope.
    """

    data: List[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [{"id": "classic", "name": "Classic"}],
            }
        }
    )


class MusicGeneratorsResponse(BaseResponse):
    """AI-music generator catalog; ``data`` is a list of enabled providers.

    Each entry is ``{id, name, max_prompt_length}`` for an AI-BGM provider whose
    credentials are configured (``is_enabled()``). Defaults to ``[]`` so a
    deployment with no configured provider still validates against the shared
    falsy-dropping ``get_response`` envelope — the UI hides "Generate with AI"
    when the list is empty.
    """

    data: List[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "elevenlabs",
                        "name": "ElevenLabs",
                        "max_prompt_length": 1000,
                    }
                ],
            }
        }
    )


# =====================================================================================
# Team Workspaces (additive multi-seat membership layer)
# =====================================================================================
class WorkspaceCreateRequest(BaseModel):
    """Request body for ``POST /api/v1/workspaces``.

    ``name`` is intentionally left unconstrained (beyond a length cap) so that an
    empty/whitespace-only value is rejected by the service with a clean HTTP 400
    (mapped from ``ValueError``) rather than a schema-level HTTP 422 — keeping the
    "missing/invalid workspace name" contract in one place (the service).
    """

    name: str = Field(..., max_length=200, description="Human-readable workspace name")


class InviteRequest(BaseModel):
    """Request body for ``POST /api/v1/workspaces/{id}/invite``.

    ``email`` must resolve to an *existing* account (invites never create users);
    an unknown email is rejected with HTTP 400. ``role`` is optional and defaults
    to ``member`` when omitted; an invalid role is rejected with HTTP 400 and a
    role above the caller's own is rejected with HTTP 403.
    """

    email: str = Field(
        ..., max_length=320, description="Email of an existing user to invite"
    )
    role: Optional[str] = Field(
        default=None,
        max_length=20,
        description="owner | admin | member (default: member)",
    )


class RoleRequest(BaseModel):
    """Request body for ``POST /api/v1/workspaces/{id}/members/{user_id}/role``.

    ``role`` is the new role for the target member (``owner | admin | member``);
    an invalid role is rejected with HTTP 400.
    """

    role: str = Field(..., max_length=20, description="owner | admin | member")


class WorkspaceResponse(BaseResponse):
    """Envelope for workspace reads/writes.

    ``data`` carries either a single workspace descriptor (create) or a list of
    them (``GET /api/v1/me/workspaces``); each descriptor includes the caller's
    own ``role`` in that workspace. Typed as ``Any`` so the one model serves both
    the single- and list-shaped payloads under the shared ``get_response``
    envelope.
    """

    data: Any = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "id": "w0rk5p4c3...",
                    "name": "Acme Studio",
                    "owner_id": "u53r...",
                    "role": "owner",
                    "created_at": "2026-08-11T00:00:00+00:00",
                },
            }
        }
    )


class MembersResponse(BaseResponse):
    """Workspace member roster; ``data`` is a list of ``{user_id, email, role,
    created_at}`` descriptors, oldest first (the owner leads).

    Defaults to ``[]`` so an empty/degraded roster still validates against the
    shared falsy-dropping ``get_response`` envelope.
    """

    data: List[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "user_id": "u53r...",
                        "email": "owner@example.com",
                        "role": "owner",
                        "created_at": "2026-08-11T00:00:00+00:00",
                    }
                ],
            }
        }
    )


class WorkspaceGrantRequest(BaseModel):
    """Request body for ``POST /api/v1/workspaces/{id}/credits/grant``.

    ``amount`` is the number of credits to add to the workspace's SHARED pool.
    It is intentionally left unconstrained at the schema level (beyond being an
    ``int``) so a non-positive value is rejected by the repository with a clean
    HTTP 400 (mapped from ``ValueError``) rather than a schema-level HTTP 422 —
    keeping the "invalid grant amount" contract in one place. ``reason`` is an
    optional free-text audit label recorded on the ledger row.

    Note: this is the manual/admin grant path (dev + top-ups). Real purchases
    flow through Stripe in a later phase; this endpoint is the ADMIN-only escape
    hatch for seeding a pool.
    """

    amount: int = Field(..., description="Credits to add to the shared pool")
    reason: Optional[str] = Field(
        default=None, max_length=200, description="Optional audit label for the grant"
    )


class WorkspaceCreditsResponse(BaseResponse):
    """Envelope for a workspace shared-pool credit read / grant.

    ``data`` carries ``{"balance": <int>}`` — the workspace's current shared
    pool balance (``SUM(delta)`` over its ledger rows). Returned by both
    ``GET /api/v1/workspaces/{id}/credits`` and, after a successful grant,
    ``POST /api/v1/workspaces/{id}/credits/grant``.
    """

    data: Any = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {"balance": 100},
            }
        }
    )


# --------------------------------------------------------------------------- #
# Enterprise Access & Governance (Epic 1): RBAC, audit trail, platform admin
# --------------------------------------------------------------------------- #
# These models document the response/request shapes of the governance API
# (``app.controllers.v1.rbac`` / ``audit`` / ``admin``). Responses use the shared
# ``utils.get_response`` envelope (``data`` typed loosely as ``Any`` / ``list`` so
# the falsy-dropping envelope never trips FastAPI's response validation), while
# the per-item models below give the OpenAPI schema its concrete shape.
class MemberRoleModel(BaseModel):
    """One workspace member with their Enterprise role.

    Serialized shape of a :class:`~app.models.db.models.WorkspaceMember` joined to
    its user for the RBAC roster (``GET /api/v1/me/workspaces/{id}/members``).
    ``role`` is one of ``owner | admin | editor | viewer | billing`` (a legacy
    ``member`` may still appear on rows created before the Enterprise vocabulary).
    """

    user_id: str
    email: Optional[str] = None
    role: str
    created_at: Optional[str] = None


class MemberRoleResponse(BaseResponse):
    """Envelope for a single-member role read/change.

    ``data`` is one :class:`MemberRoleModel` descriptor (``{user_id, email, role,
    created_at}``) — returned by ``PATCH /api/v1/me/workspaces/{id}/members/
    {user_id}/role`` after a successful change. Typed as ``Any`` so the
    falsy-dropping ``get_response`` envelope never trips response validation.
    """

    data: Any = None


class RoleUpdateRequest(BaseModel):
    """Request body for ``PATCH /api/v1/me/workspaces/{id}/members/{user_id}/role``.

    ``role`` is the new Enterprise role for the target member
    (``owner | admin | editor | viewer | billing``). An unknown role is rejected
    with HTTP 400; a role above the caller's own rank, or a change that would
    demote the workspace's last ``owner``, is rejected with HTTP 403 / 409.
    """

    role: str = Field(
        ..., max_length=20, description="owner | admin | editor | viewer | billing"
    )


class PermissionsResponse(BaseResponse):
    """Caller's effective permissions in a workspace.

    ``data`` carries ``{"workspace_id", "role", "permissions": [<perm>, ...]}`` —
    the permissions the caller's role grants (direct + inherited) as computed by
    :func:`app.services.rbac.effective_permissions`. ``role`` is ``null`` and
    ``permissions`` empty when the caller is not a member of the workspace (no
    tenant leak).
    """

    data: Any = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "workspace_id": "w0rk5p4c3...",
                    "role": "admin",
                    "permissions": [
                        "jobs.read",
                        "jobs.create",
                        "members.manage",
                        "workspace.settings",
                        "audit.read",
                    ],
                },
            }
        }
    )


class AuditEntryModel(BaseModel):
    """One APPEND-ONLY audit row (Enterprise Access & Governance).

    Serialized shape of an :class:`~app.models.db.models.AuditLog` row for the
    tenant-scoped trail (``GET /api/v1/me/workspaces/{id}/audit``). ``metadata`` is
    the opaque per-event detail (the ORM ``meta`` attribute / DB ``metadata``
    column). The trail is read-only — there is no create/update/delete API here.
    """

    id: int
    workspace_id: Optional[str] = None
    actor_user_id: str
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    ip: Optional[str] = None
    created_at: Optional[str] = None


class AuditResponse(BaseResponse):
    """Envelope for a workspace's audit trail; ``data`` is a list of
    :class:`AuditEntryModel` descriptors, newest first.

    Gated on ``audit.read`` in the target workspace and strictly tenant-scoped, so
    a member of one tenant can never read another tenant's trail. Defaults to
    ``[]`` so an empty trail still validates against the falsy-dropping envelope.
    """

    data: List[dict[str, Any]] = Field(default_factory=list)


class AdminUserModel(BaseModel):
    """A user row in the cross-tenant platform-admin listing (staff-only)."""

    id: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    is_staff: bool = False
    credits: int = 0
    created_at: Optional[str] = None


class AdminWorkspaceModel(BaseModel):
    """A workspace row in the cross-tenant platform-admin listing (staff-only)."""

    id: str
    name: Optional[str] = None
    owner_id: str
    created_at: Optional[str] = None


class AdminJobModel(BaseModel):
    """A job row in the cross-tenant platform-admin listing (staff-only)."""

    id: str
    user_id: str
    kind: Optional[str] = None
    state: Optional[int] = None
    progress: Optional[int] = None
    created_at: Optional[str] = None


class AdminUsersResponse(BaseResponse):
    """Envelope for ``GET /api/v1/admin/users``; ``data`` is a list of
    :class:`AdminUserModel`. Platform-admin (``is_staff``) only — HTTP 403 for a
    non-staff caller, HTTP 401 when unauthenticated."""

    data: List[dict[str, Any]] = Field(default_factory=list)


class AdminWorkspacesResponse(BaseResponse):
    """Envelope for ``GET /api/v1/admin/workspaces``; ``data`` is a list of
    :class:`AdminWorkspaceModel`. Platform-admin (``is_staff``) only."""

    data: List[dict[str, Any]] = Field(default_factory=list)


class AdminJobsResponse(BaseResponse):
    """Envelope for ``GET /api/v1/admin/jobs``; ``data`` is a list of
    :class:`AdminJobModel`. Platform-admin (``is_staff``) only."""

    data: List[dict[str, Any]] = Field(default_factory=list)


class ImpersonateRequest(BaseModel):
    """Request body for ``POST /api/v1/admin/impersonate``.

    ``user_id`` is the target account a platform admin wishes to impersonate. An
    unknown target is rejected with HTTP 400; a non-staff caller with HTTP 403.
    """

    user_id: str = Field(
        ..., max_length=64, description="Target user id to impersonate"
    )


class ImpersonationResponse(BaseResponse):
    """Envelope for a minted, time-boxed impersonation grant (staff-only).

    ``data`` carries the opaque ``token`` plus ``admin_user_id``,
    ``target_user_id``, ``scope``, ``issued_at``, ``expires_at`` and
    ``expires_in`` (seconds). The action is recorded as an append-only
    ``admin.impersonated`` audit row so every impersonation is accountable.
    """

    data: Any = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "token": "S3cr3t-url-safe-token",
                    "admin_user_id": "574ff...",
                    "target_user_id": "u53r...",
                    "scope": "impersonate:u53r...",
                    "issued_at": "2026-08-13T14:00:00+00:00",
                    "expires_at": "2026-08-13T14:15:00+00:00",
                    "expires_in": 900,
                },
            }
        }
    )


# --------------------------------------------------------------------------- #
# AI Social Caption & Hashtags (POST /api/v1/jobs/{job_id}/social)
# --------------------------------------------------------------------------- #
class SocialRequest(BaseModel):
    """Request body for ``POST /api/v1/jobs/{job_id}/social``.

    ``platform`` selects the target social network the copy is tailored for and
    MUST be one of ``tiktok`` / ``instagram`` / ``youtube_shorts`` (validated at
    handler time — a 400 otherwise). ``language`` is optional: when omitted the
    caption is generated in the *job's own* configured language, so a bare
    ``{"platform": "tiktok"}`` body works. The subject/script the copy is built
    from are always derived server-side from the job's persisted data, never from
    client input, so no free-text prompt is accepted here.
    """

    platform: str = Field(..., min_length=1, max_length=32)
    language: Optional[str] = Field(default=None, max_length=64)


class SocialMetadata(BaseModel):
    """The generated post metadata: a ready-to-copy title, caption and hashtags.

    ``hashtags`` is a list of individual tags (each already ``#``-prefixed by the
    generator) the creator can paste when posting; it may be empty when the model
    returns none. ``title`` / ``caption`` may be edited before posting.
    """

    model_config = ConfigDict(extra="allow")

    title: str = ""
    caption: str = ""
    hashtags: List[str] = Field(default_factory=list)


class SocialResponse(BaseResponse):
    """``POST /api/v1/jobs/{job_id}/social`` — generated post copy for a platform."""

    data: SocialMetadata

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "title": "My morning coffee routine that actually works",
                    "caption": "The 3-step routine that changed my mornings. Save this!",
                    "hashtags": ["#coffee", "#morningroutine", "#fyp"],
                },
            }
        }
    )


class ApiKeyCreateRequest(BaseModel):
    """``POST /api/v1/me/api-keys`` body — mint a personal programmatic API key.

    Only a human-friendly ``name`` (label) is accepted so the caller can tell
    their keys apart (e.g. "CI", "n8n", "laptop"). The name is required and
    trimmed/length-capped by the controller; the raw secret is generated
    server-side (never client-supplied) so a caller can never inject a weak key.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Human-friendly label to tell keys apart (e.g. 'CI').",
    )


class ApiKeyCreatedResponse(BaseResponse):
    """``POST /api/v1/me/api-keys`` — the ONE-TIME reveal of a freshly minted key.

    SECURITY: ``key`` is the FULL raw secret and is returned **exactly once**, at
    creation. The server stores only its SHA-256 digest, so the raw value is
    **unrecoverable** afterwards — a lost key must be revoked and re-created. The
    non-secret ``prefix`` is safe to persist/display so the caller can recognise
    the key later (subsequent list calls never return ``key``).
    """

    class ApiKeyCreatedData(BaseModel):
        id: str
        name: str
        key: str = Field(
            ...,
            description=(
                "The FULL raw API key — shown ONCE and unrecoverable. Store it "
                "securely; the server keeps only its SHA-256 hash."
            ),
        )
        prefix: str
        created_at: Optional[str] = None

    data: ApiKeyCreatedData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "id": "a1b2c3d4...",
                    "name": "CI",
                    "key": "rf_Xy7...full-secret-shown-once...",
                    "prefix": "rf_Xy7Kp2Qz",
                    "created_at": "2026-08-12T09:26:03+00:00",
                },
            }
        }
    )


class ApiKeyData(BaseModel):
    """One API key serialised to its public, caller-scoped envelope.

    NEVER carries the raw key or the full hash — only the id, label, non-secret
    ``prefix``, usage/lifecycle metadata, and timestamps are exposed.

    POWER-USER TIER: also surfaces the key's per-minute ``rate_limit_per_min``
    (``null`` = inherit the plan/config default), its ``monthly_quota``
    (``null`` = unlimited), and ``usage_this_month`` — the request count already
    consumed by this key in the current calendar month (0 when unused).
    """

    id: str
    name: str
    prefix: str
    last_used_at: Optional[str] = None
    revoked: bool = False
    created_at: Optional[str] = None
    rate_limit_per_min: Optional[int] = None
    monthly_quota: Optional[int] = None
    usage_this_month: int = 0


class ApiKeyListResponse(BaseResponse):
    """``GET /api/v1/me/api-keys`` — the caller's keys (newest first).

    ``data`` is the list of the caller's keys (active *and* revoked, for a full
    audit view). The raw key and full hash are **never** included — only the
    non-secret ``prefix`` and lifecycle metadata.
    """

    data: List[ApiKeyData] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "a1b2c3d4...",
                        "name": "CI",
                        "prefix": "rf_Xy7Kp2Qz",
                        "last_used_at": "2026-08-12T10:00:00+00:00",
                        "revoked": False,
                        "created_at": "2026-08-12T09:26:03+00:00",
                    }
                ],
            }
        }
    )


class ApiKeyUsageModel(BaseModel):
    """One API key's current-month usage + limits (POWER-USER TIER quotas).

    Caller-scoped. Never carries the raw key or hash — only the id, label,
    non-secret ``prefix``, the ``period_ym`` (``'YYYY-MM'``) the counts apply to,
    the requests ``used`` so far this month, and the key's limits. ``remaining``
    is ``monthly_quota - used`` (floored at 0) or ``null`` when the key has no
    monthly cap (unlimited).
    """

    id: str
    name: str
    prefix: str
    period_ym: str
    used: int = 0
    rate_limit_per_min: Optional[int] = None
    monthly_quota: Optional[int] = None
    remaining: Optional[int] = None


class ApiKeyUsageResponse(BaseResponse):
    """``GET /api/v1/me/api-keys/usage`` — current-month usage for the caller's keys.

    ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
    drops a falsy payload — a caller with no keys must still validate.
    """

    data: List[ApiKeyUsageModel] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "a1b2c3d4...",
                        "name": "CI",
                        "prefix": "rf_Xy7Kp2Qz",
                        "period_ym": "2026-08",
                        "used": 143,
                        "rate_limit_per_min": 60,
                        "monthly_quota": 10000,
                        "remaining": 9857,
                    }
                ],
            }
        }
    )


class SocialPlatformsResponse(BaseResponse):
    """Supported social-platform catalog; ``data`` is a list of ``{id, name}``.

    Defaults to ``[]`` so an empty/degraded catalog still validates against the
    shared falsy-dropping ``get_response`` envelope.
    """

    data: List[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {"id": "tiktok", "name": "TikTok"},
                    {"id": "instagram", "name": "Instagram"},
                    {"id": "youtube_shorts", "name": "YouTube Shorts"},
                ],
            }
        }
    )


######################################################################################################
# ReelForge Template Marketplace (publish / browse / clone / rate)
#
# Back the auth-gated endpoints in ``app/controllers/v1/marketplace.py``. A creator
# publishes an IMMUTABLE snapshot of a private job template (title / description /
# prompt / params / tags / language / layout) to a PUBLIC marketplace; any other
# authenticated user can browse/search it, view its detail, CLONE it into their own
# private templates, and RATE it 1..5 (one rating per user, upserted). Listings are
# owner-scoped for edit/unpublish; browse clamps ``limit`` into ``[1, 100]`` so an
# untrusted page request can never trigger an unbounded scan. Backed by
# ``app.services.marketplace`` over ``MarketplaceRepository`` /
# ``TemplateRatingRepository``.
######################################################################################################


class MarketplaceTemplateModel(BaseModel):
    """A public marketplace listing serialised to its JSON envelope.

    ``params`` is the opaque render-knob snapshot (caption_style, target_duration_s,
    …) copied at publish time, so its shape can grow without a schema bump;
    ``extra="allow"`` future-proofs the row shape (e.g. an optional ``viewer_stars``
    the detail endpoint may attach for the caller's own rating). ``rating_avg`` /
    ``rating_count`` are the denormalised aggregate maintained on each rating upsert.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    author_user_id: str = ""
    title: str = ""
    description: str = ""
    prompt: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    language: str = "en"
    layout: str = ""
    rating_avg: float = 0.0
    rating_count: int = 0
    clone_count: int = 0
    published: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Real-world "proven" performance score, aggregated at query time from the
    # win-scores of the reels made from this listing's clones (see
    # ``app.services.marketplace.listing_win_scores``). ``None`` when the listing
    # has no downstream performance data yet — it is only ever populated on the
    # ``sort='proven'`` browse so the default browse/detail shape is unchanged.
    win_score: Optional[float] = None
    # REMIX TREES (Marketplace Remix Trees). ``parent_template_id`` is the listing
    # this one was remixed from (``None`` for an original publish); ``remix_count``
    # is how many published listings directly descend from this one. Both are safe
    # public provenance fields (never a private/financial datum).
    parent_template_id: Optional[str] = None
    remix_count: int = 0


class MarketplaceListResponse(BaseResponse):
    """``GET /api/v1/marketplace`` — published listings, sorted + paginated.

    ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
    drops a falsy payload — an empty result set must still validate.
    """

    data: List[MarketplaceTemplateModel] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "id": "b1c2d3e4",
                        "author_user_id": "u_9f8e",
                        "title": "3 apps that make you look productive",
                        "description": "Fast-paced listicle roundup",
                        "prompt": "Create a rapid listicle: '3 apps that {subject}'…",
                        "params": {
                            "caption_style": "karaoke_green",
                            "target_duration_s": 35,
                        },
                        "tags": ["listicle", "saas"],
                        "language": "en",
                        "layout": "split",
                        "rating_avg": 4.7,
                        "rating_count": 42,
                        "clone_count": 128,
                        "published": True,
                        "created_at": "2026-08-12T09:26:03+00:00",
                        "updated_at": "2026-08-12T09:26:03+00:00",
                    }
                ],
            }
        }
    )


class MarketplaceTemplateResponse(BaseResponse):
    """``GET /api/v1/marketplace/{id}`` and publish/rate — a single listing."""

    data: MarketplaceTemplateModel

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "id": "b1c2d3e4",
                    "author_user_id": "u_9f8e",
                    "title": "3 apps that make you look productive",
                    "description": "Fast-paced listicle roundup",
                    "prompt": "Create a rapid listicle: '3 apps that {subject}'…",
                    "params": {"caption_style": "karaoke_green"},
                    "tags": ["listicle", "saas"],
                    "language": "en",
                    "layout": "split",
                    "rating_avg": 4.7,
                    "rating_count": 42,
                    "clone_count": 128,
                    "published": True,
                    "created_at": "2026-08-12T09:26:03+00:00",
                    "updated_at": "2026-08-12T09:26:03+00:00",
                },
            }
        }
    )


class PublishTemplateRequest(BaseModel):
    """Request body for ``POST /api/v1/marketplace/publish``.

    Two ways to publish, both owner-scoped:

    * Reference an existing private template via ``template_id`` (a
      :class:`UserPreset` OWNED by the caller) to snapshot its ``name`` + config;
      a foreign/missing id is a clean ``404``. Explicit inline fields override the
      values pulled from the referenced preset.
    * Omit ``template_id`` and pass the snapshot inline. A ``title`` (inline or
      derived from the preset) is required — an empty resolved title is a ``400``.

    The published listing is an IMMUTABLE COPY: a later edit to the source private
    template never mutates the public listing.
    """

    template_id: Optional[str] = Field(default=None, max_length=64)
    title: Optional[str] = Field(default=None, max_length=300)
    description: Optional[str] = Field(default=None, max_length=4000)
    prompt: Optional[str] = Field(default=None, max_length=8000)
    params: Optional[dict[str, Any]] = None
    tags: Optional[List[str]] = None
    language: Optional[str] = Field(default=None, max_length=20)
    layout: Optional[str] = Field(default=None, max_length=40)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "3 apps that make you look productive",
                "description": "Fast-paced listicle roundup",
                "prompt": "Create a rapid listicle: '3 apps that {subject}'…",
                "params": {
                    "caption_style": "karaoke_green",
                    "target_duration_s": 35,
                },
                "tags": ["listicle", "saas"],
                "language": "en",
                "layout": "split",
            }
        }
    )


class RateRequest(BaseModel):
    """Request body for ``POST /api/v1/marketplace/{id}/rate``.

    ``stars`` is a 1..5 rating. Exactly one rating exists per ``(user, template)``
    — re-rating upserts the caller's existing row rather than adding a duplicate.
    A value outside ``[1, 5]`` is rejected by the controller with a clean ``400``
    (matching the rest of the API's error shape) rather than a raw ``422``.
    """

    stars: int = Field(..., description="Rating from 1 to 5 (inclusive)")

    model_config = ConfigDict(json_schema_extra={"example": {"stars": 5}})


class CloneData(BaseModel):
    """The private template created by cloning a marketplace listing."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str = ""
    source_marketplace_id: str = ""


class CloneResponse(BaseResponse):
    """``POST /api/v1/marketplace/{id}/clone`` — the caller's new private template."""

    data: CloneData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "id": "p_1a2b3c",
                    "name": "3 apps that make you look productive",
                    "source_marketplace_id": "b1c2d3e4",
                },
            }
        }
    )


######################################################################################################
# ReelForge Direct-Publish Account-Connect (OAuth)
#
# Back the auth-gated endpoints in ``app/controllers/v1/connections.py``. A creator
# connects a social platform (TikTok / Instagram / YouTube) via OAuth so a finished
# reel can be posted straight to their account. These schemas are the token-free
# public shapes: an access/refresh token is NEVER serialised anywhere — only the
# provider, the provider-side account id, connection status, granted scopes and
# expiry are exposed. Backed by ``app.services.oauth_connect`` over
# ``SocialAccountRepository`` (encrypted-at-rest token blobs).
######################################################################################################


class ConnectionModel(BaseModel):
    """One connected social account serialised to its TOKEN-FREE envelope.

    SECURITY: this shape NEVER carries an access or refresh token (encrypted or
    not). Only the ``provider``, the provider-side ``external_account_id``, the
    connection ``status`` (``connected`` | ``expired``), the granted ``scopes``
    and the timestamps are exposed — enough for a "Connected accounts" UI, and
    nothing a caller could use to impersonate the account. ``connected`` is a
    convenience boolean (always ``True`` for a returned row).
    """

    model_config = ConfigDict(extra="allow")

    provider: str
    external_account_id: str = ""
    connected: bool = True
    status: str = "connected"
    scopes: str = ""
    token_expires_at: Optional[str] = None
    connected_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConnectionListResponse(BaseResponse):
    """``GET /api/v1/me/connections`` — the caller's connected providers (token-free).

    ``data`` defaults to ``[]`` because the shared ``utils.get_response`` envelope
    drops a falsy payload — a caller with no connections must still validate.
    """

    data: List[ConnectionModel] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "provider": "tiktok",
                        "external_account_id": "open_id_abc123",
                        "connected": True,
                        "status": "connected",
                        "scopes": "user.info.basic,video.publish",
                        "token_expires_at": "2026-09-12T09:26:03+00:00",
                        "connected_at": "2026-08-12T09:26:03+00:00",
                        "updated_at": "2026-08-12T09:26:03+00:00",
                    }
                ],
            }
        }
    )


class AuthorizeData(BaseModel):
    """The opaque authorize URL + single-use CSRF state for an OAuth connect."""

    provider: str
    authorize_url: str
    state: str


class AuthorizeResponse(BaseResponse):
    """``GET /api/v1/connections/{provider}/authorize`` — where to send the browser.

    ``state`` is an opaque, single-use CSRF token the caller must echo back on the
    callback; ``authorize_url`` already embeds it. Nothing sensitive is returned.
    """

    data: AuthorizeData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "provider": "tiktok",
                    "authorize_url": (
                        "https://www.tiktok.com/v2/auth/authorize/?client_id=…"
                        "&redirect_uri=…&response_type=code&state=Xy7…&scope=…"
                    ),
                    "state": "Xy7Kp2Qz-opaque-single-use-token",
                },
            }
        }
    )


class PublishResultModel(BaseModel):
    """The outcome of a direct publish to a connected provider (token-free)."""

    model_config = ConfigDict(extra="allow")

    provider: str
    external_post_id: str = ""
    url: str = ""
    status: str = "published"


class PublishResultResponse(BaseResponse):
    """``POST /api/v1/jobs/{id}/publish/{provider}`` — the direct-publish result."""

    data: PublishResultModel

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "provider": "tiktok",
                    "external_post_id": "v0987654321",
                    "url": "https://www.tiktok.com/@creator/video/0987654321",
                    "status": "published",
                },
            }
        }
    )


######################################################################################################
# ReelForge Public Watermarked Share Pages (Share links)
#
# A creator turns one of THEIR OWN completed reels into a public, unguessable,
# revocable share link. The owner-facing ``ShareLinkModel`` carries the token +
# built URL; the PUBLIC ``SharePublicModel`` is a STRICT, safe DTO (NO
# ``extra="allow"``) so a clean ``result_key`` / ``user_id`` / financial can never
# leak even if the service dict grows. Backed by ``app.services.share`` over
# ``ShareLinkRepository``.
######################################################################################################


class ShareLinkModel(BaseModel):
    """Owner-facing share link (data of ``ShareCreateResponse``).

    ``token`` is the unguessable 128-bit public handle and ``url`` is the built
    public share-page link. ``extra="allow"`` future-proofs the owner view (it is
    scoped to the reel's owner, so exposing ``job_id`` / ``view_count`` here is
    safe — this model is NEVER used for the unauthenticated public page).
    """

    model_config = ConfigDict(extra="allow")

    token: str
    url: str
    job_id: str = ""
    view_count: int = 0
    revoked: bool = False
    created_at: Optional[str] = None


class ShareCreateResponse(BaseResponse):
    """``POST /api/v1/jobs/{job_id}/share`` — the created (or existing) link."""

    data: ShareLinkModel

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "token": "kQ2f9zXvA1b3C4d5E6f7Gg",
                    "url": "https://reelforge.app/r/kQ2f9zXvA1b3C4d5E6f7Gg",
                    "job_id": "b1c2d3e4",
                    "view_count": 0,
                    "revoked": False,
                    "created_at": "2026-08-13T12:00:00+00:00",
                },
            }
        }
    )


class SharePublicModel(BaseModel):
    """SAFE public share-page DTO (unauthenticated read).

    STRICT by design — it deliberately does NOT set ``extra="allow"`` so any
    field beyond this safe allowlist is dropped by pydantic, guaranteeing the
    clean ``result_key``, the owning ``user_id`` and every private financial
    (credits, cost, revenue, even ``view_count``) can never leak to a public
    viewer. Mirrors ``app.services.share.SAFE_PUBLIC_FIELDS`` exactly.
    """

    title: str = ""
    watermarked_preview_url: str = ""
    created_at: Optional[str] = None
    sharer_referral_code: str = ""


class SharePublicResponse(BaseResponse):
    """``GET /api/v1/public/r/{token}`` — the safe public share page (no auth)."""

    data: SharePublicModel

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "title": "3 apps that make you look productive",
                    "watermarked_preview_url": "https://r2.example.com/jobs/b1c2/preview.mp4?X-Amz-...",
                    "created_at": "2026-08-13T12:00:00+00:00",
                    "sharer_referral_code": "K7QW2ABC",
                },
            }
        }
    )


class ShareRevokeResponse(BaseResponse):
    """``DELETE /api/v1/me/shares/{token}`` — revoke result."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {"revoked": True, "token": "kQ2f9zXvA1b3C4d5E6f7Gg"},
            }
        }
    )


######################################################################################################
# ReelForge Marketplace Remix Trees (lineage)
#
# Extends the marketplace listing shape with ``parent_template_id`` + ``remix_count``
# (added to ``MarketplaceTemplateModel`` above) and adds a lineage view: the
# ancestors (immediate parent → root) and direct published children of a listing.
# Backed by ``app.services.marketplace.lineage``.
######################################################################################################


class MarketplaceLineageData(BaseModel):
    """The remix-tree lineage of a listing: its ancestors + direct children.

    ``ancestors`` walks UP the ``parent_template_id`` chain (immediate parent
    first → root); ``children`` are the DIRECT, still-published remixes
    (newest-first). Every entry is a safe public ``MarketplaceTemplateModel``.
    """

    model_config = ConfigDict(extra="allow")

    ancestors: List[MarketplaceTemplateModel] = Field(default_factory=list)
    children: List[MarketplaceTemplateModel] = Field(default_factory=list)


class MarketplaceLineageResponse(BaseResponse):
    """``GET /api/v1/marketplace/{id}/lineage`` — ancestors + children."""

    data: MarketplaceLineageData

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "ancestors": [
                        {"id": "root01", "title": "Original listicle", "remix_count": 3}
                    ],
                    "children": [
                        {
                            "id": "child9",
                            "title": "Remixed for SaaS",
                            "parent_template_id": "b1c2d3e4",
                            "remix_count": 0,
                        }
                    ],
                },
            }
        }
    )


######################################################################################################
# ReelForge Creator Profiles + Follow Graph + Leaderboards
#
# Public creator identity + a directed follow graph + a documented, deterministic
# reputation leaderboard. Every public surface exposes ONLY safe fields — the
# profile/leaderboard models are STRICT (no ``extra="allow"``) so a private field
# (credits/email/cost/revenue) can never leak. Backed by ``app.services.creators``.
######################################################################################################

# A public handle is a lowercase ``[a-z0-9]`` slug joined by single hyphens or
# underscores (3..64 chars). Validating the shape at the DTO boundary keeps
# ``/creators/<handle>`` routing unambiguous and rejects path/whitespace payloads.
_HANDLE_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


class CreatorProfileModel(BaseModel):
    """SAFE public creator profile (STRICT — no ``extra="allow"``).

    Contains a creator's public identity (handle / display_name / bio) plus their
    PUBLIC reputation aggregates. It NEVER exposes credits, email, cost/revenue,
    ``user_id`` or any other private field — the strict config drops anything
    outside this allowlist. Mirrors ``app.services.creators.SAFE_PROFILE_FIELDS``.
    """

    handle: str = ""
    display_name: str = ""
    bio: str = ""
    published_template_count: int = 0
    total_clones_received: int = 0
    avg_rating: float = 0.0
    follower_count: int = 0
    following_count: int = 0


class CreatorProfileResponse(BaseResponse):
    """``GET /api/v1/creators/{handle_or_id}`` — a safe public profile."""

    data: CreatorProfileModel

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {
                    "handle": "jane-makes-reels",
                    "display_name": "Jane",
                    "bio": "I make UGC reels for SaaS founders.",
                    "published_template_count": 12,
                    "total_clones_received": 340,
                    "avg_rating": 4.72,
                    "follower_count": 128,
                    "following_count": 20,
                },
            }
        }
    )


class FollowResultModel(BaseModel):
    """Result of a follow / unfollow (safe — only ``following`` state + counts)."""

    model_config = ConfigDict(extra="allow")

    following: bool
    follower_count: int = 0
    removed: Optional[bool] = None


class FollowResponse(BaseResponse):
    """``POST``/``DELETE /api/v1/creators/{id}/follow`` — follow-state envelope."""

    data: FollowResultModel

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": {"following": True, "follower_count": 129},
            }
        }
    )


class FollowingListResponse(BaseResponse):
    """``GET /api/v1/me/following`` — safe public profiles the caller follows."""

    data: List[CreatorProfileModel] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "handle": "jane-makes-reels",
                        "display_name": "Jane",
                        "bio": "",
                        "published_template_count": 12,
                        "total_clones_received": 340,
                        "avg_rating": 4.72,
                        "follower_count": 128,
                        "following_count": 20,
                    }
                ],
            }
        }
    )


class LeaderboardEntryModel(BaseModel):
    """One ranked creator on the leaderboard (STRICT — safe fields only).

    Carries the safe profile aggregates plus the documented, deterministic
    ``reputation_score``, the gaming-resistant ``win_score`` anchor, a 1-based
    ``rank`` and the addressing ``user_id`` / ``handle``. It NEVER exposes
    credits, email, cost/revenue or any other private field.
    """

    user_id: str
    handle: str = ""
    display_name: str = ""
    published_template_count: int = 0
    total_clones_received: int = 0
    avg_rating: float = 0.0
    follower_count: int = 0
    following_count: int = 0
    win_score: float = 0.0
    reputation_score: float = 0.0
    rank: int = 0


class LeaderboardResponse(BaseResponse):
    """``GET /api/v1/creators/leaderboard`` — creators ranked by a metric."""

    data: List[LeaderboardEntryModel] = Field(default_factory=list)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": 200,
                "message": "success",
                "data": [
                    {
                        "user_id": "u_9f8e",
                        "handle": "jane-makes-reels",
                        "display_name": "Jane",
                        "published_template_count": 12,
                        "total_clones_received": 340,
                        "avg_rating": 4.72,
                        "follower_count": 128,
                        "following_count": 20,
                        "win_score": 62.5,
                        "reputation_score": 799.0,
                        "rank": 1,
                    }
                ],
            }
        }
    )


class ProfileUpdateRequest(BaseModel):
    """Request body for ``PATCH /api/v1/me/profile`` (set handle/display_name/bio).

    Every field is optional — only the ones the caller sets are updated. ``handle``
    is normalised to a lowercase slug and validated for shape (a taken handle is a
    clean ``409`` at the controller). All three are safe, public identity fields.
    """

    handle: Optional[str] = Field(default=None, max_length=64)
    display_name: Optional[str] = Field(default=None, max_length=200)
    bio: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("handle")
    @classmethod
    def _validate_handle(cls, value: Optional[str]) -> Optional[str]:
        """Normalise + shape-check a requested public handle.

        ``None`` passes through (handle not being changed). A blank/whitespace
        string is normalised to ``None`` (no change) rather than an empty handle.
        A non-blank handle must be a lowercase ``[a-z0-9]`` slug joined by single
        hyphens/underscores (3..64 chars) so ``/creators/<handle>`` routing stays
        unambiguous and traversal/whitespace payloads are rejected.
        """
        if value is None:
            return None
        handle = value.strip().lower()
        if not handle:
            return None
        if len(handle) < 3 or len(handle) > 64 or not _HANDLE_PATTERN.match(handle):
            raise ValueError(
                "handle must be 3-64 chars, lowercase letters/digits joined by "
                "single hyphens or underscores (e.g. 'jane-makes-reels')"
            )
        return handle


class ProfileUpdateResponse(BaseResponse):
    """``PATCH /api/v1/me/profile`` — the caller's updated public profile."""

    data: CreatorProfileModel


######################################################################################################
# ReelForge ENTERPRISE Identity & SSO (Epic 2) — SAML/OIDC connection, SCIM 2.0,
# and the workspace security policy.
#
# CRITICAL: no response model here EVER serializes a secret. The IdP signing
# certificate (``idp_x509_cert``) and the OIDC client secret are WRITE-ONLY
# request fields, encrypted at rest by ``app.services.crypto_tokens`` — they are
# never echoed back. A minted SCIM bearer token is shown EXACTLY ONCE (on mint)
# and thereafter only its non-secret ``prefix`` is ever returned.
######################################################################################################


class SSOConnectionModel(BaseModel):
    """CERT-FREE public view of a workspace's Enterprise SSO connection.

    The IdP signing certificate and OIDC client secret are NEVER included — only
    ``has_certificate`` / ``has_client_secret`` booleans report whether a secret is
    configured. Safe to return from the admin config surface.
    """

    workspace_id: str
    protocol: str = "saml"
    idp_entity_id: str = ""
    idp_sso_url: str = ""
    sp_acs_url: str = ""
    sp_metadata_url: str = ""
    oidc_client_id: Optional[str] = None
    enabled: bool = False
    has_certificate: bool = False
    has_client_secret: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SSOConnectionResponse(BaseResponse):
    """``GET/PUT /api/v1/me/workspaces/{id}/sso`` — the cert-free connection status.

    ``data`` is ``null`` when the workspace has no SSO connection configured.
    """

    data: Optional[SSOConnectionModel] = None


class SSOConfigRequest(BaseModel):
    """``PUT /api/v1/me/workspaces/{id}/sso`` body — configure the IdP connection.

    ``idp_x509_cert`` (SAML signing cert) and ``oidc_client_secret`` are
    WRITE-ONLY: they are Fernet-encrypted at the service boundary and never
    returned. ``protocol`` must be one of ``saml`` | ``oidc``.
    """

    protocol: str = "saml"
    idp_entity_id: str = Field(default="", max_length=512)
    idp_sso_url: str = Field(default="", max_length=1024)
    idp_x509_cert: str = Field(default="", description="Write-only; never returned")
    sp_acs_url: str = Field(default="", max_length=1024)
    oidc_client_id: str = Field(default="", max_length=512)
    oidc_client_secret: str = Field(
        default="", description="Write-only; never returned"
    )
    enabled: bool = False


class SSOMetadataModel(BaseModel):
    """SP (service-provider) SAML metadata descriptor for a workspace."""

    workspace_id: str
    entity_id: str
    acs_url: str
    metadata_xml: str


class SSOMetadataResponse(BaseResponse):
    """``GET /api/v1/sso/{workspace_id}/metadata`` — the SP metadata (also served raw)."""

    data: SSOMetadataModel


class SSOLoginModel(BaseModel):
    """The SP-initiated login redirect target (the IdP SSO URL with a SAMLRequest)."""

    workspace_id: str
    redirect_url: str


class SSOLoginResponse(BaseResponse):
    """``GET /api/v1/sso/{workspace_id}/login`` — where to send the browser (IdP)."""

    data: SSOLoginModel


class SSOSessionModel(BaseModel):
    """The ReelForge session grant issued after a VALIDATED SAML assertion.

    ``session_token`` is an opaque bearer credential minted by the ACS controller
    from the validated grant — it is never derived from an unsigned/foreign
    assertion (any validation failure is a ``401`` and mints nothing).
    """

    session_token: str
    token_type: str = "Bearer"
    user_id: str
    workspace_id: str
    email: str
    role: str
    is_new_user: bool = False


class SSOSessionResponse(BaseResponse):
    """``POST /api/v1/sso/{workspace_id}/acs`` — the issued session on success."""

    data: SSOSessionModel


class ScimTokenModel(BaseModel):
    """A workspace's SCIM bearer token descriptor.

    The raw ``token`` is populated ONLY in the mint response (shown once, then
    unrecoverable); a listing carries ``token=None`` and only the non-secret
    ``prefix``.
    """

    id: str
    workspace_id: str
    prefix: str = ""
    token: Optional[str] = None
    revoked: bool = False
    last_used_at: Optional[str] = None
    created_at: Optional[str] = None


class ScimTokenCreatedResponse(BaseResponse):
    """``POST /api/v1/me/workspaces/{id}/scim/tokens`` — the freshly minted token.

    The raw ``token`` is present here EXACTLY ONCE; store it now — it can never be
    retrieved again.
    """

    data: ScimTokenModel


class ScimTokenListResponse(BaseResponse):
    """``GET /api/v1/me/workspaces/{id}/scim/tokens`` — the workspace's tokens.

    Never carries a raw token — only ids, prefixes, and status. Defaults to ``[]``.
    """

    data: List[ScimTokenModel] = Field(default_factory=list)


class ScimUserModel(BaseModel):
    """A SCIM 2.0 User resource (as provisioned by an IdP).

    ``extra="allow"`` keeps the model faithful to the SCIM wire shape (camelCase
    keys, ``schemas``, ``meta``) — the SCIM controller returns the service dict
    verbatim under ``application/scim+json``; this model documents the shape.
    """

    model_config = ConfigDict(extra="allow")

    schemas: List[str] = Field(default_factory=list)
    id: str
    externalId: Optional[str] = None
    userName: str = ""
    active: bool = True


class ScimListResponseModel(BaseModel):
    """A SCIM 2.0 ListResponse envelope (used for Users / Groups list)."""

    model_config = ConfigDict(extra="allow")

    schemas: List[str] = Field(default_factory=list)
    totalResults: int = 0
    startIndex: int = 1
    itemsPerPage: int = 0
    Resources: List[dict[str, Any]] = Field(default_factory=list)


class ScimErrorModel(BaseModel):
    """A SCIM 2.0 Error envelope (``schemas``/``status``/``detail``/``scimType``)."""

    model_config = ConfigDict(extra="allow")

    schemas: List[str] = Field(default_factory=list)
    status: str
    detail: Optional[str] = None
    scimType: Optional[str] = None


class SecurityPolicyModel(BaseModel):
    """A workspace's enterprise login security policy (cert-free, no secrets)."""

    workspace_id: str
    require_sso: bool = False
    session_timeout_min: int = 0
    allowed_email_domains: List[str] = Field(default_factory=list)
    mfa_required: bool = False
    ip_allowlist: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SecurityPolicyResponse(BaseResponse):
    """``GET/PUT /api/v1/me/workspaces/{id}/security`` — the workspace policy.

    ``data`` is ``null`` when no policy has been configured yet.
    """

    data: Optional[SecurityPolicyModel] = None


class SecurityPolicyRequest(BaseModel):
    """``PUT /api/v1/me/workspaces/{id}/security`` body — partial policy update.

    Every field is optional; only supplied (non-``None``) fields are applied, so a
    caller can toggle a single rule without resending the whole policy.
    """

    require_sso: Optional[bool] = None
    session_timeout_min: Optional[int] = Field(default=None, ge=0)
    allowed_email_domains: Optional[List[str]] = None
    mfa_required: Optional[bool] = None
    ip_allowlist: Optional[List[str]] = None


######################################################################################################
# ReelForge ENTERPRISE Billing Platform (Epic 3): subscriptions, usage/entitlements, invoices, revenue
#
# These back ``app/controllers/v1/{subscriptions,usage,invoices}.py``. MONEY-CORRECTNESS:
# every amount is an INTEGER minor unit (cents) — no float ever touches money — and every
# read is tenant-scoped (a workspace-scoped model NEVER carries another tenant's rows). The
# platform ``RevenueModel`` is the only cross-tenant view and is served ONLY behind the
# ``is_staff`` gate. Subscription plan/seat/interval limits mirror
# ``app.services.entitlements.PLAN_ENTITLEMENTS`` so entitlement and billing never disagree.
######################################################################################################


# Billing cadence accepted at the subscribe boundary.
SUBSCRIPTION_INTERVALS: frozenset[str] = frozenset({"month", "year"})


class SubscriptionModel(BaseModel):
    """A workspace's billing subscription (tenant-scoped, secret-free).

    ``status`` is one of ``active | past_due | canceled | trialing``; only
    ``active`` / ``trialing`` grant the plan's entitlements (a lapsed subscription
    falls back to the base/free plan). ``provider_ref`` is the provider-side id
    (e.g. the Stripe subscription id) — never a secret.
    """

    workspace_id: str
    plan_key: str = "free"
    provider: str = "stripe"
    provider_ref: str = ""
    status: str = "active"
    interval: str = "month"
    seats: int = 1
    current_period_end: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SubscriptionResponse(BaseResponse):
    """``GET /api/v1/me/workspaces/{id}/subscription`` — the workspace subscription.

    ``data`` is ``null`` when the workspace has no subscription (it then resolves
    to the base/free plan entitlements).
    """

    data: Optional[SubscriptionModel] = None


class SubscribeRequest(BaseModel):
    """``POST /api/v1/me/workspaces/{id}/subscribe`` body — start a recurring checkout.

    ``plan_key`` selects the self-serve plan (``starter`` | ``pro``; Free is the
    implicit base and Enterprise is sales-led). ``interval`` (``month`` | ``year``)
    picks the plan's recurring price for that cadence, ``seats`` (1..plan limit)
    is recorded on the subscription, and ``provider`` is ``stripe`` | ``creem`` |
    ``polar``. No subscription/credit grant happens on this request — the
    verified webhook fulfils it idempotently once the provider confirms payment.
    """

    plan_key: str = Field(..., min_length=1, max_length=64)
    interval: str = Field(default="month", max_length=10)
    seats: int = Field(default=1, ge=1, le=1000)
    provider: str = Field(default="stripe", max_length=32)

    @field_validator("plan_key", "provider")
    @classmethod
    def _normalize_lower(cls, value: str) -> str:
        """Normalise ``plan_key`` / ``provider`` to their stable lower-cased ids."""
        return value.strip().lower()

    @field_validator("interval")
    @classmethod
    def _normalize_interval(cls, value: str) -> str:
        """Normalise the cadence; membership is validated at the controller."""
        return (value or "month").strip().lower() or "month"


class ChangePlanRequest(BaseModel):
    """``POST /api/v1/me/workspaces/{id}/change-plan`` body — switch plan (DB-authoritative)."""

    plan_key: str = Field(..., min_length=1, max_length=64)

    @field_validator("plan_key")
    @classmethod
    def _normalize_plan_key(cls, value: str) -> str:
        return value.strip().lower()


class SubscriptionCheckoutModel(BaseModel):
    """Hosted-checkout payload returned by ``subscribe`` (Stripe checkout url + refs).

    Extra provider fields (``reference``, ``credits``) are allowed through for
    clients that render them. Credits are granted only on webhook confirmation.
    """

    model_config = ConfigDict(extra="allow")

    checkout_url: str
    provider: str = "stripe"
    plan_key: str = ""
    workspace_id: Optional[str] = None


class SubscribeResponse(BaseResponse):
    """``POST /api/v1/me/workspaces/{id}/subscribe`` — the hosted-checkout envelope."""

    data: SubscriptionCheckoutModel


class EntitlementsModel(BaseModel):
    """The caller's active-plan entitlement bundle for a workspace.

    ``entitlements`` is the resolved ``{feature: value}`` map for the workspace's
    LIVE plan (numeric limits like ``max_variants`` / ``seats`` /
    ``monthly_credits`` and boolean capabilities like ``sso`` / ``api_access``). A
    workspace with no live subscription resolves to the base/free plan.
    """

    model_config = ConfigDict(extra="allow")

    workspace_id: str
    plan_key: str = "free"
    entitlements: dict = Field(default_factory=dict)


class EntitlementsResponse(BaseResponse):
    """``GET /api/v1/me/workspaces/{id}/entitlements`` — the caller's plan entitlements."""

    data: EntitlementsModel


class MetricOverageModel(BaseModel):
    """Per-metric usage vs plan limit for a billing period (integer units).

    ``limit`` is ``null`` when the metric is unbounded for the plan; ``overage`` is
    ``max(0, used - limit)`` (0 when within allotment or unbounded).
    """

    metric: str
    used: int = 0
    limit: Optional[int] = None
    overage: int = 0


class UsageModel(BaseModel):
    """A workspace's metered usage + overage for a billing month (tenant-scoped).

    ``usage`` is the per-metric ``{metric: total}`` aggregate for ``period``
    (``'YYYY-MM'``); ``overage`` details each metric's usage vs its plan limit.
    Both are strictly scoped to ``workspace_id`` — never another tenant's rows.
    """

    workspace_id: str
    period: str
    usage: dict = Field(default_factory=dict)
    overage: List[MetricOverageModel] = Field(default_factory=list)


class UsageResponse(BaseResponse):
    """``GET /api/v1/me/workspaces/{id}/usage`` — tenant-scoped usage + overage."""

    data: UsageModel


class InvoiceLineItemModel(BaseModel):
    """One line on an invoice (description + quantity + integer minor-unit amount)."""

    id: str
    description: str = ""
    quantity: int = 1
    amount_cents: int = 0
    created_at: Optional[str] = None


class InvoiceModel(BaseModel):
    """A workspace's invoice (tenant-scoped; integer cents, never a float).

    ``amount_cents`` is the exact integer sum of the invoice's lines in
    ``currency``. ``status`` is one of ``draft | open | paid | void``.
    """

    id: str
    workspace_id: str
    provider_ref: str = ""
    amount_cents: int = 0
    currency: str = "usd"
    status: str = "draft"
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    created_at: Optional[str] = None
    line_items: List[InvoiceLineItemModel] = Field(default_factory=list)


class InvoicesResponse(BaseResponse):
    """``GET /api/v1/me/workspaces/{id}/invoices`` — the workspace's invoices (newest first)."""

    data: List[InvoiceModel] = Field(default_factory=list)


class RevenueModel(BaseModel):
    """Platform revenue summary (cross-tenant; ``is_staff`` ONLY).

    ``revenue_cents`` is the integer sum of realized (``paid``) invoices across all
    tenants since the cutoff; ``credits_granted`` is the outstanding liability side
    (total credits granted); ``net_cents`` mirrors realized revenue.
    """

    revenue_cents: int = 0
    credits_granted: int = 0
    net_cents: int = 0


class RevenueResponse(BaseResponse):
    """``GET /api/v1/admin/revenue`` — platform-wide revenue summary (staff-only)."""

    data: RevenueModel


######################################################################################################
# ReelForge ENTERPRISE API Platform (Epic 4): webhook SUBSCRIPTIONS + developer portal
#
# These back ``app/controllers/v1/{webhooks_admin,developer}.py`` — the customer-facing
# integration surface. A workspace registers a callback ``url`` + the ``event_types`` it wants
# pushed; deliveries ride the EXISTING hardened, HMAC-signed, SSRF-guarded
# ``app.services.webhooks.deliver_webhook`` primitive. SECURITY INVARIANTS mirrored in these
# schemas:
#   * The HMAC signing ``secret`` is returned EXACTLY ONCE (on create) and is NEVER present on
#     any list/get/delivery model — a database or response leak never exposes a usable key.
#   * A subscription ``url`` is SSRF-validated (no loopback/private/link-local/metadata target)
#     before any row is persisted (enforced in the service; the controller maps a rejection to
#     ``400``).
#   * Every webhook model is workspace/tenant-scoped — a model never carries another tenant's row.
######################################################################################################


#: The catalog of event types a subscription may listen for (public API surface).
#: ``job.completed`` fires when a render job finishes; ``job.failed`` when it fails
#: for good (its body carries ``refunded`` / ``charged``, read from the ledgers);
#: ``publish.succeeded`` /
#: ``publish.failed`` when a direct-publish attempt resolves; ``performance.ingested``
#: when a self-reported performance datapoint is logged. A subscribe request whose
#: ``event_types`` are not a subset of this set is a clean ``400`` at the boundary.
WEBHOOK_EVENT_TYPES: tuple[str, ...] = (
    "job.completed",
    "job.failed",
    "publish.succeeded",
    "publish.failed",
    "performance.ingested",
    # Wave Q QM1.5 (U39): OTT channel events (app.domains.ott.events).
    "ott.title.published",
    "ott.purchase.granted",
    "ott.live.started",
)


class WebhookSubscribeRequest(BaseModel):
    """``POST /api/v1/me/workspaces/{id}/webhooks`` body — register a subscription.

    ``url`` is the customer callback endpoint; it is validated through the SAME
    SSRF guard the delivery primitive uses BEFORE any row is persisted, so a
    loopback / private / link-local / metadata target is refused (``400``) and a
    customer can never register an internal URL to SSRF the platform. ``event_types``
    must be a non-empty subset of :data:`WEBHOOK_EVENT_TYPES`. The signing secret is
    minted server-side (never client-supplied) and revealed exactly once in the
    response.
    """

    url: str = Field(
        ...,
        min_length=1,
        description="Customer callback URL (https). SSRF-validated server-side.",
    )
    event_types: List[str] = Field(
        ...,
        min_length=1,
        description=(
            "Event types to receive, e.g. ['job.completed']. Must be a subset of "
            "the supported catalog (WEBHOOK_EVENT_TYPES)."
        ),
    )


class WebhookSubscriptionModel(BaseModel):
    """A webhook subscription serialised to its public, SECRET-FREE envelope.

    NEVER carries the signing secret (plaintext OR the encrypted blob) — only the
    id, owning ``workspace_id``, callback ``url``, subscribed ``event_types``, the
    ``enabled`` kill-switch, and lifecycle timestamps. The plaintext signing secret
    is only ever available once, at create time (see
    :class:`WebhookSubscriptionCreatedModel`).
    """

    id: str
    workspace_id: str
    url: str
    event_types: List[str] = Field(default_factory=list)
    enabled: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class WebhookSubscriptionCreatedModel(WebhookSubscriptionModel):
    """The ONE-TIME reveal returned by ``POST .../webhooks``.

    SECURITY: ``secret`` is the subscription's HMAC signing key and is present
    **only here, exactly once**, at creation. The server persists it only as a
    Fernet blob, so the plaintext is **unrecoverable** afterwards — a lost secret
    means the subscription must be deleted and re-created. Every subsequent
    list/get response uses the secret-free :class:`WebhookSubscriptionModel`.
    """

    secret: str = Field(
        ...,
        description=(
            "The HMAC signing secret — shown ONCE and unrecoverable. Each delivery "
            "is signed Standard Webhooks style: 'webhook-id' (stable across retries), "
            "'webhook-timestamp' (unix seconds, fresh per attempt) and "
            "'webhook-signature: v1,<base64 HMAC-SHA256 of \"{id}.{timestamp}.{body}\">', "
            "keyed with this secret's raw UTF-8 bytes (do not base64-decode it); "
            "reject timestamps more than 5 minutes from your clock. The body-only "
            "'X-Menivor-Signature: sha256=<hexdigest>' header is still sent but "
            "deprecated. Store it securely; the server keeps only an encrypted blob."
        ),
    )


class WebhookSubscriptionCreatedResponse(BaseResponse):
    """``POST /api/v1/me/workspaces/{id}/webhooks`` — the one-time subscription reveal."""

    data: WebhookSubscriptionCreatedModel


class WebhookSubscriptionListResponse(BaseResponse):
    """``GET /api/v1/me/workspaces/{id}/webhooks`` — the workspace's subscriptions.

    ``data`` defaults to ``[]`` (the shared envelope drops a falsy payload) so a
    workspace with no subscriptions still validates. The signing secret is never
    included on any row.
    """

    data: List[WebhookSubscriptionModel] = Field(default_factory=list)


class WebhookDeliveryModel(BaseModel):
    """One delivery attempt-record of an event to a subscription (SECRET-FREE).

    ``status`` is one of ``pending | delivered | failed``. ``attempts`` /
    ``last_attempt_at`` / ``response_code`` reflect the capped-backoff retry state.
    The signed ``payload`` body is intentionally omitted from this summary view;
    only delivery metadata is exposed.
    """

    id: str
    subscription_id: str
    event_type: str
    event_id: str
    status: str = "pending"
    attempts: int = 0
    last_attempt_at: Optional[str] = None
    response_code: Optional[int] = None
    created_at: Optional[str] = None


class WebhookDeliveryResponse(BaseResponse):
    """``POST /api/v1/me/workspaces/{id}/webhooks/{sub}/test`` — the test delivery record."""

    data: WebhookDeliveryModel


class WebhookDeliveryListResponse(BaseResponse):
    """``GET /api/v1/me/workspaces/{id}/webhooks/{sub}/deliveries`` — recent deliveries.

    ``data`` defaults to ``[]`` (newest first). Tenant-scoped: only the owning
    workspace's deliveries are ever returned.
    """

    data: List[WebhookDeliveryModel] = Field(default_factory=list)


class DeveloperApiKeysSummaryModel(BaseModel):
    """The caller's API-key footprint for the developer portal (SECRET-FREE).

    Counts only — never a raw key or hash. ``requests_this_month`` is the sum of
    the current calendar month's request usage across all the caller's keys.
    """

    total: int = 0
    active: int = 0
    period_ym: str = ""
    requests_this_month: int = 0


class DeveloperWebhooksSummaryModel(BaseModel):
    """The caller's webhook-subscription footprint across their workspaces.

    Aggregated across every workspace the caller belongs to (tenant-scoped per
    workspace). ``active`` counts only enabled subscriptions. No secret is exposed.
    """

    total: int = 0
    active: int = 0
    event_types: List[str] = Field(default_factory=lambda: list(WEBHOOK_EVENT_TYPES))


class DeveloperPortalModel(BaseModel):
    """``GET /api/v1/me/developer`` — the caller-scoped API integration portal.

    A READ-only summary: the caller's API-key footprint, their webhook-subscription
    footprint, the number of workspaces they belong to, and static integration
    metadata (base URL, OpenAPI/docs links, API version, supported webhook events).
    Key mint/revoke stays in the API-keys controller; subscription management in the
    webhooks controller — this endpoint only links to them. NEVER carries a secret.
    """

    api_keys: DeveloperApiKeysSummaryModel = Field(
        default_factory=DeveloperApiKeysSummaryModel
    )
    webhooks: DeveloperWebhooksSummaryModel = Field(
        default_factory=DeveloperWebhooksSummaryModel
    )
    workspaces: int = 0
    api_base_url: str = ""
    openapi_url: str = ""
    docs_url: str = ""
    api_version: str = ""
    webhook_event_types: List[str] = Field(
        default_factory=lambda: list(WEBHOOK_EVENT_TYPES)
    )


class DeveloperPortalResponse(BaseResponse):
    """``GET /api/v1/me/developer`` — the caller's developer-portal summary."""

    data: DeveloperPortalModel


# --------------------------------------------------------------------------- #
# ENTERPRISE Compliance (Epic 5) — GDPR data-export / erasure / consent /
# retention. Every ``/me/*`` surface is STRICTLY caller-scoped; the ``/admin/*``
# surface is HARD-GATED on ``User.is_staff`` (Epic 1). See
# ``app/controllers/v1/compliance.py`` + ``admin_compliance.py``.
# --------------------------------------------------------------------------- #
class DataExportModel(BaseModel):
    """The result of a self-service data export (GDPR Art. 15 / 20).

    ``download_url`` is a SHORT-LIVED presigned GET link to the caller's export
    archive (a private R2 object, never public). ``expires_in`` is the link's
    lifetime in seconds. The archive contains ONLY the requesting caller's own
    data — no path can export another user's rows.
    """

    download_url: str = ""
    expires_in: int = 0


class DataExportResponse(BaseResponse):
    """``POST /api/v1/me/data-export`` — a short-lived signed download link."""

    data: DataExportModel


class ErasureRequestModel(BaseModel):
    """A right-to-erasure request's public shape (GDPR Art. 17).

    ``status`` moves ``requested -> processing -> completed``. Erasure ANONYMIZES
    PII in place (email/name/handle tombstoned, credentials revoked, job
    scripts/prompts blanked) while PRESERVING legally-required financial / audit
    records; it never cascade-deletes. ``scope`` records what was erased.
    """

    id: str = ""
    user_id: str = ""
    status: str = "requested"
    scope: str = "user"
    requested_at: Optional[str] = None
    completed_at: Optional[str] = None


class ErasureRequestResponse(BaseResponse):
    """``POST /api/v1/me/erase`` — the caller's own completed erasure request."""

    data: ErasureRequestModel


class ErasureConfirmRequest(BaseModel):
    """Body for ``POST /api/v1/me/erase`` — a deliberate two-factor confirmation.

    Erasure is irreversible, so it requires an explicit ``confirm=true`` step;
    a missing/false confirmation is rejected with HTTP 400 and nothing is erased.
    The route only ever erases the CALLER'S OWN account (no target id is accepted),
    so a user can never erase another account through this surface.
    """

    confirm: bool = Field(
        default=False,
        description="Must be true to proceed; a deliberate irreversible-action gate.",
    )
    confirmation: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional typed confirmation (e.g. the caller's own email).",
    )


class ConsentRecordModel(BaseModel):
    """One append-only consent decision (GDPR / SOC2 consent capture).

    Records that the caller GRANTED or withdrew consent for a ``kind`` (e.g.
    ``tos`` | ``marketing`` | ``ai_disclosure``) at a policy ``version``. Every
    read/write is strictly scoped to the requesting caller.
    """

    id: Optional[int] = None
    kind: str = ""
    granted: bool = False
    version: str = ""
    created_at: Optional[str] = None


class ConsentResponse(BaseResponse):
    """``GET/PUT /api/v1/me/consent`` — the caller's consent trail (or a decision).

    ``GET`` returns the caller's full trail as a list; ``GET?kind=`` returns the
    current (newest) decision for that dimension (nullable); ``PUT`` records a new
    decision and returns it. Always caller-scoped.
    """

    data: Any = None


class ConsentUpdateRequest(BaseModel):
    """Body for ``PUT /api/v1/me/consent`` — record a consent decision.

    ``kind`` is the consent dimension (required); ``granted`` records
    grant/withdrawal; ``version`` is the policy version the decision was made
    against. The decision is always recorded for the CALLER (never another user).
    """

    kind: str = Field(..., min_length=1, max_length=60)
    granted: bool = Field(default=False)
    version: str = Field(default="", max_length=40)


class RetentionPolicyModel(BaseModel):
    """A workspace's data-retention window (GDPR retention).

    ``jobs_retention_days`` / ``assets_retention_days`` bound how long a
    workspace's members' jobs / assets are kept before the periodic sweep
    anonymizes the aged rows. ``None`` means **keep forever** (that dimension is
    never swept). Reading/writing a policy is gated on ``workspace.settings``.
    """

    workspace_id: str = ""
    jobs_retention_days: Optional[int] = None
    assets_retention_days: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RetentionPolicyResponse(BaseResponse):
    """``GET/PUT /api/v1/me/workspaces/{id}/retention`` — a workspace policy."""

    data: RetentionPolicyModel


class RetentionUpdateRequest(BaseModel):
    """Body for ``PUT /api/v1/me/workspaces/{id}/retention`` — set the window.

    A full replace of both windows: ``None`` (or omitted) means **keep forever**
    for that dimension; a negative value is rejected (HTTP 400). Only a workspace
    owner/admin (``workspace.settings``) may set it — a viewer gets HTTP 403.
    """

    jobs_retention_days: Optional[int] = Field(default=None, ge=0)
    assets_retention_days: Optional[int] = Field(default=None, ge=0)


class AdminErasureRequestsResponse(BaseResponse):
    """``GET /api/v1/admin/erasure-requests`` — cross-tenant erasure requests.

    Platform-admin (``is_staff``) ONLY — HTTP 403 for a non-staff caller. ``data``
    is a list of :class:`ErasureRequestModel` across every tenant, newest first.
    """

    data: List[ErasureRequestModel] = Field(default_factory=list)


class AdminRetentionResponse(BaseResponse):
    """``GET /api/v1/admin/retention`` — cross-tenant retention-policy overview.

    Platform-admin (``is_staff``) ONLY. ``data`` is a list of every configured
    :class:`RetentionPolicyModel` so an operator can audit retention posture.
    """

    data: List[RetentionPolicyModel] = Field(default_factory=list)
