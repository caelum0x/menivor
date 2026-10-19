//! Render-command assembly (`rf-render-cmd`) — the top of the desktop render
//! chain. Stitches the video filtergraph (`rf-compose`) and the audio chain
//! (`rf-audio`) into a single, runnable `ffmpeg` argument vector: inputs →
//! `-filter_complex` → stream maps → interchange-friendly encode → output.
//!
//! Pure argv assembly (no process spawn); the runtime executes the returned
//! command. Every filter node comes from the golden-parity crates, so the
//! command matches what the cloud would run for the same plan.

use rf_audio::{build_audio, AudioSpec};
use rf_compose::{compose, ComposeInputs};
use rf_hardware::{select_encoder, Capabilities, Encoder, Platform};
use rf_plan::RenderPlan;

/// Standard hardware-encoder bitrate ladder (kbps) — HW encoders use CBR-ish
/// bitrate rather than CRF.
const HW_BITRATE_KBPS: u32 = 8000;

/// The encode + audio + faststart tail, chosen by encoder: a hardware encoder
/// uses a bitrate target; software x264 uses CRF + preset.
fn encode_tail(encoder: Encoder, output_path: &str) -> Vec<String> {
    let mut tail: Vec<String> = vec!["-c:v".into(), encoder.ffmpeg_name().to_string()];
    if encoder.is_hardware() {
        tail.push("-b:v".into());
        tail.push(format!("{HW_BITRATE_KBPS}k"));
    } else {
        tail.push("-preset".into());
        tail.push("medium".into());
        tail.push("-crf".into());
        tail.push("21".into());
    }
    tail.extend([
        "-pix_fmt".into(),
        "yuv420p".into(),
        "-c:a".into(),
        "aac".into(),
        "-b:a".into(),
        "192k".into(),
        "-movflags".into(),
        "+faststart".into(),
        output_path.to_string(),
    ]);
    tail
}

/// The concrete files + options a render needs. Inputs are ordered
/// video(0), narration(1), and — when present — BGM(2).
#[derive(Debug, Clone)]
pub struct RenderRequest<'a> {
    pub video_path: &'a str,
    pub narration_path: &'a str,
    pub bgm_path: Option<&'a str>,
    /// Burned-caption `.ass` path (empty = no captions).
    pub ass_path: &'a str,
    pub fonts_dir: &'a str,
    pub output_path: &'a str,
    /// Duck the BGM under the narration (only applies when BGM is present).
    pub duck: bool,
}

/// Build the full `ffmpeg` argv for a reel from its plan + concrete inputs,
/// encoding with software x264 (`-crf 21 -preset medium`) — the portable,
/// interchange-friendly default that runs anywhere.
pub fn build_render_argv(plan: &RenderPlan, req: &RenderRequest) -> Vec<String> {
    build_with_encoder(plan, req, Encoder::Libx264)
}

/// Like [`build_render_argv`], but picks the best available **hardware** encoder
/// for `platform`/`caps` (falling back to software x264 when none is present),
/// exactly as `rf-encode` / the cloud renderer does. Hardware encoders target a
/// bitrate (`-b:v`) instead of CRF.
pub fn build_render_argv_hw(
    plan: &RenderPlan,
    req: &RenderRequest,
    platform: Platform,
    caps: &Capabilities,
) -> Vec<String> {
    build_with_encoder(plan, req, select_encoder(platform, caps))
}

