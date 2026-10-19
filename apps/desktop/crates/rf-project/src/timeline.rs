//! Non-destructive timeline export model (`rf-project::timeline`). The Rust
//! mirror of the web/mobile timeline editor (`apps/*/lib/editor` →
//! `POST /jobs/{id}/timeline-exports`): an ordered list of trimmed segments —
//! each with its own in/out, speed, and burned caption — plus text overlays on
//! a wall-clock track. The desktop editor assembles one of these and `rf-sync`
//! ships it to the same backend endpoint the web/mobile clients call.
//!
//! All math is integer-milliseconds (no floats) so the output-duration estimate
//! is deterministic and matches across runs. Speed is a per-mille factor
//! (`1000` = 1.0×) to keep the whole model float-free and content-addressable.

use serde::{Deserialize, Serialize};

/// `1000` per-mille = 1.0× playback speed. Bounds mirror the client editors
/// (0.25×..4×), expressed in per-mille.
pub const SPEED_UNIT: u32 = 1000;
pub const MIN_SPEED_MILLI: u32 = 250;
pub const MAX_SPEED_MILLI: u32 = 4000;
pub const MAX_SOURCE_MS: u32 = 21_600_000;
pub const MIN_SEGMENT_MS: u32 = 100;
pub const MAX_TEXT_CHARS: usize = 200;
pub const MAX_SEGMENTS: usize = 200;
pub const MAX_OVERLAYS: usize = 50;
/// Upper bound on an effect-kernel identifier (e.g. `push-in`, `shake`). A
/// generous cap that still fails fast on obviously malformed input; the actual
/// kernel-existence check happens at the UI boundary (which owns `rf-effects`).
pub const MAX_EFFECT_KERNEL_CHARS: usize = 64;

/// Where a text overlay is anchored on the frame.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum OverlayPosition {
    Top,
    Center,
    #[default]
    Bottom,
}

/// One trimmed span of the source, played at `speed_milli` per-mille.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Segment {
    pub source_in_ms: u32,
    pub source_out_ms: u32,
    /// Playback speed in per-mille (`1000` = 1.0×). Defaults to 1.0×.
    #[serde(default = "default_speed")]
    pub speed_milli: u32,
    /// Burned caption for this segment (empty = none).
    #[serde(default)]
    pub caption: String,
    /// Animation effect kernel applied to this segment, identified by its
    /// `rf-effects` kernel id (e.g. `push-in`). `None` = no effect. Persisted
    /// on the timeline so an effect applied in the desktop Effects section
    /// survives serialization into the project bundle and the timeline-export
    /// request the backend composes/renders from.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub effect_kernel: Option<String>,
}

fn default_speed() -> u32 {
    SPEED_UNIT
}

/// A text overlay pinned to a wall-clock window of the assembled output.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Overlay {
    pub text: String,
    pub start_ms: u32,
    pub end_ms: u32,
    #[serde(default)]
    pub position: OverlayPosition,
}

/// A full non-destructive timeline export request.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct TimelineExport {
    #[serde(default)]
    pub segments: Vec<Segment>,
    #[serde(default)]
    pub overlays: Vec<Overlay>,
}

/// Why a timeline can't be exported. Typed so the desktop UI can surface an
/// actionable message per failure (mirrors the client-side `canExport` gate).
/// Manual `Display`/`Error` impls (no `thiserror`) keep this crate dependency-free.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TimelineError {
    Empty,
    TooManySegments {
        count: usize,
    },
    TooManyOverlays {
        count: usize,
    },
    EmptySpan {
        index: usize,
        in_ms: u32,
        out_ms: u32,
    },
    SpeedOutOfRange {
        index: usize,
        speed_milli: u32,
    },
    SourceOutOfRange {
        index: usize,
        out_ms: u32,
    },
    SegmentTooShort {
        index: usize,
        span_ms: u32,
    },
    TextTooLong {
        kind: &'static str,
        index: usize,
    },
    EffectKernelTooLong {
        index: usize,
    },
    OverlayWindow {
        index: usize,
        start_ms: u32,
        end_ms: u32,
    },
    OverlayPastOutput {
        index: usize,
        end_ms: u32,
        output_ms: u64,
    },
}

