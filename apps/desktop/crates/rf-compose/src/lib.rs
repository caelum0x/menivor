//! Compose step (`rf-compose`) — the last link in the desktop render chain: it
//! turns an [`rf_plan::RenderPlan`] into a concrete FFmpeg `-filter_complex`
//! string via the [`rf_ffmpeg`] filtergraph builder. Blueprint → command.
//!
//! Pure + deterministic (input labels + the burned-caption `.ass` path are
//! injected; no I/O). The graph nodes come from `rf-ffmpeg` (which mirrors the
//! cloud's compose filtergraph), so a desktop-composed reel matches the cloud's.

use rf_ffmpeg::FilterGraph;
use rf_plan::RenderPlan;

/// The concrete inputs a plan needs to become a runnable filtergraph.
#[derive(Debug, Clone)]
pub struct ComposeInputs<'a> {
    /// The source video stream label, e.g. `"0:v"`.
    pub video_label: &'a str,
    /// Path to the burned-caption `.ass` file; empty = no captions.
    pub ass_path: &'a str,
    /// Fonts directory for libass.
    pub fonts_dir: &'a str,
}

/// A composed reel: the filtergraph + the label of its final video node.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Composition {
    pub filtergraph: String,
    pub output_label: String,
    pub width: u32,
    pub height: u32,
}

/// Output dimensions for a plan's aspect (defaults to portrait 9:16).
pub fn dimensions_for_aspect(aspect: &str) -> (u32, u32) {
    match aspect {
        "1:1" => (1080, 1080),
        "16:9" => (1920, 1080),
        _ => (1080, 1920),
    }
}

/// Build the FFmpeg filtergraph for a reel: scale-to-fill the source to the
/// plan's aspect, then (when captions exist and an `.ass` path is given) burn
/// them. Returns the graph + the final output label to map.
pub fn compose(plan: &RenderPlan, inputs: &ComposeInputs) -> Composition {
    let (width, height) = dimensions_for_aspect(&plan.aspect);
    let has_captions =
        !inputs.ass_path.is_empty() && plan.slots.iter().any(|s| s.caption_style.is_some());

    let mut graph = FilterGraph::new().scale_crop_fill(inputs.video_label, width, height, "scaled");
    let output_label = if has_captions {
        graph = graph.ass("scaled", inputs.ass_path, inputs.fonts_dir, "final");
        "final"
    } else {
        "scaled"
    };

    Composition {
        filtergraph: graph.build(),
        output_label: output_label.to_string(),
        width,
        height,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rf_shots::{SegmentSlot, ShotTemplate};

    fn plan(aspect: &str, caption: &str) -> RenderPlan {
        let template = ShotTemplate {
            slug: "t".into(),
            genre: "g".into(),
            aspect: aspect.into(),
            slots: vec![SegmentSlot {
                role: "hook".into(),
                t_start_ms: 0,
                t_end_ms: 3000,
                caption_preset: caption.into(),
                transition_out: "cut".into(),
            }],
        };
        rf_plan::plan_from_template(&template)
    }

    #[test]
    fn portrait_scale_and_caption_burn() {
        // A real caption preset resolves, so the plan has captions to burn.
        let known = rf_captions::list_presets().into_iter().next().unwrap();
        let c = compose(
            &plan("9:16", &known),
            &ComposeInputs {
                video_label: "0:v",
                ass_path: "/tmp/c.ass",
                fonts_dir: "/fonts",
            },
        );
        assert_eq!((c.width, c.height), (1080, 1920));
        assert!(c.filtergraph.contains("scale=1080:1920"));
        assert!(c.filtergraph.contains("ass="));
        assert_eq!(c.output_label, "final");
    }

    #[test]
    fn no_ass_path_skips_caption_node() {
        let known = rf_captions::list_presets().into_iter().next().unwrap();
        let c = compose(
            &plan("9:16", &known),
            &ComposeInputs {
                video_label: "0:v",
                ass_path: "",
                fonts_dir: "/fonts",
            },
        );
        assert!(!c.filtergraph.contains("ass="));
        assert_eq!(c.output_label, "scaled");
    }

    #[test]
    fn aspect_maps_to_dimensions() {
        assert_eq!(dimensions_for_aspect("1:1"), (1080, 1080));
        assert_eq!(dimensions_for_aspect("16:9"), (1920, 1080));
        assert_eq!(dimensions_for_aspect("9:16"), (1080, 1920));
        assert_eq!(dimensions_for_aspect("weird"), (1080, 1920));
    }

    #[test]
    fn unresolved_caption_means_no_burn() {
        // A bogus caption preset resolves to None, so there is nothing to burn
        // even when an ass path is supplied.
        let c = compose(
            &plan("1:1", "___nope___"),
            &ComposeInputs {
                video_label: "0:v",
                ass_path: "/tmp/c.ass",
                fonts_dir: "/fonts",
            },
        );
        assert_eq!((c.width, c.height), (1080, 1080));
        assert!(!c.filtergraph.contains("ass="));
        assert_eq!(c.output_label, "scaled");
    }
}
