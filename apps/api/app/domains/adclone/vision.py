"""Keyframe understanding without a paid model: framing (face size), camera move (frame-to-frame
similarity transform), burned-in caption OCR, and speech transcript. Every heavy dependency is
optional and imported lazily; when one is missing the field degrades to "unknown"/empty and the
brief notes it, so the analysis never crashes on a lean worker.
"""

from __future__ import annotations

from dataclasses import dataclass

# Face height / frame height thresholds for framing.
CLOSE_FACE = 0.22
MEDIUM_FACE = 0.09
ZOOM_EPS = 0.04
PAN_EPS = 0.06


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float
    y_center: float  # 0 = top, 1 = bottom
    x_center: float = 0.5  # 0 = left, 1 = right (tracks text that moves with a subject)


def framing_from_face(face_h_ratio: float | None) -> str:
    if face_h_ratio is None:
        return "wide"
    if face_h_ratio >= CLOSE_FACE:
        return "close"
    if face_h_ratio >= MEDIUM_FACE:
        return "medium"
    return "wide"


def camera_move_from_transform(scale: float | None, dx_ratio: float | None) -> str:
    if scale is None or dx_ratio is None:
        return "unknown"
    if scale > 1 + ZOOM_EPS:
        return "push_in"
    if scale < 1 - ZOOM_EPS:
        return "pull_out"
    if abs(dx_ratio) > PAN_EPS:
        return "pan"
    return "static"


def _vision_face_ratio(image_path: str) -> float | None:
    """macOS Vision face rectangles (pyobjc), heights are already normalised to 0..1."""
    try:
        import Vision  # noqa: PLC0415
        from Foundation import NSURL  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(image_path), None)
    req = Vision.VNDetectFaceRectanglesRequest.alloc().init()
    ok, _err = handler.performRequests_error_([req], None)
    if not ok:
        return None
    heights = [float(r.boundingBox().size.height) for r in (req.results() or [])]
    return round(max(heights), 4) if heights else None


def largest_face_ratio(image_path: str) -> float | None:
    """Height of the largest detected face over the frame height (None: no face / no detector)."""
    try:
        import cv2  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return _vision_face_ratio(image_path)
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV 5 moved Haar cascades out of the main package
        return _vision_face_ratio(image_path)
    img = cv2.imread(image_path)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    best = 0
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
        for _x, _y, _w, h in faces:
            best = max(best, int(h))
    return round(best / gray.shape[0], 4) if best else None


def similarity(first_path: str, last_path: str) -> tuple[float | None, float | None]:
    """(scale, dx/width) of the partial-affine transform first->last frame, from ORB matches."""
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None, None
    a, b = cv2.imread(first_path, 0), cv2.imread(last_path, 0)
    if a is None or b is None:
        return None, None
    orb = cv2.ORB_create(800)
    ka, da = orb.detectAndCompute(a, None)
    kb, db = orb.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < 12 or len(kb) < 12:
        return None, None
    matches = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db), key=lambda m: m.distance)[:200]
    if len(matches) < 12:
        return None, None
    src = np.float32([ka[m.queryIdx].pt for m in matches])
    dst = np.float32([kb[m.trainIdx].pt for m in matches])
    m, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC)
    if m is None:
        return None, None
    scale = float((m[0, 0] ** 2 + m[1, 0] ** 2) ** 0.5)
    return round(scale, 4), round(float(m[0, 2]) / a.shape[1], 4)


_RAPID: list = []  # one RapidOCR engine per process (model load is the slow part)


def _rapidocr(image_path: str) -> list[OcrLine] | None:
    """RapidOCR (ONNX, Apache-2.0, pip-only): the Linux worker's OCR. None when not installed."""
    try:
        from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    if not _RAPID:
        _RAPID.append(RapidOCR())
    result, _elapsed = _RAPID[0](image_path)
    size = Image.open(image_path).size
    width, height = (size[0] or 1), (size[1] or 1)
    out = []
    for box, text, score in result or []:
        ys = [float(p[1]) for p in box]
        xs = [float(p[0]) for p in box]
        if str(text).strip():
            out.append(OcrLine(str(text).strip(), float(score), round(sum(ys) / len(ys) / height, 3),
                               round(sum(xs) / len(xs) / width, 3)))
    return out