impl std::fmt::Display for TimelineError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TimelineError::Empty => write!(f, "timeline has no segments"),
            TimelineError::TooManySegments { count } => {
                write!(f, "timeline has {count} segments; maximum is {MAX_SEGMENTS}")
            }
            TimelineError::TooManyOverlays { count } => {
                write!(f, "timeline has {count} overlays; maximum is {MAX_OVERLAYS}")
            }
            TimelineError::EmptySpan { index, in_ms, out_ms } => {
                write!(f, "segment {index}: out ({out_ms}ms) must be after in ({in_ms}ms)")
            }
            TimelineError::SpeedOutOfRange { index, speed_milli } => write!(
                f,
                "segment {index}: speed {speed_milli}‰ out of range [{MIN_SPEED_MILLI}, {MAX_SPEED_MILLI}]"
            ),
            TimelineError::SourceOutOfRange { index, out_ms } => write!(
                f,
                "segment {index}: source out ({out_ms}ms) exceeds {MAX_SOURCE_MS}ms"
            ),
            TimelineError::SegmentTooShort { index, span_ms } => write!(
                f,
                "segment {index}: span ({span_ms}ms) must be at least {MIN_SEGMENT_MS}ms"
            ),
            TimelineError::TextTooLong { kind, index } => {
                write!(f, "{kind} {index}: text exceeds {MAX_TEXT_CHARS} characters")
            }
            TimelineError::EffectKernelTooLong { index } => write!(
                f,
                "segment {index}: effect kernel id exceeds {MAX_EFFECT_KERNEL_CHARS} characters"
            ),
            TimelineError::OverlayWindow { index, start_ms, end_ms } => {
                write!(f, "overlay {index}: end ({end_ms}ms) must be after start ({start_ms}ms)")
            }
            TimelineError::OverlayPastOutput {
                index,
                end_ms,
                output_ms,
            } => write!(
                f,
                "overlay {index}: end ({end_ms}ms) extends past output ({output_ms}ms)"
            ),
        }
    }
}

impl std::error::Error for TimelineError {}

impl Segment {
    /// A 1.0× segment over `[in, out)`.
    pub fn new(source_in_ms: u32, source_out_ms: u32) -> Self {
        Segment {
            source_in_ms,
            source_out_ms,
            speed_milli: SPEED_UNIT,
            caption: String::new(),
            effect_kernel: None,
        }
    }

    /// Return a copy of this segment with `effect_kernel` set — the immutable
    /// way the editor records an effect selection. An empty/whitespace id clears
    /// the effect (`None`) so a blank field round-trips to "no effect".
    pub fn with_effect_kernel(&self, kernel_id: impl AsRef<str>) -> Self {
        let trimmed = kernel_id.as_ref().trim();
        Segment {
            effect_kernel: (!trimmed.is_empty()).then(|| trimmed.to_owned()),
            ..self.clone()
        }
    }

    /// Length of the source span consumed, in ms (`0` if `out <= in`).
    pub fn span_ms(&self) -> u32 {
        self.source_out_ms.saturating_sub(self.source_in_ms)
    }

    /// Output duration of this segment after the speed change, in ms.
    ///
    /// `output = span * SPEED_UNIT / speed_milli`, rounded to nearest (all
    /// integer math). A 2.0× (`2000‰`) speed halves the span; 0.5× doubles it.
    pub fn output_ms(&self) -> u64 {
        let speed = if self.speed_milli == 0 {
            SPEED_UNIT
        } else {
            self.speed_milli
        };
        let numer = self.span_ms() as u64 * SPEED_UNIT as u64;
        // Round half-up without floats.
        (numer + speed as u64 / 2) / speed as u64
    }
}

impl TimelineExport {
    pub fn new() -> Self {
        TimelineExport::default()
    }

    /// Total output duration across all segments, in ms.
    pub fn output_ms(&self) -> u64 {
        self.segments.iter().map(Segment::output_ms).sum()
    }

