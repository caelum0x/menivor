//! `rf-captions` — Rust port of `@reelforge/caption-engine` (golden-parity).
//!
//! Word timestamps → styled ASS subtitles. Byte-identical to the TypeScript
//! source and the Python port (golden `.ass` parity), so the caption preview
//! and the burned subtitle match exactly.
//!
//! Ported surface:
//! - [`CaptionStyle`] presets ([`get_preset`], [`list_presets`]) — mirror of `style.ts`.
//! - [`hex_to_ass`] — `#RRGGBB` → ASS `&HAABBGGRR` colour — mirror of `color.ts`.
//! - [`build_ass`] / [`format_time`] — ASS document assembly — mirror of `ass.ts`.
//!
//! Parity note: the upstream package contains no scoring / hashing / filtergraph
//! logic, so there is no `round6` or FNV-1a here. Integer math is used on every
//! duration / centisecond path exactly where the TypeScript uses it, and string
//! assembly is byte-identical.

use rf_project::{OverlayPosition, TimelineExport};
use serde::{Deserialize, Serialize};

/// ASS canvas width (matches the TS `PLAY_RES_X`).
pub const PLAY_RES_X: u32 = 1080;
/// ASS canvas height (matches the TS `PLAY_RES_Y`).
pub const PLAY_RES_Y: u32 = 1920;

const STYLE_FORMAT: &str = "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding";
const EVENT_FORMAT: &str =
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text";

/// A single timestamped word (mirror of the TS `Word` interface).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Word {
    pub text: String,
    pub start: f64,
    pub end: f64,
}

/// Caption style / preset (mirror of the TS `CaptionStyle` interface).
///
/// Field names match the TS/Python snake_case JSON exactly.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct CaptionStyle {
    pub font: String,
    pub size: f64,
    pub primary_hex: String,
    pub highlight_hex: String,
    pub outline_hex: String,
    pub outline: f64,
    pub shadow: f64,
    /// ASS numpad alignment.
    pub alignment: f64,
    pub margin_v: f64,
    pub bold: bool,
    pub uppercase: bool,
    pub words_per_group: f64,
}

/// The `hormozi` base preset — every other preset is a spread-override of it.
fn hormozi() -> CaptionStyle {
    CaptionStyle {
        font: "Montserrat Black".to_string(),
        size: 120.0,
        primary_hex: "#FFFFFF".to_string(),
        highlight_hex: "#FFD93D".to_string(),
        outline_hex: "#000000".to_string(),
        outline: 4.0,
        shadow: 2.0,
        alignment: 5.0,
        margin_v: 0.0,
        bold: true,
        uppercase: true,
        words_per_group: 2.0,
    }
}

/// Sorted list of preset names (matches JS `Object.keys(PRESETS).sort()`).
const PRESET_NAMES: [&str; 4] = [
    "brainrot-popin",
    "hormozi",
    "karaoke-classic",
    "minimal-top-label",
];

fn preset(name: &str) -> Option<CaptionStyle> {
    match name {
        "hormozi" => Some(hormozi()),
        "karaoke-classic" => Some(CaptionStyle {
            font: "Arial".to_string(),
            size: 90.0,
            highlight_hex: "#35D9FF".to_string(),
            alignment: 2.0,
            margin_v: 120.0,
            uppercase: false,
            words_per_group: 4.0,
            ..hormozi()
        }),
        "minimal-top-label" => Some(CaptionStyle {
            font: "Helvetica".to_string(),
            size: 64.0,
            highlight_hex: "#FFFFFF".to_string(),
            outline: 2.0,
            shadow: 1.0,
            alignment: 8.0,
            margin_v: 120.0,
            bold: false,
            uppercase: false,
            words_per_group: 1.0,
            ..hormozi()
        }),
        "brainrot-popin" => Some(CaptionStyle {
            font: "Impact".to_string(),
            size: 140.0,
            highlight_hex: "#39FF14".to_string(),
            outline: 6.0,
            shadow: 0.0,
            alignment: 5.0,
            words_per_group: 2.0,
            ..hormozi()
        }),
        _ => None,
    }
}

