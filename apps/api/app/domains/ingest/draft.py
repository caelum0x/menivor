"""Pure reel-draft assembly from extracted page content (no network, no LLM).

Turns ``{title, description, features}`` into a hook-first UGC reel draft
(subject + script + b-roll prompts) using a deterministic template, so URL→reel
works out of the box; an optional LLM rewrite can polish it later. Pure + tested.
"""

from __future__ import annotations

_MAX_SCRIPT_FEATURES = 4


def _hook(title: str) -> str:
    title = (title or "").strip().rstrip(".")
    if not title:
        return "You have to see this."
    return f"POV: you just found {title}."


def build_reel_draft(content: dict) -> dict:
    """Assemble a reel draft from extracted content.

    Returns ``{video_subject, hook, video_script, broll_prompts}``. The script is
    hook → 1-3 feature beats → CTA. B-roll prompts are cinematic phrasings of the
    title + features for the AI B-roll studio.
    """
    title = str(content.get("title", "") or "").strip()
    description = str(content.get("description", "") or "").strip()
    features = [str(f).strip() for f in (content.get("features") or []) if str(f).strip()]

    hook = _hook(title)
    beats: list[str] = []
    if description:
        beats.append(description[:220])
    for feat in features[:_MAX_SCRIPT_FEATURES]:
        beats.append(feat)
    if not beats:
        beats.append(f"{title} is worth a look." if title else "This is worth a look.")

    cta = "Check the link to try it."
    script = " ".join([hook, *beats, cta]).strip()

    broll_prompts: list[str] = []
    if title:
        broll_prompts.append(f"cinematic hero shot of {title}")
    for feat in features[:3]:
        broll_prompts.append(f"dynamic b-roll illustrating: {feat}")

    return {
        "video_subject": title or "New find",
        "hook": hook,
        "video_script": script,
        "broll_prompts": broll_prompts,
    }