    /// Validate the timeline the way the client editors gate the export button:
    /// at least one segment, every span positive, speed in range, overlay
    /// windows positive. Returns the *first* problem so the UI can focus it.
    pub fn validate(&self) -> Result<(), TimelineError> {
        if self.segments.is_empty() {
            return Err(TimelineError::Empty);
        }
        if self.segments.len() > MAX_SEGMENTS {
            return Err(TimelineError::TooManySegments {
                count: self.segments.len(),
            });
        }
        if self.overlays.len() > MAX_OVERLAYS {
            return Err(TimelineError::TooManyOverlays {
                count: self.overlays.len(),
            });
        }
        for (index, seg) in self.segments.iter().enumerate() {
            if seg.source_out_ms <= seg.source_in_ms {
                return Err(TimelineError::EmptySpan {
                    index,
                    in_ms: seg.source_in_ms,
                    out_ms: seg.source_out_ms,
                });
            }
            if seg.source_out_ms > MAX_SOURCE_MS {
                return Err(TimelineError::SourceOutOfRange {
                    index,
                    out_ms: seg.source_out_ms,
                });
            }
            if seg.span_ms() < MIN_SEGMENT_MS {
                return Err(TimelineError::SegmentTooShort {
                    index,
                    span_ms: seg.span_ms(),
                });
            }
            if seg.speed_milli < MIN_SPEED_MILLI || seg.speed_milli > MAX_SPEED_MILLI {
                return Err(TimelineError::SpeedOutOfRange {
                    index,
                    speed_milli: seg.speed_milli,
                });
            }
            if seg.caption.chars().count() > MAX_TEXT_CHARS {
                return Err(TimelineError::TextTooLong {
                    kind: "segment caption",
                    index,
                });
            }
            if seg
                .effect_kernel
                .as_deref()
                .is_some_and(|kernel| kernel.chars().count() > MAX_EFFECT_KERNEL_CHARS)
            {
                return Err(TimelineError::EffectKernelTooLong { index });
            }
        }
        let output_ms = self.output_ms();
        for (index, ov) in self.overlays.iter().enumerate() {
            if ov.end_ms <= ov.start_ms {
                return Err(TimelineError::OverlayWindow {
                    index,
                    start_ms: ov.start_ms,
                    end_ms: ov.end_ms,
                });
            }
            if ov.text.chars().count() > MAX_TEXT_CHARS {
                return Err(TimelineError::TextTooLong {
                    kind: "overlay",
                    index,
                });
            }
            if ov.end_ms as u64 > output_ms {
                return Err(TimelineError::OverlayPastOutput {
                    index,
                    end_ms: ov.end_ms,
                    output_ms,
                });
            }
        }
        Ok(())
    }