/// Look up a preset by name. `Err` mirrors the TS `throw` on an unknown preset.
pub fn get_preset(name: &str) -> Result<CaptionStyle, String> {
    preset(name).ok_or_else(|| format!("unknown caption preset {name}"))
}

/// Sorted preset names (mirror of TS `listPresets`).
pub fn list_presets() -> Vec<String> {
    let mut names: Vec<String> = PRESET_NAMES.iter().map(|s| s.to_string()).collect();
    names.sort();
    names
}

/// Hex → ASS `&HAABBGGRR` colour (mirror of `color.ts`). Alpha `0` = opaque.
///
/// `Err` mirrors the TS `throw` when the hex is not `#RRGGBB` / `RRGGBB`.
pub fn hex_to_ass(hex_color: &str, alpha: i64) -> Result<String, String> {
    let h = hex_color.strip_prefix('#').unwrap_or(hex_color);
    if h.len() != 6 {
        return Err(format!("expected #RRGGBB, got {hex_color}"));
    }
    let parse = |slice: &str| -> Result<u8, String> {
        u8::from_str_radix(slice, 16).map_err(|_| format!("expected #RRGGBB, got {hex_color}"))
    };
    let rr = parse(&h[0..2])?;
    let gg = parse(&h[2..4])?;
    let bb = parse(&h[4..6])?;
    let a = alpha.clamp(0, 255) as u8;
    Ok(format!("&H{a:02X}{bb:02X}{gg:02X}{rr:02X}"))
}

/// JS `Math.round` semantics: round half toward +∞ (== half-away-from-zero for
/// the non-negative inputs used here).
fn js_round(x: f64) -> f64 {
    (x + 0.5).floor()
}

/// Seconds → ASS `H:MM:SS.cc` (mirror of TS `formatTime`).
pub fn format_time(seconds: f64) -> String {
    let cs_total = js_round(seconds.max(0.0) * 100.0) as i64;
    let h = cs_total / 360_000;
    let m = (cs_total % 360_000) / 6_000;
    let s = (cs_total % 6_000) / 100;
    let cs = cs_total % 100;
    format!("{h}:{m:02}:{s:02}.{cs:02}")
}

fn style_line(style: &CaptionStyle) -> String {
    let bold = if style.bold { -1 } else { 0 };
    // Presets carry valid `#RRGGBB` hex; a caller-supplied invalid hex is a
    // programming error, mirroring the TS `throw` inside `hexToAss`.
    let primary = hex_to_ass(&style.primary_hex, 0).expect("invalid primary_hex");
    let highlight = hex_to_ass(&style.highlight_hex, 0).expect("invalid highlight_hex");
    let outline = hex_to_ass(&style.outline_hex, 0).expect("invalid outline_hex");
    format!(
        "Style: Default,{font},{size},{primary},{highlight},{outline},&H00000000,{bold},0,0,0,100,100,0,0,1,{outline_n},{shadow},{alignment},60,60,{margin_v},1",
        font = style.font,
        size = style.size,
        outline_n = style.outline,
        shadow = style.shadow,
        alignment = style.alignment,
        margin_v = style.margin_v,
    )
}

fn dialogue_line(group: &[Word], style: &CaptionStyle) -> String {
    let start = format_time(group[0].start);
    let end = format_time(group[group.len() - 1].end);
    let parts: Vec<String> = group
        .iter()
        .map(|w| {
            let dur_cs = js_round((w.end - w.start) * 100.0).max(0.0) as i64;
            let text = if style.uppercase {
                w.text.to_uppercase()
            } else {
                w.text.clone()
            };
            format!("{{\\k{dur_cs}}}{text}")
        })
        .collect();
    format!(
        "Dialogue: 0,{start},{end},Default,,0,0,0,,{}",
        parts.join(" ")
    )
}

