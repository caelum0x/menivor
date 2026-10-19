//! `rf-render-core` — the desktop Rust port of `@reelforge/render-core`: a
//! declarative `RenderSpec` → FFmpeg `-filter_complex` builder, byte-identical
//! to the TS/Python ports (asserted against their shared golden fixtures). Pure,
//! deterministic string assembly with stable pad labels; no I/O.
//!
//! The composition graph (up to the `[comp]` sink) and the ducked-audio graph
//! (`[aout]`) are reproduced byte-for-byte from the executor
//! (`app/services/compose/compose_ffmpeg.py`). The executor's environment-specific
//! caption-burn / watermark nodes (which escape an absolute path + embed the
//! render-time font dir) live past `[comp]` and are intentionally not modelled
//! here. Chroma / PiP diameter / margin / loudnorm are the executor's shipping
//! defaults, baked as constants (no locale-sensitive float formatting).

use serde::Deserialize;

/// Output frame geometry.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Output {
    pub width: i64,
    pub height: i64,
    pub fps: i64,
}

/// Green-screen avatar overlay input + circular-badge geometry.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Avatar {
    pub input: i64,
    #[serde(default)]
    pub diameter: Option<i64>,
    #[serde(default)]
    pub margin: Option<i64>,
}

/// Audio mix inputs. `bgm` present triggers the ducked + loudnorm graph.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Audio {
    pub narration: i64,
    #[serde(default)]
    pub bgm: Option<i64>,
}

/// A declarative render specification.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct RenderSpec {
    pub output: Output,
    #[serde(default)]
    pub layout: Option<String>,
    #[serde(default)]
    pub avatar: Option<Avatar>,
    #[serde(default)]
    pub caption_ass: Option<String>,
    #[serde(default)]
    pub audio: Option<Audio>,
}

// Constants — each mirrors a compose_ffmpeg default (see filtergraph.py).
const CHROMA: &str = "chromakey=0x00FF00:0.18:0.1";
const DUCK: &str = "sidechaincompress=threshold=0.03:ratio=8:attack=5:release=250";
const LOUDNORM: &str = "loudnorm=I=-14:TP=-1:LRA=11";
const PIP_DIAMETER: i64 = 480;
const PIP_MARGIN: i64 = 48;
const HOOK: &str = "3";

const AVATAR_LAYOUTS: [&str; 3] = ["pip", "split", "hook_intro"];

struct ResolvedAvatar {
    input: i64,
    diameter: i64,
    margin: i64,
}

fn resolve_avatar(spec: &RenderSpec) -> ResolvedAvatar {
    match &spec.avatar {
        Some(av) => ResolvedAvatar {
            input: av.input,
            diameter: av.diameter.unwrap_or(PIP_DIAMETER),
            margin: av.margin.unwrap_or(PIP_MARGIN),
        },
        None => ResolvedAvatar {
            input: 1,
            diameter: PIP_DIAMETER,
            margin: PIP_MARGIN,
        },
    }
}

fn circle_geq(radius: i64) -> String {
    format!(
        "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':\
         a='if(lte(hypot(X-{radius},Y-{radius}),{radius}),alpha(X,Y),0)'"
    )
}

fn layout_base(w: i64, h: i64) -> String {
    format!(
        "[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[comp]"
    )
}

fn layout_pip(w: i64, h: i64, av: &ResolvedAvatar) -> String {
    let d = av.diameter;
    let radius = d / 2;
    let ai = av.input;
    let x = (w - d - av.margin).max(0);
    let y = (h - d - av.margin).max(0);
    [
        format!(
            "[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[bg]"
        ),
        format!(
            "[{ai}:v]{CHROMA},scale={d}:{d}:force_original_aspect_ratio=increase,\
             crop={d}:{d},format=rgba,{}[av]",
            circle_geq(radius)
        ),
        format!("[bg][av]overlay=x={x}:y={y}:format=auto[comp]"),
    ]
    .join(";")
}

fn layout_split(w: i64, h: i64, av: &ResolvedAvatar) -> String {
    let half = h / 2;
    let ai = av.input;
    [
        format!(
            "[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},\
             setsar=1,split=2[s_top][s_bot]"
        ),
        format!("[s_top]crop={w}:{half}:0:0[top]"),
        format!("[s_bot]crop={w}:{half}:0:{half}[botbg]"),
        format!(
            "[{ai}:v]{CHROMA},scale={w}:{half}:force_original_aspect_ratio=increase,\
             crop={w}:{half},setsar=1,format=rgba[botfg]"
        ),
        "[botbg][botfg]overlay=0:0:format=auto[bot]".to_string(),
        "[top][bot]vstack=inputs=2[comp]".to_string(),
    ]
    .join(";")
}

