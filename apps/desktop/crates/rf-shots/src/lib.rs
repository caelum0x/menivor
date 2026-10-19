//! `rf-shots` — Rust port of `@reelforge/shot-template-schema` (golden-parity).
//!
//! Genre templates expressed as ordered, named segment slots
//! (Hook / Setup / Proof / Rising / Body / Escalation / Exchange / Climax /
//! Payoff / Button / CTA / Loop / Seam) with validation, total-duration math,
//! and deterministic instance hashing.
//!
//! Slot times are integer milliseconds (`i64`) so the FNV-1a-32 content hash is
//! byte-identical to the TypeScript source of truth and the Python port. The
//! canonical string assembly and hashing mirror `template.ts` exactly.

use serde::{Deserialize, Serialize};

/// Canonical slot roles + narrative ordering (mirror of `roles.ts`).
pub const ROLE_ORDER: [&str; 14] = [
    "hook",
    "setup",
    "proof1",
    "proof2",
    "rising",
    "body",
    "escalation",
    "exchange",
    "climax",
    "payoff",
    "button",
    "cta",
    "loop",
    "seam",
];

/// Position of `role` within [`ROLE_ORDER`], if it is a known role.
fn index_of(role: &str) -> Option<usize> {
    ROLE_ORDER.iter().position(|&r| r == role)
}

/// `true` when `role` is one of the canonical [`ROLE_ORDER`] roles.
pub fn is_role(role: &str) -> bool {
    index_of(role).is_some()
}

/// Narrative-order index of `role`; errors for an unknown role (mirrors the TS
/// `throw new Error("unknown slot role ...")`).
pub fn role_index(role: &str) -> Result<usize, String> {
    index_of(role).ok_or_else(|| format!("unknown slot role {role}"))
}

/// A single timed segment slot within a [`ShotTemplate`].
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SegmentSlot {
    pub role: String,
    pub t_start_ms: i64,
    pub t_end_ms: i64,
    pub caption_preset: String,
    pub transition_out: String,
}

/// A named genre template: an ordered list of segment slots.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ShotTemplate {
    pub slug: String,
    pub genre: String,
    pub aspect: String,
    pub slots: Vec<SegmentSlot>,
}

/// Build a [`SegmentSlot`]. `caption_preset` defaults to `""` and
/// `transition_out` defaults to `"cut"` (mirror of `makeSlot`).
pub fn make_slot(
    role: &str,
    t_start_ms: i64,
    t_end_ms: i64,
    caption_preset: Option<&str>,
    transition_out: Option<&str>,
) -> SegmentSlot {
    SegmentSlot {
        role: role.to_string(),
        t_start_ms,
        t_end_ms,
        caption_preset: caption_preset.unwrap_or("").to_string(),
        transition_out: transition_out.unwrap_or("cut").to_string(),
    }
}

/// Build a [`ShotTemplate`] from its parts (mirror of `makeTemplate`).
pub fn make_template(
    slug: &str,
    genre: &str,
    aspect: &str,
    slots: Vec<SegmentSlot>,
) -> ShotTemplate {
    ShotTemplate {
        slug: slug.to_string(),
        genre: genre.to_string(),
        aspect: aspect.to_string(),
        slots,
    }
}

/// Largest `t_end_ms` across all slots (0 for an empty template).
pub fn total_duration_ms(template: &ShotTemplate) -> i64 {
    template.slots.iter().fold(0, |max, s| max.max(s.t_end_ms))
}