/// Build a complete ASS document from word timestamps + a style.
///
/// `style == None` uses the `hormozi` preset (mirror of TS `buildAss` default).
pub fn build_ass(words: &[Word], style: Option<&CaptionStyle>) -> String {
    let default_style;
    let s = match style {
        Some(s) => s,
        None => {
            default_style = hormozi();
            &default_style
        }
    };
    let size = (s.words_per_group.trunc() as i64).max(1) as usize;

    let mut lines: Vec<String> = vec![
        "[Script Info]".to_string(),
        "ScriptType: v4.00+".to_string(),
        format!("PlayResX: {PLAY_RES_X}"),
        format!("PlayResY: {PLAY_RES_Y}"),
        String::new(),
        "[V4+ Styles]".to_string(),
        STYLE_FORMAT.to_string(),
        style_line(s),
        String::new(),
        "[Events]".to_string(),
        EVENT_FORMAT.to_string(),
    ];

    let mut i = 0;
    while i < words.len() {
        let group = &words[i..(i + size).min(words.len())];
        if !group.is_empty() {
            lines.push(dialogue_line(group, s));
        }
        i += size;
    }
    let mut out = lines.join("\n");
    out.push('\n');
    out
}

/// Build the deterministic subtitle layer for a non-destructive desktop EDL.
/// Segment captions occupy their segment's output window after speed changes;
/// overlays use their explicit output-clock windows and position.
pub fn build_timeline_ass(timeline: &TimelineExport) -> Result<Option<String>, String> {
    timeline
        .validate()
        .map_err(|error| format!("timeline captions are invalid: {error}"))?;
    let has_text = timeline
        .segments
        .iter()
        .any(|segment| !segment.caption.trim().is_empty())
        || timeline
            .overlays
            .iter()
            .any(|overlay| !overlay.text.trim().is_empty());
    if !has_text {
        return Ok(None);
    }

    let mut lines = vec![
        "[Script Info]".to_string(),
        "ScriptType: v4.00+".to_string(),
        format!("PlayResX: {PLAY_RES_X}"),
        format!("PlayResY: {PLAY_RES_Y}"),
        String::new(),
        "[V4+ Styles]".to_string(),
        STYLE_FORMAT.to_string(),
        "Style: Segment,Arial,72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,110,1".to_string(),
        "Style: OverlayTop,Arial,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,2,0,8,80,80,100,1".to_string(),
        "Style: OverlayCenter,Arial,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,2,0,5,80,80,0,1".to_string(),
        "Style: OverlayBottom,Arial,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,2,0,2,80,80,100,1".to_string(),
        String::new(),
        "[Events]".to_string(),
        EVENT_FORMAT.to_string(),
    ];
    let mut cursor_ms = 0_u64;
    for segment in &timeline.segments {
        let end_ms = cursor_ms + segment.output_ms();
        if !segment.caption.trim().is_empty() {
            lines.push(format!(
                "Dialogue: 0,{},{},Segment,,0,0,0,,{}",
                format_time(cursor_ms as f64 / 1000.0),
                format_time(end_ms as f64 / 1000.0),
                escape_ass_text(segment.caption.trim()),
            ));
        }
        cursor_ms = end_ms;
    }
    for overlay in &timeline.overlays {
        if overlay.text.trim().is_empty() {
            continue;
        }
        let style = match overlay.position {
            OverlayPosition::Top => "OverlayTop",
            OverlayPosition::Center => "OverlayCenter",
            OverlayPosition::Bottom => "OverlayBottom",
        };
        lines.push(format!(
            "Dialogue: 1,{},{},{style},,0,0,0,,{}",
            format_time(overlay.start_ms as f64 / 1000.0),
            format_time(overlay.end_ms as f64 / 1000.0),
            escape_ass_text(overlay.text.trim()),
        ));
    }
    let mut output = lines.join("\n");
    output.push('\n');
    Ok(Some(output))
}