    /// Serialize to the exact JSON body shape the backend timeline-export
    /// endpoint accepts (speed as a float multiplier, seconds for overlays),
    /// so `rf-sync` can POST it unchanged.
    pub fn to_request_json(&self) -> Result<String, serde_json::Error> {
        let segments: Vec<_> = self
            .segments
            .iter()
            .map(|s| {
                let effect = match s.effect_kernel.as_deref().map(str::trim) {
                    Some(kernel) if !kernel.is_empty() => {
                        serde_json::Value::String(kernel.to_owned())
                    }
                    _ => serde_json::Value::Null,
                };
                serde_json::json!({
                    "source_in": s.source_in_ms as f64 / 1000.0,
                    "source_out": s.source_out_ms as f64 / 1000.0,
                    "speed": s.speed_milli as f64 / SPEED_UNIT as f64,
                    "caption": if s.caption.is_empty() { serde_json::Value::Null } else { serde_json::Value::String(s.caption.clone()) },
                    "effect": effect,
                })
            })
            .collect();
        let overlays: Vec<_> = self
            .overlays
            .iter()
            .filter(|o| !o.text.trim().is_empty())
            .map(|o| {
                serde_json::json!({
                    "text": o.text.trim(),
                    "start_s": o.start_ms as f64 / 1000.0,
                    "end_s": o.end_ms as f64 / 1000.0,
                    "position": o.position,
                })
            })
            .collect();
        let mut body = serde_json::Map::new();
        body.insert("segments".into(), serde_json::Value::Array(segments));
        if !overlays.is_empty() {
            body.insert("overlays".into(), serde_json::Value::Array(overlays));
        }
        serde_json::to_string(&serde_json::Value::Object(body))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn output_ms_applies_speed() {
        // 6000ms span at 1.0× → 6000ms out.
        assert_eq!(Segment::new(0, 6000).output_ms(), 6000);
        // 6000ms span at 2.0× → 3000ms out.
        let mut fast = Segment::new(0, 6000);
        fast.speed_milli = 2000;
        assert_eq!(fast.output_ms(), 3000);
        // 6000ms span at 0.5× → 12000ms out.
        let mut slow = Segment::new(0, 6000);
        slow.speed_milli = 500;
        assert_eq!(slow.output_ms(), 12000);
    }

    #[test]
    fn output_ms_zero_speed_is_treated_as_unit() {
        let mut seg = Segment::new(0, 4000);
        seg.speed_milli = 0;
        assert_eq!(seg.output_ms(), 4000);
    }

    #[test]
    fn total_output_sums_segments() {
        let tl = TimelineExport {
            segments: vec![Segment::new(0, 3000), Segment::new(5000, 8000)],
            overlays: vec![],
        };
        assert_eq!(tl.output_ms(), 6000);
    }

    #[test]
    fn validate_rejects_empty() {
        assert_eq!(TimelineExport::new().validate(), Err(TimelineError::Empty));
    }

    #[test]
    fn validate_rejects_backwards_span() {
        let tl = TimelineExport {
            segments: vec![Segment::new(3000, 1000)],
            overlays: vec![],
        };
        assert!(matches!(
            tl.validate(),
            Err(TimelineError::EmptySpan { index: 0, .. })
        ));
    }

    #[test]
    fn validate_rejects_out_of_range_speed() {
        let mut seg = Segment::new(0, 1000);
        seg.speed_milli = 9000;
        let tl = TimelineExport {
            segments: vec![seg],
            overlays: vec![],
        };
        assert!(matches!(
            tl.validate(),
            Err(TimelineError::SpeedOutOfRange { index: 0, .. })
        ));
    }

    #[test]
    fn validate_mirrors_backend_source_and_text_bounds() {
        let too_short = TimelineExport {
            segments: vec![Segment::new(0, MIN_SEGMENT_MS - 1)],
            overlays: vec![],
        };
        assert!(matches!(
            too_short.validate(),
            Err(TimelineError::SegmentTooShort { index: 0, .. })
        ));

        let too_long = TimelineExport {
            segments: vec![Segment::new(0, MAX_SOURCE_MS + 1)],
            overlays: vec![],
        };
        assert!(matches!(
            too_long.validate(),
            Err(TimelineError::SourceOutOfRange { index: 0, .. })
        ));

        let long_caption = TimelineExport {
            segments: vec![Segment {
                caption: "x".repeat(MAX_TEXT_CHARS + 1),
                ..Segment::new(0, 1000)
            }],
            overlays: vec![],
        };
        assert!(matches!(
            long_caption.validate(),
            Err(TimelineError::TextTooLong {
                kind: "segment caption",
                index: 0
            })
        ));
    }

    #[test]
    fn validate_mirrors_backend_collection_caps() {
        let too_many_segments = TimelineExport {
            segments: vec![Segment::new(0, 1000); MAX_SEGMENTS + 1],
            overlays: vec![],
        };
        assert_eq!(
            too_many_segments.validate(),
            Err(TimelineError::TooManySegments {
                count: MAX_SEGMENTS + 1
            })
        );

        let too_many_overlays = TimelineExport {
            segments: vec![Segment::new(0, 1000)],
            overlays: vec![
                Overlay {
                    text: "label".into(),
                    start_ms: 0,
                    end_ms: 100,
                    position: OverlayPosition::Bottom,
                };
                MAX_OVERLAYS + 1
            ],
        };
        assert_eq!(
            too_many_overlays.validate(),
            Err(TimelineError::TooManyOverlays {
                count: MAX_OVERLAYS + 1
            })
        );
    }

    #[test]
    fn validate_rejects_overlay_past_computed_output() {
        let timeline = TimelineExport {
            segments: vec![Segment::new(0, 1000)],
            overlays: vec![Overlay {
                text: "late".into(),
                start_ms: 900,
                end_ms: 1100,
                position: OverlayPosition::Bottom,
            }],
        };
        assert!(matches!(
            timeline.validate(),
            Err(TimelineError::OverlayPastOutput { index: 0, .. })
        ));
    }

    #[test]
    fn validate_rejects_backwards_overlay() {
        let tl = TimelineExport {
            segments: vec![Segment::new(0, 1000)],
            overlays: vec![Overlay {
                text: "hi".into(),
                start_ms: 900,
                end_ms: 400,
                position: OverlayPosition::Top,
            }],
        };
        assert!(matches!(
            tl.validate(),
            Err(TimelineError::OverlayWindow { index: 0, .. })
        ));
    }

    #[test]
    fn request_json_shapes_body_for_backend() {
        let tl = TimelineExport {
            segments: vec![Segment {
                source_in_ms: 0,
                source_out_ms: 2000,
                speed_milli: 2000,
                caption: "hook".into(),
                effect_kernel: Some("push-in".into()),
            }],
            overlays: vec![Overlay {
                text: "  buy now ".into(),
                start_ms: 0,
                end_ms: 3000,
                position: OverlayPosition::Bottom,
            }],
        };
        let json = tl.to_request_json().unwrap();
        let v: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(v["segments"][0]["source_out"], 2.0);
        assert_eq!(v["segments"][0]["speed"], 2.0);
        assert_eq!(v["segments"][0]["caption"], "hook");
        assert_eq!(v["segments"][0]["effect"], "push-in");
        assert_eq!(v["overlays"][0]["text"], "buy now"); // trimmed
        assert_eq!(v["overlays"][0]["start_s"], 0.0);
        assert_eq!(v["overlays"][0]["position"], "bottom");
    }

    #[test]
    fn request_json_preserves_visible_segment_order() {
        let timeline = TimelineExport {
            segments: vec![
                Segment {
                    caption: "first".into(),
                    ..Segment::new(5_000, 6_000)
                },
                Segment {
                    caption: "second".into(),
                    ..Segment::new(1_000, 2_000)
                },
            ],
            overlays: vec![],
        };
        let value: serde_json::Value =
            serde_json::from_str(&timeline.to_request_json().unwrap()).unwrap();
        assert_eq!(value["segments"][0]["source_in"], 5.0);
        assert_eq!(value["segments"][0]["caption"], "first");
        assert_eq!(value["segments"][1]["source_in"], 1.0);
        assert_eq!(value["segments"][1]["caption"], "second");
    }

    #[test]
    fn empty_caption_serializes_as_null() {
        let tl = TimelineExport {
            segments: vec![Segment::new(0, 1000)],
            overlays: vec![],
        };
        let v: serde_json::Value = serde_json::from_str(&tl.to_request_json().unwrap()).unwrap();
        assert!(v["segments"][0]["caption"].is_null());
        // A segment with no effect exports a null effect field.
        assert!(v["segments"][0]["effect"].is_null());
        // No overlays key when there are none.
        assert!(v.get("overlays").is_none());
    }

    #[test]
    fn effect_kernel_survives_export_and_bundle_roundtrip() {
        let segment = Segment::new(0, 2000).with_effect_kernel("push-in");
        assert_eq!(segment.effect_kernel.as_deref(), Some("push-in"));
        let tl = TimelineExport {
            segments: vec![segment.clone()],
            overlays: vec![],
        };
        // Survives the backend timeline-export request body.
        let request: serde_json::Value =
            serde_json::from_str(&tl.to_request_json().unwrap()).unwrap();
        assert_eq!(request["segments"][0]["effect"], "push-in");
        // Survives the on-disk bundle (serde) round-trip.
        let bundle = serde_json::to_string(&tl).unwrap();
        let back: TimelineExport = serde_json::from_str(&bundle).unwrap();
        assert_eq!(back, tl);
        assert_eq!(back.segments[0].effect_kernel.as_deref(), Some("push-in"));
    }

    #[test]
    fn with_effect_kernel_clears_on_blank_and_is_immutable() {
        let base = Segment::new(0, 2000);
        // Applying a whitespace-only id clears the effect.
        assert_eq!(base.with_effect_kernel("   ").effect_kernel, None);
        // Applying trims surrounding whitespace and does not mutate the original.
        let applied = base.with_effect_kernel("  shake  ");
        assert_eq!(applied.effect_kernel.as_deref(), Some("shake"));
        assert_eq!(base.effect_kernel, None);
    }

    #[test]
    fn legacy_segment_without_effect_defaults_to_none() {
        // A pre-effect bundle omits the field entirely; it must load as `None`.
        let seg: Segment =
            serde_json::from_str(r#"{"source_in_ms":0,"source_out_ms":1000}"#).unwrap();
        assert_eq!(seg.effect_kernel, None);
    }

    #[test]
    fn validate_rejects_overlong_effect_kernel() {
        let tl = TimelineExport {
            segments: vec![Segment::new(0, 1000)
                .with_effect_kernel("k".repeat(MAX_EFFECT_KERNEL_CHARS + 1))],
            overlays: vec![],
        };
        assert!(matches!(
            tl.validate(),
            Err(TimelineError::EffectKernelTooLong { index: 0 })
        ));
    }

    #[test]
    fn timeline_roundtrips_through_json() {
        let tl = TimelineExport {
            segments: vec![Segment {
                source_in_ms: 100,
                source_out_ms: 2500,
                speed_milli: 1500,
                caption: "x".into(),
                effect_kernel: Some("shake".into()),
            }],
            overlays: vec![Overlay {
                text: "t".into(),
                start_ms: 0,
                end_ms: 500,
                position: OverlayPosition::Center,
            }],
        };
        let json = serde_json::to_string(&tl).unwrap();
        let back: TimelineExport = serde_json::from_str(&json).unwrap();
        assert_eq!(tl, back);
    }
}
