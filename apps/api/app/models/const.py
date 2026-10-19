PUNCTUATIONS = [
    "?",
    ",",
    ".",
    "、",
    ";",
    ":",
    "!",
    "…",
    "？",
    "，",
    "。",
    "、",
    "；",
    "：",
    "！",
    "...",
    # 阿拉伯语常用标点也应作为自然断句点，避免脚本文本和 edge-tts
    # 返回的字幕停顿边界不一致，导致后续逐行匹配失败。
    "،",
    "؛",
    "؟",
]

TASK_STATE_FAILED = -1
TASK_STATE_COMPLETE = 1
TASK_STATE_PROCESSING = 4

# ReelForge per-stage status strings (JobEvent.status / Job.stages values).
REELFORGE_STAGE_PENDING = "pending"
REELFORGE_STAGE_RUNNING = "running"
REELFORGE_STAGE_COMPLETE = "complete"
REELFORGE_STAGE_FAILED = "failed"

# ReelForge canonical DAG: stage -> upstream dependencies.
# script -> tts -> {avatar ∥ captions} -> compose -> upload.
REELFORGE_DAG: dict[str, tuple[str, ...]] = {
    "script": (),
    "tts": ("script",),
    "avatar": ("tts",),
    "captions": ("tts",),
    "compose": ("avatar", "captions"),
    "upload": ("compose",),
}

# Relative progress weight per stage. Upload weight is excluded from the
# denominator when a job requests no publishing platforms (§6 progress rule).
REELFORGE_STAGE_WEIGHTS: dict[str, int] = {
    "script": 10,
    "tts": 20,
    "avatar": 30,
    "captions": 15,
    "compose": 20,
    "upload": 5,
}

CROSS_POST_STATE_PENDING = "pending"
CROSS_POST_STATE_PROCESSING = "processing"
CROSS_POST_STATE_COMPLETE = "complete"
CROSS_POST_STATE_FAILED = "failed"

FILE_TYPE_VIDEOS = ["mp4", "mov", "mkv", "webm"]
FILE_TYPE_IMAGES = ["jpg", "jpeg", "png", "bmp"]