fn escape_ass_text(text: &str) -> String {
    text.replace('\\', r"\\")
        .replace('{', r"\{")
        .replace('}', r"\}")
        .replace("\r\n", r"\N")
        .replace(['\r', '\n'], r"\N")
}

#[cfg(test)]
mod tests {
    use super::*;
    use rf_project::{Overlay, OverlayPosition, Segment, TimelineExport};

    fn sample_words() -> Vec<Word> {
        [
            ("make", 0.0, 0.32),
            ("your", 0.32, 0.58),
            ("first", 0.58, 0.91),
            ("viral", 0.91, 1.4),
            ("reel", 1.4, 1.85),
            ("today", 1.85, 2.4),
        ]
        .iter()
        .map(|(t, s, e)| Word {
            text: t.to_string(),
            start: *s,
            end: *e,
        })
        .collect()
    }

    #[test]
    fn hex_to_ass_basic() {
        assert_eq!(hex_to_ass("#FFFFFF", 0).unwrap(), "&H00FFFFFF");
        assert_eq!(hex_to_ass("#FFD93D", 0).unwrap(), "&H003DD9FF");
        assert_eq!(hex_to_ass("#35D9FF", 0).unwrap(), "&H00FFD935");
        assert_eq!(hex_to_ass("#39FF14", 0).unwrap(), "&H0014FF39");
        assert_eq!(hex_to_ass("#000000", 0).unwrap(), "&H00000000");
    }

    #[test]
    fn hex_to_ass_no_prefix_and_alpha_clamp() {
        assert_eq!(hex_to_ass("FFFFFF", 0).unwrap(), "&H00FFFFFF");
        // alpha clamps to [0, 255].
        assert_eq!(hex_to_ass("#000000", 300).unwrap(), "&HFF000000");
        assert_eq!(hex_to_ass("#000000", -5).unwrap(), "&H00000000");
        assert_eq!(hex_to_ass("#000000", 128).unwrap(), "&H80000000");
    }

    #[test]
    fn hex_to_ass_invalid() {
        assert!(hex_to_ass("#FFF", 0).is_err());
        assert!(hex_to_ass("#GGGGGG", 0).is_err());
    }

    #[test]
    fn format_time_cases() {
        assert_eq!(format_time(0.0), "0:00:00.00");
        assert_eq!(format_time(0.58), "0:00:00.58");
        assert_eq!(format_time(2.4), "0:00:02.40");
        assert_eq!(format_time(61.5), "0:01:01.50");
        assert_eq!(format_time(3661.0), "1:01:01.00");
        // negative clamps to zero.
        assert_eq!(format_time(-5.0), "0:00:00.00");
    }

    #[test]
    fn list_presets_sorted() {
        assert_eq!(
            list_presets(),
            vec![
                "brainrot-popin",
                "hormozi",
                "karaoke-classic",
                "minimal-top-label",
            ]
        );
    }

    #[test]
    fn get_preset_unknown_errors() {
        assert!(get_preset("nope").is_err());
        assert!(get_preset("hormozi").is_ok());
    }

    #[test]
    fn build_ass_hormozi_golden() {
        let expected = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Montserrat Black,120,&H00FFFFFF,&H003DD9FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,2,5,60,60,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:00.58,Default,,0,0,0,,{\\k32}MAKE {\\k26}YOUR\nDialogue: 0,0:00:00.58,0:00:01.40,Default,,0,0,0,,{\\k33}FIRST {\\k49}VIRAL\nDialogue: 0,0:00:01.40,0:00:02.40,Default,,0,0,0,,{\\k45}REEL {\\k55}TODAY\n";
        let style = get_preset("hormozi").unwrap();
        assert_eq!(build_ass(&sample_words(), Some(&style)), expected);
        // Default (None) is the hormozi preset.
        assert_eq!(build_ass(&sample_words(), None), expected);
    }

