//! Render blueprint composition (`rf-plan`). Turns a shot-template preset
//! (`rf-shots`) into a concrete, orderable render plan whose every slot has its
//! caption **style resolved** (`rf-captions`) and its duration computed — the
//! bridge from "a genre blueprint" to "what the renderer actually lays down".
//!
//! Pure + deterministic. The template structure, its content hash, and the
//! caption styles all come from the golden-parity crates, so a desktop plan
//! matches what the cloud composes. Only the *resolution/joining* lives here.

use rf_captions::{get_preset as caption_preset, CaptionStyle};
use rf_shots::{
    content_hash, get_preset as shot_preset, total_duration_ms, validate_template, ShotTemplate,
};

/// One slot of the plan: the shot's timing + role, with its caption style resolved.
#[derive(Debug, Clone)]
pub struct PlannedSlot {
    pub role: String,
    pub t_start_ms: i64,
    pub t_end_ms: i64,
    pub duration_ms: i64,
    pub transition_out: String,
    pub caption_preset: String,
    /// The resolved caption style, or `None` if the slot names an unknown preset.
    pub caption_style: Option<CaptionStyle>,
}

/// A fully-resolved render blueprint.
#[derive(Debug, Clone)]
pub struct RenderPlan {
    pub slug: String,
    pub genre: String,
    pub aspect: String,
    pub total_duration_ms: i64,
    pub content_hash: String,
    pub slots: Vec<PlannedSlot>,
    /// Template-validation errors plus any unresolved-caption warnings (empty = clean).
    pub warnings: Vec<String>,
}

impl RenderPlan {
    /// Every slot resolved a caption style and the template validated cleanly.
    pub fn is_clean(&self) -> bool {
        self.warnings.is_empty()
    }
}

/// Build a render plan from a shot-template preset slug (e.g. a genre blueprint).
pub fn plan_from_preset(slug: &str) -> Result<RenderPlan, String> {
    let template = shot_preset(slug)?;
    Ok(plan_from_template(&template))
}

/// Build a render plan from a shot template, resolving each slot's caption style.
pub fn plan_from_template(template: &ShotTemplate) -> RenderPlan {
    let mut warnings = validate_template(template);
    let slots = template
        .slots
        .iter()
        .map(|s| {
            let caption_style = match caption_preset(&s.caption_preset) {
                Ok(style) => Some(style),
                Err(_) => {
                    warnings.push(format!(
                        "slot '{}' names an unknown caption preset '{}'",
                        s.role, s.caption_preset
                    ));
                    None
                }
            };
            PlannedSlot {
                role: s.role.clone(),
                t_start_ms: s.t_start_ms,
                t_end_ms: s.t_end_ms,
                duration_ms: (s.t_end_ms - s.t_start_ms).max(0),
                transition_out: s.transition_out.clone(),
                caption_preset: s.caption_preset.clone(),
                caption_style,
            }
        })
        .collect();

    RenderPlan {
        slug: template.slug.clone(),
        genre: template.genre.clone(),
        aspect: template.aspect.clone(),
        total_duration_ms: total_duration_ms(template),
        content_hash: content_hash(template),
        slots,
        warnings,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rf_shots::SegmentSlot;

    #[test]
    fn every_shipped_preset_plans() {
        let slugs = rf_shots::list_presets(None);
        assert!(!slugs.is_empty(), "expected shipped shot presets");
        for slug in &slugs {
            let plan = plan_from_preset(slug).unwrap();
            assert!(!plan.slots.is_empty(), "{slug} has no slots");
            assert!(plan.total_duration_ms > 0, "{slug} has zero duration");
            assert!(!plan.content_hash.is_empty(), "{slug} has no hash");
            // Each slot's computed duration is the span of its timing.
            for s in &plan.slots {
                assert_eq!(s.duration_ms, (s.t_end_ms - s.t_start_ms).max(0));
            }
        }
    }

    #[test]
    fn resolves_known_and_flags_unknown_caption_presets() {
        // A real caption preset name resolves; a bogus one warns + resolves to None.
        let known = rf_captions::list_presets()
            .into_iter()
            .next()
            .expect("a caption preset");
        let template = ShotTemplate {
            slug: "test".into(),
            genre: "test".into(),
            aspect: "9:16".into(),
            slots: vec![
                SegmentSlot {
                    role: "hook".into(),
                    t_start_ms: 0,
                    t_end_ms: 3000,
                    caption_preset: known.clone(),
                    transition_out: "cut".into(),
                },
                SegmentSlot {
                    role: "payoff".into(),
                    t_start_ms: 3000,
                    t_end_ms: 8000,
                    caption_preset: "___not-a-preset___".into(),
                    transition_out: "cut".into(),
                },
            ],
        };
        let plan = plan_from_template(&template);
        assert_eq!(plan.slots.len(), 2);
        assert_eq!(plan.total_duration_ms, 8000);
        assert_eq!(plan.slots[0].duration_ms, 3000);
        assert!(
            plan.slots[0].caption_style.is_some(),
            "known preset should resolve"
        );
        assert!(
            plan.slots[1].caption_style.is_none(),
            "bogus preset should be None"
        );
        assert!(plan
            .warnings
            .iter()
            .any(|w| w.contains("unknown caption preset")));
        assert!(!plan.is_clean());
    }
}