/// Validate a template's slots, returning a list of human-readable errors
/// (empty when valid). Mirrors `validateTemplate` order and messages exactly.
pub fn validate_template(template: &ShotTemplate) -> Vec<String> {
    let mut errors: Vec<String> = Vec::new();
    let slots = &template.slots;
    if slots.is_empty() {
        errors.push("template has no slots".to_string());
        return errors;
    }
    let mut prev_end: Option<i64> = None;
    let mut prev_role_idx: i64 = -1;
    for (i, s) in slots.iter().enumerate() {
        if !is_role(&s.role) {
            errors.push(format!("slot {i}: unknown role {}", s.role));
            continue;
        }
        let ts = s.t_start_ms;
        let te = s.t_end_ms;
        if ts < 0 {
            errors.push(format!("slot {i}: negative t_start_ms"));
        }
        if te <= ts {
            errors.push(format!("slot {i}: t_end_ms must be > t_start_ms"));
        }
        if let Some(pe) = prev_end {
            if ts < pe {
                errors.push(format!("slot {i}: overlaps previous slot"));
            }
            if ts > pe {
                errors.push(format!("slot {i}: gap after previous slot"));
            }
        }
        let idx = index_of(&s.role).expect("is_role checked above") as i64;
        if idx < prev_role_idx {
            errors.push(format!("slot {i}: role {} out of narrative order", s.role));
        }
        prev_end = Some(te);
        prev_role_idx = idx;
    }
    let first = &slots[0].role;
    if first != "hook" && first != "loop" {
        errors.push("first slot should be a hook (or a single loop)".to_string());
    }
    errors
}

/// Canonical byte-identical string used for content hashing (mirror of `canon`).
fn canon(template: &ShotTemplate) -> String {
    let body = template
        .slots
        .iter()
        .map(|s| {
            format!(
                "{},{},{},{},{}",
                s.role, s.t_start_ms, s.t_end_ms, s.caption_preset, s.transition_out
            )
        })
        .collect::<Vec<_>>()
        .join(";");
    format!(
        "{}|{}|{}|{}",
        template.slug, template.genre, template.aspect, body
    )
}

/// Deterministic FNV-1a-32 hex of the canonical template string — identical to
/// the TypeScript and Python ports.
pub fn content_hash(template: &ShotTemplate) -> String {
    let mut h: u32 = 0x811c_9dc5;
    for byte in canon(template).as_bytes() {
        h ^= u32::from(*byte);
        h = h.wrapping_mul(0x0100_0193);
    }
    format!("{h:08x}")
}