def ocr_image(image_path: str) -> list[OcrLine] | None:
    """Burned-in text on a frame: macOS Vision (ocrmac), else RapidOCR (Linux workers), else Tesseract;
    None = no OCR engine installed."""
    try:
        from ocrmac import ocrmac  # noqa: PLC0415

        rows = ocrmac.OCR(image_path).recognize()
        # ocrmac boxes are (x, y_from_bottom, w, h) in 0..1
        return [OcrLine(t.strip(), float(c), round(1 - (box[1] + box[3] / 2), 3), round(box[0] + box[2] / 2, 3))
                for t, c, box in rows if t.strip()]
    except Exception:  # noqa: BLE001 - try the next engine
        pass
    rapid = _rapidocr(image_path)
    if rapid is not None:
        return rapid
    try:
        import pytesseract  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        img = Image.open(image_path)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        lines: dict[tuple, list] = {}
        for i, word in enumerate(data["text"]):
            if word.strip() and float(data["conf"][i]) > 50:
                key = (data["block_num"][i], data["line_num"][i])
                lines.setdefault(key, []).append((word, data["top"][i] + data["height"][i] / 2,
                                                  data["left"][i] + data["width"][i] / 2))
        return [OcrLine(" ".join(w for w, _, _ in ws), 0.8, round(sum(y for _, y, _ in ws) / len(ws) / img.height, 3),
                        round(sum(x for _, _, x in ws) / len(ws) / img.width, 3))
                for ws in lines.values()]
    except Exception:  # noqa: BLE001
        return None


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float
    text: str


MULTILINGUAL_MODELS = ("small", "base", "medium")
_NO_LANGUAGE = {"", "original", "auto", "none"}


def whisper_model_name(env: dict | None = None) -> str:
    """The multilingual model to download: ``ADCLONE_WHISPER_MODEL`` without any English-only ``.en``."""
    import os  # noqa: PLC0415

    raw = str((os.environ if env is None else env).get("ADCLONE_WHISPER_MODEL") or "small").strip()
    return raw[:-3] if raw.endswith(".en") else raw


def transcribe(path: str, language: str | None = None) -> tuple[list[Segment], str] | None:
    """Local faster-whisper (MIT; base dependency), multilingual models only.

    English-only ``*.en`` models turn non-English speech (a Turkish ad) into English nonsense, so
    they are never used, even when they are the only cached ones. ``language`` (an ISO code from the
    brief or the clone options) is passed through; ``None`` / ``"original"`` lets Whisper detect it.
    A missing model is fetched once (free, Hugging Face) unless ADCLONE_WHISPER_DOWNLOAD=0.
    None when unavailable."""
    import os  # noqa: PLC0415

    try:
        from faster_whisper import WhisperModel  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    wanted = whisper_model_name()
    model = None
    for name in dict.fromkeys((wanted, *MULTILINGUAL_MODELS)):
        try:
            model = WhisperModel(name, device="cpu", compute_type="int8", local_files_only=True)
            break
        except Exception:  # noqa: BLE001 - model not cached, try the next one
            model = None
    if model is None and os.getenv("ADCLONE_WHISPER_DOWNLOAD", "1").strip() not in ("0", "false", "no"):
        try:
            model = WhisperModel(wanted, device="cpu", compute_type="int8")
        except Exception:  # noqa: BLE001 - offline worker
            model = None
    if model is None:
        return None
    lang = (language or "").strip().lower()
    lang = None if lang in _NO_LANGUAGE else lang.split("-")[0]
    segs, info = model.transcribe(path, language=lang, vad_filter=True)
    out = [Segment(round(s.start, 2), round(s.end, 2), s.text.strip()) for s in segs if s.text.strip()]
    return out, str(getattr(info, "language", "") or lang or "en")