    #[test]
    fn build_ass_karaoke_golden() {
        let expected = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,90,&H00FFFFFF,&H00FFD935,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,2,2,60,60,120,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:01.40,Default,,0,0,0,,{\\k32}make {\\k26}your {\\k33}first {\\k49}viral\nDialogue: 0,0:00:01.40,0:00:02.40,Default,,0,0,0,,{\\k45}reel {\\k55}today\n";
        let style = get_preset("karaoke-classic").unwrap();
        assert_eq!(build_ass(&sample_words(), Some(&style)), expected);
    }

    #[test]
    fn build_ass_minimal_golden() {
        let expected = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Helvetica,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,8,60,60,120,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:00.32,Default,,0,0,0,,{\\k32}make\nDialogue: 0,0:00:00.32,0:00:00.58,Default,,0,0,0,,{\\k26}your\nDialogue: 0,0:00:00.58,0:00:00.91,Default,,0,0,0,,{\\k33}first\nDialogue: 0,0:00:00.91,0:00:01.40,Default,,0,0,0,,{\\k49}viral\nDialogue: 0,0:00:01.40,0:00:01.85,Default,,0,0,0,,{\\k45}reel\nDialogue: 0,0:00:01.85,0:00:02.40,Default,,0,0,0,,{\\k55}today\n";
        let style = get_preset("minimal-top-label").unwrap();
        assert_eq!(build_ass(&sample_words(), Some(&style)), expected);
    }

    #[test]
    fn build_ass_brainrot_golden() {
        let expected = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Impact,140,&H00FFFFFF,&H0014FF39,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,6,0,5,60,60,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:00.58,Default,,0,0,0,,{\\k32}MAKE {\\k26}YOUR\nDialogue: 0,0:00:00.58,0:00:01.40,Default,,0,0,0,,{\\k33}FIRST {\\k49}VIRAL\nDialogue: 0,0:00:01.40,0:00:02.40,Default,,0,0,0,,{\\k45}REEL {\\k55}TODAY\n";
        let style = get_preset("brainrot-popin").unwrap();
        assert_eq!(build_ass(&sample_words(), Some(&style)), expected);
    }

    #[test]
    fn build_ass_empty_words() {
        let expected = "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Montserrat Black,120,&H00FFFFFF,&H003DD9FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,2,5,60,60,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n";
        assert_eq!(build_ass(&[], None), expected);
    }

    #[test]
    fn timeline_ass_uses_speed_adjusted_segment_windows_and_overlay_positions() {
        let timeline = TimelineExport {
            segments: vec![
                Segment {
                    source_in_ms: 0,
                    source_out_ms: 2_000,
                    speed_milli: 2_000,
                    caption: "first {safe}".into(),
                    effect_kernel: None,
                },
                Segment {
                    source_in_ms: 5_000,
                    source_out_ms: 6_000,
                    speed_milli: 1_000,
                    caption: "second".into(),
                    effect_kernel: None,
                },
            ],
            overlays: vec![Overlay {
                text: "top\\label".into(),
                start_ms: 250,
                end_ms: 1_750,
                position: OverlayPosition::Top,
            }],
        };
        let ass = build_timeline_ass(&timeline).unwrap().unwrap();
        assert!(ass.contains(r"Dialogue: 0,0:00:00.00,0:00:01.00,Segment,,0,0,0,,first \{safe\}"));
        assert!(ass.contains("Dialogue: 0,0:00:01.00,0:00:02.00,Segment,,0,0,0,,second"));
        assert!(ass.contains(r"Dialogue: 1,0:00:00.25,0:00:01.75,OverlayTop,,0,0,0,,top\\label"));
    }

    #[test]
    fn timeline_ass_is_absent_when_no_caption_or_overlay_text_exists() {
        let timeline = TimelineExport {
            segments: vec![Segment::new(0, 1_000)],
            overlays: vec![],
        };
        assert_eq!(build_timeline_ass(&timeline).unwrap(), None);
    }
}