fn layout_hook_intro(w: i64, h: i64, av: &ResolvedAvatar) -> String {
    let d = av.diameter;
    let radius = d / 2;
    let ai = av.input;
    let x = (w - d - av.margin).max(0);
    let y = (h - d - av.margin).max(0);
    [
        format!(
            "[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[bg]"
        ),
        format!("[{ai}:v]{CHROMA},format=rgba,split=2[a_raw][b_raw]"),
        format!(
            "[a_raw]scale={w}:{h}:force_original_aspect_ratio=increase,\
             crop={w}:{h},setsar=1[a_full]"
        ),
        format!(
            "[b_raw]scale={d}:{d}:force_original_aspect_ratio=increase,crop={d}:{d},{}[a_pip]",
            circle_geq(radius)
        ),
        format!("[bg][a_full]overlay=0:0:format=auto:enable='lt(t,{HOOK})'[tmp]"),
        format!("[tmp][a_pip]overlay=x={x}:y={y}:format=auto:enable='gte(t,{HOOK})'[comp]"),
    ]
    .join(";")
}

/// Build the composition graph (video only, terminating in `[comp]`).
pub fn build_video_graph(spec: &RenderSpec) -> String {
    let w = spec.output.width;
    let h = spec.output.height;
    match spec.layout.as_deref() {
        Some("pip") => layout_pip(w, h, &resolve_avatar(spec)),
        Some("split") => layout_split(w, h, &resolve_avatar(spec)),
        Some("hook_intro") => layout_hook_intro(w, h, &resolve_avatar(spec)),
        _ => layout_base(w, h),
    }
}

/// Build the ducked-music + loudnorm audio graph (or `""` when no bgm).
pub fn build_audio_graph(spec: &RenderSpec) -> String {
    let Some(audio) = &spec.audio else {
        return String::new();
    };
    let Some(bgm) = audio.bgm else {
        return String::new();
    };
    let nar = audio.narration;
    [
        format!("[{nar}:a]asplit=2[vo][vo_key]"),
        format!("[{bgm}:a][vo_key]{DUCK}[duck]"),
        "[vo][duck]amix=inputs=2:duration=first:dropout_transition=0[premix]".to_string(),
        format!("[premix]{LOUDNORM}[aout]"),
    ]
    .join(";")
}

/// Build the FFmpeg `-filter_complex` string for a spec (deterministic).
pub fn build_filtergraph(spec: &RenderSpec) -> String {
    let mut parts = vec![build_video_graph(spec)];
    let audio = build_audio_graph(spec);
    if !audio.is_empty() {
        parts.push(audio);
    }
    parts.join(";")
}

/// The composition video sink to continue from (always `[comp]`); the executor
/// appends its environment-specific caption / watermark finishing after this.
pub fn video_out_label(_spec: &RenderSpec) -> String {
    "[comp]".to_string()
}

/// Whether the spec produces a mixed audio pad (`[aout]`).
pub fn has_audio_out(spec: &RenderSpec) -> bool {
    spec.audio.as_ref().map(|a| a.bgm.is_some()).unwrap_or(false)
}

/// Options for [`make_spec`] (mirror of the TS `MakeSpecOptions`).
#[derive(Debug, Clone, Default)]
pub struct MakeSpecOptions {
    pub width: Option<i64>,
    pub height: Option<i64>,
    pub fps: Option<i64>,
    pub layout: Option<String>,
    pub avatar_input: Option<i64>,
    pub diameter: Option<i64>,
    pub margin: Option<i64>,
    pub caption_ass: Option<String>,
    pub narration: Option<i64>,
    pub bgm: Option<i64>,
}

/// Build a `RenderSpec` from options, with the same defaults as the TS port.
pub fn make_spec(opts: &MakeSpecOptions) -> RenderSpec {
    let layout = opts
        .layout
        .clone()
        .unwrap_or_else(|| "captions_only".to_string());
    let is_avatar = AVATAR_LAYOUTS.contains(&layout.as_str());
    let avatar = if is_avatar {
        Some(Avatar {
            input: opts.avatar_input.unwrap_or(1),
            diameter: Some(opts.diameter.unwrap_or(PIP_DIAMETER)),
            margin: Some(opts.margin.unwrap_or(PIP_MARGIN)),
        })
    } else {
        opts.avatar_input.map(|input| Avatar {
            input,
            diameter: Some(opts.diameter.unwrap_or(PIP_DIAMETER)),
            margin: Some(opts.margin.unwrap_or(PIP_MARGIN)),
        })
    };
    let audio = opts.narration.map(|narration| Audio {
        narration,
        bgm: opts.bgm,
    });
    RenderSpec {
        output: Output {
            width: opts.width.unwrap_or(1080),
            height: opts.height.unwrap_or(1920),
            fps: opts.fps.unwrap_or(30),
        },
        layout: Some(layout),
        avatar,
        caption_ass: opts.caption_ass.clone().filter(|s| !s.is_empty()),
        audio,
    }
}