/// Seed genre presets (mirror of `presets.ts`). Slot timings, genres, and
/// caption presets are byte-identical to the shared golden fixture
/// (`packages/shot-template-schema/test/fixtures/golden/templates.json`) so the
/// FNV-1a-32 content hashes match the TypeScript and Python ports exactly.
fn presets() -> Vec<ShotTemplate> {
    vec![
        make_template(
            "anime-beat-edit",
            "edit",
            "9:16",
            vec![
                make_slot("hook", 0, 1600, Some("clean_white"), Some("cut")),
                make_slot("body", 1600, 18400, Some("clean_white"), Some("cut")),
                make_slot("payoff", 18400, 20000, Some("clean_white"), Some("cut")),
            ],
        ),
        make_template(
            "asmr-satisfying-loop",
            "asmr",
            "9:16",
            vec![
                make_slot("hook", 0, 1000, Some("clean_white"), Some("cut")),
                make_slot("body", 1000, 4500, Some("clean_white"), Some("cut")),
                make_slot("seam", 4500, 5000, Some("clean_white"), Some("cut")),
            ],
        ),
        make_template(
            "before-after",
            "marketing",
            "9:16",
            vec![
                make_slot("hook", 0, 3500, Some("karaoke_yellow"), Some("cut")),
                make_slot("setup", 3500, 9500, Some("karaoke_yellow"), Some("cut")),
                make_slot("rising", 9500, 18500, Some("karaoke_yellow"), Some("cut")),
                make_slot("climax", 18500, 22500, Some("karaoke_yellow"), Some("cut")),
                make_slot("cta", 22500, 25000, Some("karaoke_yellow"), Some("cut")),
            ],
        ),
        make_template(
            "brainrot-ai-meme",
            "meme",
            "9:16",
            vec![
                make_slot("hook", 0, 1440, Some("bold_violet"), Some("cut")),
                make_slot("escalation", 1440, 9000, Some("bold_violet"), Some("cut")),
                make_slot("payoff", 9000, 12000, Some("bold_violet"), Some("cut")),
            ],
        ),
        make_template(
            "fake-ai-podcast",
            "podcast",
            "9:16",
            vec![
                make_slot("hook", 0, 3000, Some("bold_violet"), Some("cut")),
                make_slot("exchange", 3000, 45000, Some("bold_violet"), Some("cut")),
                make_slot("button", 45000, 50000, Some("bold_violet"), Some("cut")),
            ],
        ),
        make_template(
            "greenscreen-react",
            "commentary",
            "9:16",
            vec![
                make_slot("hook", 0, 3900, Some("clean_white"), Some("cut")),
                make_slot("body", 3900, 18600, Some("clean_white"), Some("cut")),
                make_slot("payoff", 18600, 25800, Some("clean_white"), Some("cut")),
                make_slot("cta", 25800, 30000, Some("clean_white"), Some("cut")),
            ],
        ),
        make_template(
            "listicle",
            "edutainment",
            "9:16",
            vec![
                make_slot("hook", 0, 2800, Some("bold_violet"), Some("cut")),
                make_slot("rising", 2800, 21840, Some("bold_violet"), Some("cut")),
                make_slot("payoff", 21840, 25200, Some("bold_violet"), Some("cut")),
                make_slot("cta", 25200, 28000, Some("bold_violet"), Some("cut")),
            ],
        ),
        make_template(
            "minecraft-reddit-split",
            "brainrot-split",
            "9:16",
            vec![
                make_slot("hook", 0, 2025, Some("karaoke_yellow"), Some("cut")),
                make_slot("setup", 2025, 9900, Some("karaoke_yellow"), Some("cut")),
                make_slot("rising", 9900, 31500, Some("karaoke_yellow"), Some("cut")),
                make_slot("climax", 31500, 39600, Some("karaoke_yellow"), Some("cut")),
                make_slot("cta", 39600, 45000, Some("karaoke_yellow"), Some("cut")),
            ],
        ),
        make_template(
            "movie-recap",
            "recap",
            "9:16",
            vec![
                make_slot("hook", 0, 4800, Some("karaoke_yellow"), Some("cut")),
                make_slot("setup", 4800, 15000, Some("karaoke_yellow"), Some("cut")),
                make_slot("body", 15000, 49200, Some("karaoke_yellow"), Some("cut")),
                make_slot("payoff", 49200, 56400, Some("karaoke_yellow"), Some("cut")),
                make_slot("cta", 56400, 60000, Some("karaoke_yellow"), Some("cut")),
            ],
        ),
        make_template(
            "platform-hook-open",
            "opener",
            "9:16",
            vec![
                make_slot("hook", 0, 500, Some("karaoke_yellow"), Some("cut")),
                make_slot("setup", 500, 3000, Some("karaoke_yellow"), Some("cut")),
                make_slot("payoff", 3000, 5000, Some("karaoke_yellow"), Some("cut")),
            ],
        ),
        make_template(
            "product-demo-ad",
            "marketing",
            "9:16",
            vec![
                make_slot("hook", 0, 3600, Some("karaoke_yellow"), Some("cut")),
                make_slot("setup", 3600, 9000, Some("karaoke_yellow"), Some("cut")),
                make_slot("rising", 9000, 21600, Some("karaoke_yellow"), Some("cut")),
                make_slot("payoff", 21600, 26400, Some("karaoke_yellow"), Some("cut")),
                make_slot("cta", 26400, 30000, Some("karaoke_yellow"), Some("cut")),
            ],
        ),
        make_template(
            "quiz-engagement",
            "engagement",
            "9:16",
            vec![
                make_slot("hook", 0, 2200, Some("karaoke_green"), Some("cut")),
                make_slot("rising", 2200, 15400, Some("karaoke_green"), Some("cut")),
                make_slot("climax", 15400, 18920, Some("karaoke_green"), Some("cut")),
                make_slot("cta", 18920, 20900, Some("karaoke_green"), Some("cut")),
                make_slot("loop", 20900, 22000, Some("karaoke_green"), Some("cut")),
            ],
        ),
        make_template(
            "split-screen-gameplay-story",
            "brainrot-split",
            "9:16",
            vec![
                make_slot("hook", 0, 2250, Some("karaoke_green"), Some("cut")),
                make_slot("body", 2250, 40500, Some("karaoke_green"), Some("cut")),
                make_slot("cta", 40500, 45000, Some("karaoke_green"), Some("cut")),
            ],
        ),
        make_template(
            "testimonial-ad",
            "marketing",
            "9:16",
            vec![
                make_slot("hook", 0, 3500, Some("clean_white"), Some("cut")),
                make_slot("setup", 3500, 10000, Some("clean_white"), Some("cut")),
                make_slot("payoff", 10000, 20500, Some("clean_white"), Some("cut")),
                make_slot("cta", 20500, 25000, Some("clean_white"), Some("cut")),
            ],
        ),
    ]
}

