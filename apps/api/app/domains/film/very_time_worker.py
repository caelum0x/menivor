"""Very ___ Time worker steps (preset ``very-time``), called from the shared story8 workers.

What runs here and not in the story8 path:

* **Identity and garment references.** The identity reference is the character's
  turnaround sheet (or its first reference), else the built-in brand's sheet
  (Oxhan), else a host sheet generated once for the job (house-paid). The garment
  reference is the user's uploaded garment photo, else the brand's garment.
  Stills are made on a reference-taking image model with both, role-tagged; shots
  get them as ``identity`` / ``garment`` references next to the first frame.
* **Chest-text check.** Every still whose prompt carries the chest text is read
  with OCR (``chest_check``); a misspelling is re-rolled up to the job's
  ``chest_rerolls`` cap (house-paid, never charged to the user; the cap is fixed
  at start and shown in the plan), then the text is overlaid cleanly.
* **Payoff.** Animated jobs: ``native`` keeps the shot's own speech when it is
  there; otherwise (or with ``lipsync``) the chosen voice take is lip-synced onto
  the payoff shot (MuseTalk or the Replicate lane); otherwise the take is laid
  over as a voice-over. The video uses the chosen take, never a fresh narration.
* **Sound.** Per-beat sound effects (ElevenLabs or the Replicate lane), the
  shots' own audio as room tone when asked, ducked under the voice and mastered
  to -14 LUFS / -1.5 dBTP.
* **Length and end card.** Beats fill the chosen length minus the end card; the
  closing caption runs from the payoff beat to the end card; the end card shows
  the brand logo and call to action; the output is exactly ``duration_s`` long.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from loguru import logger

from . import story8, story8_render as render

LIPSYNC_TIMEOUT_S = 8 * 60
SPEECH_LEAD_S = 0.2
_IMAGE_ROLES = {
    "identity": "Image {n} is the character turnaround sheet: it controls only the face, hair, skin tone, "
                "build and the shirt; do not copy its background, its panel layout or its pose.",
    "garment": "Image {n} shows the garment: copy its cut, colour, fabric and chest print exactly; "
               "ignore its background and anyone wearing it.",
}


# --------------------------------------------------------------------------- #
# Default lanes (real services); tests inject their own
# --------------------------------------------------------------------------- #
def presign(key: str) -> str:
    from app.platform.storage.r2 import get_r2_client

    return get_r2_client().presign_get(key, expires=3600)


def ref_image(prompt: str, negative: str, seed: int, reference_urls: Sequence[str], model: str) -> bytes:
    from app.domains.gateway.house_image import house_image

    return house_image(prompt, model_id=model, reference_urls=tuple(reference_urls),
                       correlation_id=f"very-time-{seed}", negative=negative)


def text_image(prompt: str, negative: str, seed: int, model: str) -> bytes:
    from app.domains.gateway.house_image import house_image

    return house_image(prompt, model_id=model, correlation_id=f"very-time-{seed}", negative=negative)


def voice_take(*, params: Mapping[str, Any], user_id: str, work: str, fetch: Callable[[str], bytes],
               max_seconds: float | None) -> tuple[str, float, str]:
    from . import very_time_voice

    voice = dict(params.get("voice") or {})
    line, reply = str(params.get("line") or ""), str(params.get("reply_line") or "")
    return very_time_voice.take_for_job(
        take_key=voice.get("take_key") or None, user_id=user_id, line=line, reply_line=reply,
        engine=str(voice.get("engine") or "free"), delivery=str(voice.get("delivery") or "deadpan"),
        language=str(params.get("language") or ""), work_dir=work, fetch=fetch, max_seconds=max_seconds)


def make_sfx(backend: str, prompt: str, seconds: float, out_path: str, *, clip_url: str = "",
             image_url: str = "") -> str:
    if backend == "elevenlabs":
        from app.services.audio.sfx_elevenlabs import generate_sfx

        return generate_sfx(prompt, seconds=max(0.5, min(30.0, seconds)), out_path=out_path)
    if backend == "replicate":
        from app.services.audio.sfx_replicate import generate_sfx

        return generate_sfx(prompt, seconds=seconds, out_path=out_path, video_url=clip_url, image_url=image_url)
    raise RuntimeError("no sound-effects lane")


def lipsync_submit(backend: str, *, image_url: str, video_url: str, audio_url: str, correlation_id: str
                   ) -> dict[str, Any]:
    if backend == "musetalk":
        from . import very_time_payoff

        return dict(very_time_payoff.submit_lipsync(image_url=image_url, audio_url=audio_url,
                                                    correlation_id=correlation_id))
    if backend == "replicate":
        from app.domains.routing.providers import replicate_lipsync

        return dict(replicate_lipsync.submit(video_url, audio_url, correlation_id))
    raise RuntimeError("no lip-sync lane")


def lipsync_poll(run: Mapping[str, Any]) -> tuple[str, str]:
    if run.get("provider") == "musetalk":
        from . import very_time_payoff

        return very_time_payoff.poll_lipsync(run)
    from app.domains.routing.providers import replicate_lipsync

    return replicate_lipsync.poll(run)


def speech_present(path: str) -> bool:
    from . import very_time_payoff

    return very_time_payoff.speech_present(path)


@dataclass
class VtDeps:
    presign: Callable[[str], str] = presign
    ref_image: Callable[[str, str, int, Sequence[str], str], bytes] = ref_image
    text_image: Callable[[str, str, int, str], bytes] = text_image
    ocr: Callable[[bytes], list] | None = None  # None: the real RapidOCR reader
    voice_take: Callable[..., tuple[str, float, str]] = voice_take
    make_sfx: Callable[..., str] = make_sfx
    lipsync_submit: Callable[..., dict[str, Any]] = lipsync_submit
    lipsync_poll: Callable[[Mapping[str, Any]], tuple[str, str]] = lipsync_poll
    speech_present: Callable[[str], bool] = speech_present
    download: Callable[[str], bytes] | None = None  # None: the story8 downloader


def is_very_time(job_or_params: Any) -> bool:
    return story8.job_preset_id(job_or_params) == "very-time"


def _vt(deps: Any) -> VtDeps:
    return getattr(deps, "very_time", None) or VtDeps()


def _save(job: Any, **changes: Any) -> None:
    job.params = {**dict(job.params or {}), **changes}


# --------------------------------------------------------------------------- #
# References: identity sheet + garment
# --------------------------------------------------------------------------- #
def brand_asset(params: Mapping[str, Any], asset: str, deps: Any) -> str | None:
    """Upload a built-in brand asset once per job run and return its server key."""
    from . import very_time

    name = str((params.get("brand") or {}).get("preset") or "")
    path, key = very_time.brand_asset_path(name, asset), very_time.brand_asset_key(name, asset)
    if path is None or key is None:
        return None
    content = "image/png" if path.suffix == ".png" else "image/jpeg"
    deps.upload(str(path), key, content)
    return key


def _sheet_prompt(params: Mapping[str, Any]) -> tuple[str, str]:
    from app.domains.characters.turnaround import sheet_prompt

    from . import very_time

    data = very_time.preset()
    look = (data.get("looks") or {}).get(str(params.get("look") or ""), {})
    brand = dict(params.get("brand") or {})
    wearing = f'{brand.get("garment") or ""}, the chest text reading "{brand.get("chest_text") or ""}"'
    return sheet_prompt([str(data["host"])], style=str(look.get("style") or ""), wearing=wearing)


def identity_key(job: Any, work: str, deps: Any) -> str | None:
    """Character sheet > brand sheet > a host sheet generated for this job (when a reference lane is live)."""
    params = dict(job.params or {})
    for key in (params.get("_sheet_key"), params.get("character_ref")):
        if key:
            return str(key)
    key = brand_asset(params, "sheet", deps)
    model = str(params.get("reference_image_model") or "")
    if key is None and model:
        garment = garment_key(job, deps)
        refs = [_vt(deps).presign(garment)] if garment else []
        prompt, negative = _sheet_prompt(params)
        try:
            image = _vt(deps).ref_image(prompt, negative, 7, refs, model) if refs else \
                _vt(deps).text_image(prompt, negative, 7, str(params.get("image_model") or model))
        except Exception as exc:  # noqa: BLE001 - no sheet: frames fall back to prompt-only identity
            logger.warning(f"very-time {job.id}: host sheet not made ({exc})")
            return None
        path = os.path.join(work, "sheet.png")
        with open(path, "wb") as fh:
            fh.write(_fit(image, (1536, 1024)))
        key = f"jobs/{job.id}/story8/sheet.png"
        deps.upload(path, key, "image/png")
    if key:
        _save(job, _sheet_key=key)
    return key


def garment_key(job: Any, deps: Any) -> str | None:
    params = dict(job.params or {})
    ref = (params.get("brand") or {}).get("garment_ref")
    if ref:
        return str(ref)
    if params.get("_garment_key"):
        return str(params["_garment_key"])
    key = brand_asset(params, "garment", deps)
    if key:
        _save(job, _garment_key=key)
    return key


def _fit(image: bytes, size: tuple[int, int]) -> bytes:
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(image)) as source:
        out = io.BytesIO()
        ImageOps.fit(source.convert("RGB"), size, Image.LANCZOS).save(out, format="PNG")
        return out.getvalue()


def _role_prompt(prompt: str, roles: Sequence[str]) -> str:
    lines = [_IMAGE_ROLES[r].format(n=i) for i, r in enumerate(roles, start=1) if r in _IMAGE_ROLES]
    return " ".join([*lines, prompt]) if lines else prompt


# --------------------------------------------------------------------------- #
# Frames with references and the chest-text check
# --------------------------------------------------------------------------- #
def frame_lane(job: Any, work: str, deps: Any) -> Callable[[str, str, int], bytes]:
    """``(prompt, negative, seed) -> bytes`` for this job: reference model with identity + garment when
    both a reference lane and references exist; otherwise the text image model (or the injected lane)."""
    params = dict(job.params or {})
    refs: list[tuple[str, str]] = []
    identity = identity_key(job, work, deps)
    if identity:
        refs.append(("identity", identity))
    garment = garment_key(job, deps)
    if garment:
        refs.append(("garment", garment))
    model = str(params.get("reference_image_model") or "")
    vt = _vt(deps)
    if refs and model:
        urls = [vt.presign(key) for _, key in refs]
        roles = [role for role, _ in refs]
        return lambda prompt, negative, seed: vt.ref_image(_role_prompt(prompt, roles), negative, seed, urls, model)
    from .story8_tasks import house_frame_image

    if deps.frame_image is not house_frame_image:
        return deps.frame_image  # an injected lane (tests, other callers)
    image_model = str(params.get("image_model") or story8.job_preset(job)["frame_model"])
    return lambda prompt, negative, seed: vt.text_image(prompt, negative, seed, image_model)


def make_frames(session: Any, job: Any, work: str, deps: Any, fit_frame: Callable[[bytes], bytes]
                ) -> list[dict[str, Any]]:
    from . import chest_check

    params = dict(job.params or {})
    frames = [dict(f) for f in params.get("frames") or []]
    lane = frame_lane(job, work, deps)
    expected = str((params.get("brand") or {}).get("chest_text") or "")
    cap = int(params.get("chest_rerolls") if params.get("chest_rerolls") is not None else 2)
    for frame in frames:
        if frame.get("key"):
            continue

        def generate(seed: int, frame: dict[str, Any] = frame) -> bytes:
            return fit_frame(lane(frame["prompt"], frame.get("negative", ""), seed))

        if frame.get("chest") and expected:
            result = chest_check.verify_chest(generate, expected=expected, seed=int(frame["seed"]),
                                              max_rerolls=cap, ocr=_vt(deps).ocr,
                                              region=tuple(frame.get("chest_region") or (0.5, 0.55)))
            image = result.image
            frame["chest_check"] = {"status": result.status, "attempts": result.attempts, "read": result.read[:80]}
            frame["seed"] = result.seed
        else:
            image = generate(int(frame["seed"]))
        path = os.path.join(work, f"frame-{frame['index'] + 1}.png")
        with open(path, "wb") as fh:
            fh.write(image)
        key = f"jobs/{job.id}/story8/frame-{frame['index'] + 1}.png"
        deps.upload(path, key, "image/png")
        frame["key"] = key
    return frames


def shot_references(job: Any, frame: Mapping[str, Any], deps: Any) -> list[dict[str, str]]:
    """First frame, identity sheet, garment: the multi-reference contract for one shot."""
    refs = [{"key": str(frame["key"]), "role": "first_frame"}]
    params = dict(job.params or {})
    identity = params.get("_sheet_key") or params.get("character_ref")
    if identity:
        refs.append({"key": str(identity), "role": "identity"})
    garment = (params.get("brand") or {}).get("garment_ref") or params.get("_garment_key")
    if garment:
        refs.append({"key": str(garment), "role": "garment"})
    return refs


def shot_generate_audio(params: Mapping[str, Any], frame: Mapping[str, Any]) -> bool:
    """Ask the model for its own audio only where it is used (room tone, native speech, sound effects)."""
    sound = dict(params.get("sound") or {})
    speaking = bool(str(frame.get("line") or "").strip())
    return bool(sound.get("room_tone") or (speaking and params.get("payoff") == "native"))


# --------------------------------------------------------------------------- #
# Payoff: native speech, lip-sync, or voice-over (animated jobs, before finish)
# --------------------------------------------------------------------------- #
def _speaking_index(frames: Sequence[Mapping[str, Any]]) -> int | None:
    for frame in sorted(frames, key=lambda f: int(f["index"])):
        if str(frame.get("line") or "").strip():
            return int(frame["index"])
    return None


def payoff_stage(session: Any, job: Any, work: str, deps: Any, clips: dict[int, str]) -> str:
    """``"wait"`` while a lip-sync run is in flight, else ``"done"`` with ``_payoff_used`` set.

    The chosen voice take is fixed here once (``_take_key`` / ``_vo_key``) so the
    lip-sync and the final mix use the same take."""
    params = dict(job.params or {})
    frames = [dict(f) for f in params.get("frames") or []]
    index = _speaking_index(frames)
    mode = str(params.get("payoff") or "voiceover")
    if index is None:
        return "done"
    if params.get("_payoff_used"):
        if params.get("_payoff_used") == "lipsync" and params.get("_payoff_clip_key"):
            path = os.path.join(work, "payoff-lipsync.mp4")  # a re-run: reuse the stored lip-synced shot
            with open(path, "wb") as fh:
                fh.write(deps.fetch(str(params["_payoff_clip_key"])))
            clips[index] = path
        return "done"
    clip = clips.get(index)
    vt = _vt(deps)
    if mode == "native" and clip and not params.get("reply_line") and vt.speech_present(clip):
        _save(job, _payoff_used="native")
        return "done"
    backend = str(params.get("lipsync_backend") or "")
    if mode == "voiceover" or not backend:
        _save(job, _payoff_used="voiceover")
        return "done"
    run = params.get("_lipsync")
    if not run:
        vo_key = ensure_vo(job, work, deps)
        frame = next(f for f in frames if int(f["index"]) == index)
        try:
            run = vt.lipsync_submit(
                backend, image_url=vt.presign(frame["key"]),
                video_url=vt.presign(frame.get("clip_key")) if frame.get("clip_key") else "",
                audio_url=vt.presign(vo_key), correlation_id=f"very-time:{job.id}:payoff")
        except Exception as exc:  # noqa: BLE001 - no lip-sync: the take is laid over as a voice-over
            logger.warning(f"very-time {job.id}: lip-sync not started ({exc})")
            _save(job, _payoff_used="voiceover")
            return "done"
        _save(job, _lipsync={**dict(run), "started": deps.now()})
        session.flush()
        return "wait"
    state, url = vt.lipsync_poll(run)
    if state == "running" and deps.now() - float(run.get("started") or deps.now()) < LIPSYNC_TIMEOUT_S:
        return "wait"
    if state == "completed" and url:
        try:
            data = (vt.download or _download)(url)
            path = os.path.join(work, "payoff-lipsync.mp4")
            with open(path, "wb") as fh:
                fh.write(data)
            key = f"jobs/{job.id}/story8/payoff-lipsync.mp4"
            deps.upload(path, key, "video/mp4")
            clips[index] = path
            _save(job, _payoff_used="lipsync", _payoff_clip_key=key)
            return "done"
        except Exception as exc:  # noqa: BLE001 - a bad download falls back to the voice-over
            logger.warning(f"very-time {job.id}: lip-sync result unusable ({exc})")
    _save(job, _payoff_used="voiceover")
    return "done"


def _download(url: str) -> bytes:
    from .story8_tasks import _download as download

    return download(url, 120.0)


def ensure_vo(job: Any, work: str, deps: Any) -> str:
    """The chosen voice take, rendered once and stored as ``jobs/<id>/story8/vo.mp3``."""
    params = dict(job.params or {})
    if params.get("_vo_key"):
        return str(params["_vo_key"])
    path, seconds, key = _vt(deps).voice_take(params=params, user_id=str(job.user_id), work=work, fetch=deps.fetch,
                                              max_seconds=None)
    vo_key = f"jobs/{job.id}/story8/vo{os.path.splitext(path)[1] or '.mp3'}"
    deps.upload(path, vo_key, "audio/mpeg")
    _save(job, _vo_key=vo_key, _take_key=key, _vo_seconds=float(seconds))
    return vo_key


def _local_vo(job: Any, work: str, deps: Any) -> str:
    key = ensure_vo(job, work, deps)
    path = os.path.join(work, "vo" + (os.path.splitext(key)[1] or ".mp3"))
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(deps.fetch(key))
    return path


# --------------------------------------------------------------------------- #
# End card
# --------------------------------------------------------------------------- #
def end_card_image(*, cta: str, logo: bytes | None, background: str, text_colour: str,
                   size: tuple[int, int] = (render.WIDTH, render.HEIGHT)) -> bytes:
    """A calm end card: brand colour, the logo centred, the call to action under it."""
    from PIL import Image, ImageDraw, ImageFont

    from app.utils import utils

    card = Image.new("RGB", size, background)
    width, height = size
    if logo:
        with Image.open(io.BytesIO(logo)) as source:
            mark = source.convert("RGBA")
            scale = min(width * 0.62 / mark.width, height * 0.18 / mark.height)
            mark = mark.resize((max(1, int(mark.width * scale)), max(1, int(mark.height * scale))), Image.LANCZOS)
            card.paste(mark, ((width - mark.width) // 2, int(height * 0.40) - mark.height // 2), mark)
    if cta:
        draw = ImageDraw.Draw(card)
        font_path = os.path.join(utils.font_dir(), "Inter-Bold.ttf")
        size_px = max(18, int(width * 0.05))
        font = ImageFont.truetype(font_path, size_px) if os.path.exists(font_path) else ImageFont.load_default()
        while draw.textlength(cta, font=font) > width * 0.86 and size_px > 14:
            size_px -= 2
            font = ImageFont.truetype(font_path, size_px) if os.path.exists(font_path) else font
        y = int(height * (0.56 if logo else 0.5))
        draw.text(((width - draw.textlength(cta, font=font)) / 2, y), cta, font=font, fill=text_colour)
    out = io.BytesIO()
    card.save(out, format="PNG")
    return out.getvalue()


def end_card_clip(job: Any, work: str, deps: Any, ffmpeg: str) -> str | None:
    from . import very_time

    params = dict(job.params or {})
    card = dict(params.get("end_card") or {})
    seconds = float(card.get("seconds") or 0)
    if seconds <= 0:
        return None
    brand = dict(params.get("brand") or {})
    logo = None
    if brand.get("logo_ref"):
        logo = deps.fetch(str(brand["logo_ref"]))
    else:
        path = very_time.brand_asset_path(str(brand.get("preset") or ""), "logo")
        if path is not None:
            logo = path.read_bytes()
    colours = dict(very_time.preset().get("end_card") or {})
    if brand.get("preset"):
        colours.update(very_time.brand_preset(str(brand["preset"])).get("end_card") or {})
    image = end_card_image(cta=str(brand.get("cta") or ""), logo=logo, background=str(colours.get("background")
                           or "#141414"), text_colour=str(colours.get("text") or "#F2EEE9"))
    still = os.path.join(work, "end-card.png")
    with open(still, "wb") as fh:
        fh.write(image)
    out = os.path.join(work, "end-card.mp4")
    render.run(render.ken_burns_command(still, out, seconds=seconds, camera="hold", ffmpeg=ffmpeg))
    return out


# --------------------------------------------------------------------------- #
# Sound: voice, effects, room tone, master
# --------------------------------------------------------------------------- #
def _starts(frames: Sequence[Mapping[str, Any]]) -> dict[int, float]:
    t, out = 0.0, {}
    for frame in sorted(frames, key=lambda f: int(f["index"])):
        out[int(frame["index"])] = t
        t += float(frame["seconds"])
    return out


def build_audio(job: Any, work: str, deps: Any, clips: Mapping[int, str], ffmpeg: str) -> tuple[str, float, float]:
    """Mastered wav for the whole video; returns ``(path, line_start_s, beats_end_s)``."""
    from . import very_time_audio as audio

    params = dict(job.params or {})
    frames = sorted((dict(f) for f in params.get("frames") or []), key=lambda f: int(f["index"]))
    starts = _starts(frames)
    beats_end = sum(float(f["seconds"]) for f in frames)
    total = float(params.get("duration_s") or beats_end)
    index = _speaking_index(frames)
    line_start = starts.get(index, 0.0) if index is not None else 0.0
    native = params.get("_payoff_used") == "native" and index is not None and clips.get(index)
    vo, vo_delay = None, 0.0
    if native:
        vo = os.path.join(work, "native-line.wav")
        audio.run(audio.native_audio_command(clips[index], vo, seconds=float(frames[index]["seconds"]),
                                             ffmpeg=ffmpeg))
        vo_delay = line_start
    elif index is not None:
        vo, vo_delay = _local_vo(job, work, deps), line_start + SPEECH_LEAD_S
    room = None
    if (params.get("sound") or {}).get("room_tone") and clips:
        parts = [(None if (native and i == index) else clips.get(int(f["index"])), float(f["seconds"]))
                 for i, f in enumerate(frames)]
        room = audio.room_tone_track(parts, os.path.join(work, "room.wav"), work, ffmpeg=ffmpeg)
    effects = _effects(job, work, deps, frames, starts, clips)
    mixed = os.path.join(work, "mix.wav")
    audio.run(audio.mix_command(out=mixed, total_s=total, vo=vo, vo_delay_s=vo_delay, sfx=effects, room=room,
                                ffmpeg=ffmpeg))
    master = os.path.join(work, "master.wav")
    audio.loudnorm_two_pass(mixed, master, ffmpeg=ffmpeg)
    return master, line_start, beats_end


def _effects(job: Any, work: str, deps: Any, frames: Sequence[Mapping[str, Any]], starts: Mapping[int, float],
             clips: Mapping[int, str]) -> list[tuple[str, float]]:
    params = dict(job.params or {})
    backend = str(params.get("sfx_backend") or "")
    if not (params.get("sound") or {}).get("sfx") or not backend:
        return []
    vt, out = _vt(deps), []
    for frame in frames:
        prompt = str(frame.get("sfx") or "").strip()
        if not prompt or str(frame.get("line") or "").strip():
            continue  # the payoff beat stays quiet under the line
        path = os.path.join(work, f"sfx-{int(frame['index']) + 1}.mp3")
        try:
            clip_key = frame.get("clip_key")
            vt.make_sfx(backend, prompt, float(frame["seconds"]), path,
                        clip_url=vt.presign(clip_key) if clip_key else "",
                        image_url=vt.presign(frame["key"]) if frame.get("key") else "")
            out.append((path, starts[int(frame["index"])]))
        except Exception as exc:  # noqa: BLE001 - one missing effect never fails the video
            logger.warning(f"very-time {job.id}: no sound effect for beat {frame['index']} ({exc})")
    return out


def final_command(beats: str, end_card: str | None, audio_path: str, out: str, *, total_s: float,
                  ass_path: str | None, fonts_dir: str | None, grade: Sequence[str], ffmpeg: str) -> list[str]:
    """Grade + captions on the beats only (the end card keeps the brand colours), then the end card,
    the mastered audio as is, cut to exactly ``total_s``."""
    parts = [str(f) for f in grade if f]
    if ass_path:
        burn = f"ass={render._escape_filter_path(ass_path)}"
        if fonts_dir:
            burn += f":fontsdir={render._escape_filter_path(fonts_dir)}"
        parts.append(burn)
    chain = ",".join([*parts, "setsar=1", "format=yuv420p"])
    inputs = ["-i", beats] + (["-i", end_card] if end_card else []) + ["-i", audio_path]
    audio_index = 2 if end_card else 1
    graph = f"[0:v]{chain}[b]"
    if end_card:
        graph += ";[1:v]setsar=1,format=yuv420p[e];[b][e]concat=n=2:v=1:a=0[v]"
        video_label = "[v]"
    else:
        video_label = "[b]"
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", graph,
            "-map", video_label, "-map", f"{audio_index}:a", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-ac", "2", "-t", f"{float(total_s):.3f}", "-movflags", "+faststart", *render._video_out(out)]


def finish(session: Any, job: Any, work: str, deps: Any, clips: Mapping[int, str], *, frame_file: Callable
           ) -> dict[str, str]:
    """Render the very-time video into ``work/final.mp4``; returns the local paths."""
    from app.utils import utils

    params = dict(job.params or {})
    frames = sorted((dict(f) for f in params.get("frames") or []), key=lambda f: int(f["index"]))
    ffmpeg = render.ffmpeg_bin()
    slots = []
    for frame in frames:
        out = os.path.join(work, f"slot-{frame['index'] + 1}.mp4")
        clip = clips.get(int(frame["index"]))
        if clip:
            render.run(render.fit_clip_command(clip, out, seconds=frame["seconds"], ffmpeg=ffmpeg))
        else:
            render.run(render.ken_burns_command(frame_file(frame), out, seconds=frame["seconds"],
                                                camera=frame["camera"], ffmpeg=ffmpeg))
        slots.append(out)
    beats = os.path.join(work, "beats.mp4")
    render.run(render.concat_command(slots, beats, ffmpeg=ffmpeg))
    card = end_card_clip(job, work, deps, ffmpeg)
    master, line_start, beats_end = build_audio(job, work, deps, clips, ffmpeg)
    data = story8.job_preset(params)
    look = (data.get("looks") or {}).get(str(params.get("look") or ""), {})
    style = str(look.get("caption_style") or "game_yellow")
    text = " ".join(t for t in (str(params.get("line") or ""), str(params.get("reply_line") or "")) if t.strip())
    burn = deps.burn_captions if deps.burn_captions is not None else render.has_filter("ass", ffmpeg)
    ass_path = None
    if burn and text:
        ass_path = os.path.join(work, "captions.ass")
        with open(ass_path, "w", encoding="utf-8") as fh:
            fh.write(render.captions_ass([], style, lines=[(text, line_start, beats_end)],
                                         language=str(params.get("language") or "")))
    elif deps.burn_captions is None and text:
        raise render.RenderError("this ffmpeg cannot burn captions (no ass filter)")
    grade = render.look_filters(look, ffmpeg=ffmpeg, lut_available=deps.grade)
    final = os.path.join(work, "final.mp4")
    total = float(params.get("duration_s") or beats_end)
    render.run(final_command(beats, card, master, final, total_s=total, ass_path=ass_path,
                             fonts_dir=utils.font_dir(), grade=grade, ffmpeg=ffmpeg))
    return {"final": final}


__all__ = ["VtDeps", "build_audio", "end_card_image", "final_command", "finish", "frame_lane", "garment_key",
           "identity_key", "is_very_time", "make_frames", "payoff_stage", "shot_generate_audio", "shot_references"]