/// The shared assembly core: inputs → `-filter_complex` → maps → encoder tail.
/// The only variation between the software and hardware entry points is the
/// chosen [`Encoder`], applied by [`encode_tail`].
fn build_with_encoder(plan: &RenderPlan, req: &RenderRequest, encoder: Encoder) -> Vec<String> {
    // Inputs: 0 = video, 1 = narration, [2 = bgm].
    let mut argv: Vec<String> = vec![
        "-y".into(),
        "-i".into(),
        req.video_path.to_string(),
        "-i".into(),
        req.narration_path.to_string(),
    ];
    let bgm_index = req.bgm_path.map(|bgm| {
        argv.push("-i".into());
        argv.push(bgm.to_string());
        2u32
    });

    let comp = compose(
        plan,
        &ComposeInputs {
            video_label: "0:v",
            ass_path: req.ass_path,
            fonts_dir: req.fonts_dir,
        },
    );
    let audio = build_audio(&AudioSpec {
        narration_input: 1,
        bgm_input: bgm_index,
        duck: req.duck,
    });

    // -filter_complex = video graph, then (if any) the audio graph.
    let mut fc = comp.filtergraph.clone();
    if audio.has_filter {
        if !fc.is_empty() {
            fc.push(';');
        }
        fc.push_str(&audio.filtergraph);
    }
    argv.push("-filter_complex".into());
    argv.push(fc);

    // Map the composed video pad + the audio pad. compose emits a bare label;
    // rf-audio emits an already-bracketed pad.
    argv.push("-map".into());
    argv.push(format!("[{}]", comp.output_label));
    argv.push("-map".into());
    argv.push(audio.output_label.clone());

    // Encoder-specific master tail (software CRF vs hardware bitrate) + audio.
    argv.extend(encode_tail(encoder, req.output_path));
    argv
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

    /// The value following the first occurrence of `flag`.
    fn val_after<'a>(argv: &'a [String], flag: &str) -> &'a str {
        let i = argv.iter().position(|a| a == flag).expect("flag present");
        argv.get(i + 1).expect("value after flag")
    }

    #[test]
    fn full_reel_captions_bgm_duck() {
        let known = rf_captions::list_presets().into_iter().next().unwrap();
        let argv = build_render_argv(
            &plan("9:16", &known),
            &RenderRequest {
                video_path: "in.mp4",
                narration_path: "nar.wav",
                bgm_path: Some("bgm.mp3"),
                ass_path: "/tmp/c.ass",
                fonts_dir: "/fonts",
                output_path: "out.mp4",
                duck: true,
            },
        );
        // Three inputs in order.
        let inputs: Vec<&String> = argv
            .iter()
            .enumerate()
            .filter(|(i, a)| *a == "-i" || (*i > 0 && argv[i - 1] == "-i"))
            .filter(|(_, a)| *a != "-i")
            .map(|(_, a)| a)
            .collect();
        assert_eq!(inputs, vec!["in.mp4", "nar.wav", "bgm.mp3"]);

        let fc = val_after(&argv, "-filter_complex");
        assert!(fc.contains("scale=1080:1920"));
        assert!(fc.contains("ass="));
        assert!(fc.contains("sidechaincompress"));
        assert!(fc.contains("amix=inputs=2:duration=first[aout]"));

        // Maps: composed video pad + mixed audio pad.
        assert!(argv.windows(2).any(|w| w[0] == "-map" && w[1] == "[final]"));
        assert!(argv.windows(2).any(|w| w[0] == "-map" && w[1] == "[aout]"));
        assert_eq!(argv.last().unwrap(), "out.mp4");
        assert!(argv.contains(&"+faststart".to_string()));
    }

    #[test]
    fn software_default_uses_crf_not_bitrate() {
        let argv = build_render_argv(
            &plan("9:16", "___nope___"),
            &RenderRequest {
                video_path: "in.mp4",
                narration_path: "nar.wav",
                bgm_path: None,
                ass_path: "",
                fonts_dir: "/fonts",
                output_path: "out.mp4",
                duck: false,
            },
        );
        assert!(argv.windows(2).any(|w| w[0] == "-c:v" && w[1] == "libx264"));
        assert_eq!(val_after(&argv, "-crf"), "21");
        assert_eq!(val_after(&argv, "-preset"), "medium");
        assert!(!argv.contains(&"-b:v".to_string()));
    }

    #[test]
    fn hw_variant_uses_gpu_encoder_and_bitrate() {
        use rf_hardware::{Capabilities, Platform};
        // A Mac with VideoToolbox → hardware H.264, bitrate-targeted.
        let caps = Capabilities {
            videotoolbox: true,
            nvenc: false,
            qsv: false,
            vaapi: false,
            amf: false,
        };
        let req = RenderRequest {
            video_path: "in.mp4",
            narration_path: "nar.wav",
            bgm_path: None,
            ass_path: "",
            fonts_dir: "/fonts",
            output_path: "out.mp4",
            duck: false,
        };
        let argv = build_render_argv_hw(&plan("9:16", "___nope___"), &req, Platform::MacOs, &caps);
        assert!(argv
            .windows(2)
            .any(|w| w[0] == "-c:v" && w[1] == "h264_videotoolbox"));
        assert_eq!(val_after(&argv, "-b:v"), "8000k");
        // Hardware path does not use CRF/preset.
        assert!(!argv.contains(&"-crf".to_string()));
        // Filtergraph + maps are identical to the software path.
        assert!(val_after(&argv, "-filter_complex").contains("scale="));
        assert!(argv.windows(2).any(|w| w[0] == "-map" && w[1] == "[1:a]"));
    }

    #[test]
    fn hw_variant_falls_back_to_software_when_no_gpu() {
        use rf_hardware::{Capabilities, Platform};
        let caps = Capabilities {
            videotoolbox: false,
            nvenc: false,
            qsv: false,
            vaapi: false,
            amf: false,
        };
        let req = RenderRequest {
            video_path: "in.mp4",
            narration_path: "nar.wav",
            bgm_path: None,
            ass_path: "",
            fonts_dir: "/fonts",
            output_path: "out.mp4",
            duck: false,
        };
        let sw = build_render_argv(&plan("9:16", "___nope___"), &req);
        let hw = build_render_argv_hw(&plan("9:16", "___nope___"), &req, Platform::Linux, &caps);
        // No hardware caps → the hw entry point degrades to the software argv exactly.
        assert_eq!(sw, hw);
    }

    #[test]
    fn narration_only_no_captions_maps_direct_audio() {
        let argv = build_render_argv(
            &plan("9:16", "___nope___"),
            &RenderRequest {
                video_path: "in.mp4",
                narration_path: "nar.wav",
                bgm_path: None,
                ass_path: "",
                fonts_dir: "/fonts",
                output_path: "out.mp4",
                duck: false,
            },
        );
        let fc = val_after(&argv, "-filter_complex");
        assert!(fc.contains("scale="));
        assert!(!fc.contains("ass="));
        assert!(!fc.contains("amix"));
        // No captions → map the scaled pad; no BGM → map narration directly.
        assert!(argv
            .windows(2)
            .any(|w| w[0] == "-map" && w[1] == "[scaled]"));
        assert!(argv.windows(2).any(|w| w[0] == "-map" && w[1] == "[1:a]"));
    }
}