/// Fetch a preset template by slug; errors for an unknown slug (mirror of
/// `getPreset`).
pub fn get_preset(slug: &str) -> Result<ShotTemplate, String> {
    presets()
        .into_iter()
        .find(|t| t.slug == slug)
        .ok_or_else(|| format!("unknown template preset {slug}"))
}

/// Sorted preset slugs, optionally filtered by genre (mirror of `listPresets`).
pub fn list_presets(genre: Option<&str>) -> Vec<String> {
    let mut slugs: Vec<String> = presets()
        .into_iter()
        .filter(|t| genre.is_none_or(|g| t.genre == g))
        .map(|t| t.slug)
        .collect();
    slugs.sort();
    slugs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn role_order_matches_golden() {
        assert_eq!(
            ROLE_ORDER,
            [
                "hook",
                "setup",
                "proof1",
                "proof2",
                "rising",
                "body",
                "escalation",
                "exchange",
                "climax",
                "payoff",
                "button",
                "cta",
                "loop",
                "seam"
            ]
        );
        assert!(is_role("hook"));
        assert!(!is_role("nope"));
        assert_eq!(role_index("payoff").unwrap(), 9);
        assert!(role_index("bogus").is_err());
    }

    #[test]
    fn make_slot_defaults() {
        let s = make_slot("hook", 0, 3000, None, None);
        assert_eq!(s.caption_preset, "");
        assert_eq!(s.transition_out, "cut");
    }

    #[test]
    fn preset_hashes_match_golden() {
        // Golden FNV-1a-32 hashes from test/fixtures/golden/templates.json.
        let golden = [
            ("anime-beat-edit", "8b5a46f0", 20000),
            ("asmr-satisfying-loop", "45c3c437", 5000),
            ("before-after", "7cb6e33d", 25000),
            ("brainrot-ai-meme", "c1043099", 12000),
            ("fake-ai-podcast", "db9691a8", 50000),
            ("minecraft-reddit-split", "7a89050c", 45000),
            ("movie-recap", "475811c2", 60000),
            ("platform-hook-open", "9c1eb469", 5000),
        ];
        for (slug, hash, total) in golden {
            let t = get_preset(slug).unwrap();
            assert_eq!(content_hash(&t), hash, "hash mismatch for {slug}");
            assert_eq!(total_duration_ms(&t), total, "duration mismatch for {slug}");
            assert!(validate_template(&t).is_empty(), "{slug} should be valid");
        }
    }

    #[test]
    fn list_presets_sorted_and_filtered() {
        assert_eq!(
            list_presets(None),
            vec![
                "anime-beat-edit",
                "asmr-satisfying-loop",
                "before-after",
                "brainrot-ai-meme",
                "fake-ai-podcast",
                "greenscreen-react",
                "listicle",
                "minecraft-reddit-split",
                "movie-recap",
                "platform-hook-open",
                "product-demo-ad",
                "quiz-engagement",
                "split-screen-gameplay-story",
                "testimonial-ad"
            ]
        );
        // Genre filter returns the sorted slugs for that genre.
        assert_eq!(
            list_presets(Some("marketing")),
            vec!["before-after", "product-demo-ad", "testimonial-ad"]
        );
        assert_eq!(list_presets(Some("asmr")), vec!["asmr-satisfying-loop"]);
        assert!(list_presets(Some("nonexistent")).is_empty());
    }

    #[test]
    fn get_preset_unknown_errors() {
        assert!(get_preset("does-not-exist").is_err());
    }

    #[test]
    fn validate_empty_template() {
        let t = make_template("x", "g", "9:16", vec![]);
        assert_eq!(validate_template(&t), vec!["template has no slots"]);
        assert_eq!(total_duration_ms(&t), 0);
    }

    #[test]
    fn validate_unknown_role() {
        let t = make_template(
            "x",
            "g",
            "9:16",
            vec![make_slot("bogus", 0, 1000, None, None)],
        );
        let errs = validate_template(&t);
        assert!(errs.contains(&"slot 0: unknown role bogus".to_string()));
        // Unknown-role slot short-circuits, so no first-slot check is skipped:
        assert!(errs.contains(&"first slot should be a hook (or a single loop)".to_string()));
    }

    #[test]
    fn validate_gap_overlap_and_order() {
        // gap: slot 1 starts after prev end.
        let gap = make_template(
            "x",
            "g",
            "9:16",
            vec![
                make_slot("hook", 0, 1000, None, None),
                make_slot("rising", 2000, 3000, None, None),
            ],
        );
        assert!(validate_template(&gap).contains(&"slot 1: gap after previous slot".to_string()));

        // overlap: slot 1 starts before prev end.
        let overlap = make_template(
            "x",
            "g",
            "9:16",
            vec![
                make_slot("hook", 0, 2000, None, None),
                make_slot("rising", 1000, 3000, None, None),
            ],
        );
        assert!(validate_template(&overlap).contains(&"slot 1: overlaps previous slot".to_string()));

        // out of narrative order: payoff (6) before rising (4).
        let order = make_template(
            "x",
            "g",
            "9:16",
            vec![
                make_slot("hook", 0, 1000, None, None),
                make_slot("payoff", 1000, 2000, None, None),
                make_slot("rising", 2000, 3000, None, None),
            ],
        );
        assert!(validate_template(&order)
            .contains(&"slot 2: role rising out of narrative order".to_string()));
    }

    #[test]
    fn validate_bad_times_and_first_slot() {
        let t = make_template(
            "x",
            "g",
            "9:16",
            vec![make_slot("rising", 0, 0, None, None)],
        );
        let errs = validate_template(&t);
        assert!(errs.contains(&"slot 0: t_end_ms must be > t_start_ms".to_string()));
        assert!(errs.contains(&"first slot should be a hook (or a single loop)".to_string()));

        let neg = make_template(
            "x",
            "g",
            "9:16",
            vec![make_slot("hook", -5, 1000, None, None)],
        );
        assert!(validate_template(&neg).contains(&"slot 0: negative t_start_ms".to_string()));
    }

    #[test]
    fn loop_only_is_valid_first_slot() {
        // A single loop slot is an allowed first slot (the one exception to the
        // "first slot must be a hook" rule).
        let t = make_template(
            "loop-only",
            "asmr",
            "9:16",
            vec![make_slot("loop", 0, 5000, Some("clean_white"), Some("cut"))],
        );
        assert!(validate_template(&t).is_empty());
    }

    #[test]
    fn serde_roundtrips() {
        let t = get_preset("movie-recap").unwrap();
        let json = serde_json::to_string(&t).unwrap();
        let back: ShotTemplate = serde_json::from_str(&json).unwrap();
        assert_eq!(t, back);
        assert_eq!(content_hash(&t), content_hash(&back));
    }
}