/// Return a list of invariant violations (empty = valid).
pub fn validate_spec(spec: &RenderSpec) -> Vec<String> {
    let mut errors = Vec::new();
    for (k, v) in [
        ("width", spec.output.width),
        ("height", spec.output.height),
        ("fps", spec.output.fps),
    ] {
        if v <= 0 {
            errors.push(format!("output.{k} must be a positive int"));
        }
    }

    let layout = spec.layout.as_deref().unwrap_or("captions_only");
    let known = layout == "captions_only" || AVATAR_LAYOUTS.contains(&layout);
    if !known {
        errors.push(format!("layout must be one of {AVATAR_LAYOUTS:?} or captions_only"));
    }
    if AVATAR_LAYOUTS.contains(&layout) && spec.avatar.is_none() {
        errors.push(format!("layout {layout} requires avatar.input (an int)"));
    }
    if let Some(av) = &spec.avatar {
        for (k, v) in [("diameter", av.diameter), ("margin", av.margin)] {
            if let Some(v) = v {
                if v < 0 {
                    errors.push(format!("avatar.{k} must be a non-negative int"));
                }
            }
        }
    }
    errors
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_render_core_golden_fixtures() {
        // TS = Python = Rust: assert every golden filtergraph the shared package
        // ships is reproduced exactly.
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../../../packages/render-core/test/fixtures/golden/filtergraphs.json"
        );
        let raw = std::fs::read_to_string(path).expect("golden fixtures readable");
        let cases: serde_json::Map<String, serde_json::Value> =
            serde_json::from_str(&raw).expect("golden json parses");
        assert!(!cases.is_empty(), "expected golden cases");
        for (name, case) in &cases {
            let spec: RenderSpec = serde_json::from_value(case["spec"].clone())
                .unwrap_or_else(|e| panic!("{name}: {e}"));
            let expected = case["filtergraph"].as_str().unwrap();
            assert_eq!(build_filtergraph(&spec), expected, "case {name}");
        }
    }

    #[test]
    fn make_spec_defaults_and_labels() {
        let spec = make_spec(&MakeSpecOptions::default());
        assert_eq!(
            spec.output,
            Output {
                width: 1080,
                height: 1920,
                fps: 30
            }
        );
        assert_eq!(spec.layout.as_deref(), Some("captions_only"));
        assert_eq!(video_out_label(&spec), "[comp]");
        assert!(!has_audio_out(&spec));
        assert!(validate_spec(&spec).is_empty());
    }

    #[test]
    fn base_cover_crop_has_setsar_like_executor() {
        let spec = make_spec(&MakeSpecOptions::default());
        assert!(build_video_graph(&spec).ends_with(",setsar=1[comp]"));
    }

    #[test]
    fn pip_is_circular_avatar_over_filled_screen() {
        let spec = make_spec(&MakeSpecOptions {
            layout: Some("pip".to_string()),
            avatar_input: Some(1),
            ..Default::default()
        });
        let fg = build_filtergraph(&spec);
        assert!(fg.contains("chromakey=0x00FF00:0.18:0.1"));
        assert!(fg.contains("geq=r='r(X,Y)'"));
        assert!(fg.ends_with("overlay=x=552:y=1392:format=auto[comp]"));
    }

    #[test]
    fn validate_flags_bad_geometry_and_missing_avatar() {
        let spec = make_spec(&MakeSpecOptions {
            width: Some(0),
            ..Default::default()
        });
        let errors = validate_spec(&spec);
        assert!(errors.iter().any(|e| e.contains("output.width")));

        // An avatar layout with no avatar input is invalid.
        let bad_pip = RenderSpec {
            output: Output {
                width: 1080,
                height: 1920,
                fps: 30,
            },
            layout: Some("pip".to_string()),
            avatar: None,
            caption_ass: None,
            audio: None,
        };
        assert!(validate_spec(&bad_pip)
            .iter()
            .any(|e| e.contains("avatar.input")));
    }
}
