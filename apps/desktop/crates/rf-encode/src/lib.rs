//! Local encode command builder — assembles the ffmpeg argv for the desktop
//! render farm (`rf-render`), choosing the fastest available hardware encoder via
//! `rf-hardware` and emitting interchange-friendly, watermark-safe master output.
//! Pure argv assembly (no process spawn here) so it is unit-testable; `rf-render`
//! executes the returned command.

use rf_effects::ffexpr;
use rf_hardware::{select_encoder, Capabilities, Platform};
use rf_project::{Segment, TimelineExport};

/// Brand mark burned into free-tier exports (removed on the paid tier via
/// `watermark_free`). Bottom-centered over a semi-transparent box for legibility.
pub const FREE_EXPORT_MARK: &str = "Made with ReelForge";

/// Target output spec for one encode.
#[derive(Debug, Clone)]
pub struct EncodeTarget {
    pub width: u32,
    pub height: u32,
    pub fps: u32,
    pub quality: Quality,
    /// `true` = clean master (no watermark); the paid tier removes the free-export mark.
    pub watermark_free: bool,
}

#[derive(Debug, Clone, Copy)]
pub enum Quality {
    Draft, // fast, larger CRF
    Standard,
    High,
}

impl Quality {
    /// CRF/quality value for software x264 (lower = better).
    fn crf(self) -> u32 {
        match self {
            Quality::Draft => 28,
            Quality::Standard => 21,
            Quality::High => 17,
        }
    }
    /// Hardware encoders use a bitrate ladder (kbps at 1080p) instead of CRF.
    fn bitrate_kbps(self) -> u32 {
        match self {
            Quality::Draft => 4000,
            Quality::Standard => 8000,
            Quality::High => 14000,
        }
    }
}

/// Assemble the `-vf` filter chain: scale-to-fill → crop → fps, then (free tier
/// only) a burned-in brand mark. Kept separate so it is directly unit-testable.
fn build_vf_chain(target: &EncodeTarget) -> String {
    let mut vf = format!(
        "scale={}:{}:force_original_aspect_ratio=increase,crop={}:{},fps={}",
        target.width, target.height, target.width, target.height, target.fps
    );
    if !target.watermark_free {
        // Bottom-centered drawtext over a translucent box. Font size scales with
        // frame height; `rf-render` supplies fontconfig at exec time.
        let fontsize = (target.height / 28).max(18);
        vf.push_str(&format!(
            ",drawtext=text='{FREE_EXPORT_MARK}':fontcolor=white@0.85:fontsize={fontsize}:\
box=1:boxcolor=black@0.4:boxborderw=10:x=(w-text_w)/2:y=h-text_h-40"
        ));
    }
    vf
}

/// Build the ffmpeg argument vector to encode `input` → `output` for the host.
pub fn build_encode_argv(
    platform: Platform,
    caps: &Capabilities,
    input: &str,
    output: &str,
    target: &EncodeTarget,
) -> Vec<String> {
    let encoder = select_encoder(platform, caps);
    let mut argv: Vec<String> = vec![
        "-y".into(),
        "-i".into(),
        input.into(),
        "-vf".into(),
        build_vf_chain(target),
        "-c:v".into(),
        encoder.ffmpeg_name().into(),
    ];

    if encoder.is_hardware() {
        argv.push("-b:v".into());
        argv.push(format!("{}k", target.quality.bitrate_kbps()));
    } else {
        argv.push("-crf".into());
        argv.push(target.quality.crf().to_string());
        argv.push("-preset".into());
        argv.push("medium".into());
    }

    // Interchange-friendly defaults + faststart for web playback.
    argv.extend([
        "-pix_fmt".into(),
        "yuv420p".into(),
        "-c:a".into(),
        "aac".into(),
        "-b:a".into(),
        "192k".into(),
        "-movflags".into(),
        "+faststart".into(),
        output.into(),
    ]);
    argv
}

/// Build a runnable one-source non-destructive timeline render. Video and audio
/// are trimmed from the same immutable source, speed-adjusted independently,
/// concatenated in visible EDL order, and optionally passed through one ASS
/// subtitle document containing segment captions and text overlays.
pub fn build_timeline_encode_argv(
    platform: Platform,
    caps: &Capabilities,
    input: &str,
    output: &str,
    target: &EncodeTarget,
    timeline: &TimelineExport,
    ass_path: Option<&str>,
    has_audio: bool,
) -> Result<Vec<String>, String> {
    timeline
        .validate()
        .map_err(|error| format!("timeline is not renderable: {error}"))?;
    let encoder = select_encoder(platform, caps);
    let mut graph = Vec::new();
    for (index, segment) in timeline.segments.iter().enumerate() {
        let start = decimal_millis(segment.source_in_ms);
        let end = decimal_millis(segment.source_out_ms);
        // Apply the segment's animation kernel (if any) as a per-frame FFmpeg
        // fragment on the already-composed WxH frame — the same way the cloud
        // render path (`app/services/compose/vfx.py`) splices effects-core
        // kernels, so a desktop-encoded segment matches the preview and cloud.
        let effect = segment_effect_filter(segment, target.width, target.height);
        let effect_suffix = effect.map(|f| format!(",{f}")).unwrap_or_default();
        graph.push(format!(
            "[0:v]trim=start={start}:end={end},setpts=(PTS-STARTPTS)*1000/{speed},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}{effect_suffix}[v{index}]",
            speed = segment.speed_milli,
            width = target.width,
            height = target.height,
            fps = target.fps,
        ));
        if has_audio {
            graph.push(format!(
                "[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,{tempo}[a{index}]",
                tempo = atempo_chain(segment.speed_milli),
            ));
        }
    }

    let inputs = (0..timeline.segments.len())
        .map(|index| {
            if has_audio {
                format!("[v{index}][a{index}]")
            } else {
                format!("[v{index}]")
            }
        })
        .collect::<String>();
    graph.push(format!(
        "{inputs}concat=n={}:v=1:a={}[timelinev]{}",
        timeline.segments.len(),
        usize::from(has_audio),
        if has_audio { "[timelinea]" } else { "" }
    ));
    let video_output = if let Some(path) = ass_path {
        graph.push(format!(
            "[timelinev]ass={}[videoout]",
            rf_ffmpeg::escape_ass_path(path)
        ));
        "videoout"
    } else {
        "timelinev"
    };

    let mut argv = vec![
        "-y".into(),
        "-i".into(),
        input.into(),
        "-filter_complex".into(),
        graph.join(";"),
        "-map".into(),
        format!("[{video_output}]"),
    ];
    if has_audio {
        argv.extend(["-map".into(), "[timelinea]".into()]);
    }
    argv.extend(["-c:v".into(), encoder.ffmpeg_name().into()]);
    if encoder.is_hardware() {
        argv.extend(["-b:v".into(), format!("{}k", target.quality.bitrate_kbps())]);
    } else {
        argv.extend([
            "-crf".into(),
            target.quality.crf().to_string(),
            "-preset".into(),
            "medium".into(),
        ]);
    }
    argv.extend(["-pix_fmt".into(), "yuv420p".into()]);
    if has_audio {
        argv.extend(["-c:a".into(), "aac".into(), "-b:a".into(), "192k".into()]);
    } else {
        argv.push("-an".into());
    }
    argv.extend(["-movflags".into(), "+faststart".into(), output.into()]);
    Ok(argv)
}

fn decimal_millis(value: u32) -> String {
    let whole = value / 1000;
    let fraction = value % 1000;
    if fraction == 0 {
        whole.to_string()
    } else {
        format!("{whole}.{fraction:03}")
            .trim_end_matches('0')
            .to_string()
    }
}

fn atempo_chain(speed_milli: u32) -> String {
    if speed_milli < 500 {
        format!("atempo=0.5,atempo={}", decimal_millis(speed_milli * 2))
    } else if speed_milli > 2000 {
        format!("atempo=2,atempo={}", decimal_ratio(speed_milli, 2000))
    } else {
        format!("atempo={}", decimal_millis(speed_milli))
    }
}

/// Render a positive rational as a compact decimal without going through a
/// float. Six fractional digits are ample for ffmpeg while retaining exact
/// per-mille editor speeds such as 2.001x after the first 2x atempo stage.
fn decimal_ratio(numerator: u32, denominator: u32) -> String {
    let whole = numerator / denominator;
    let remainder = numerator % denominator;
    if remainder == 0 {
        return whole.to_string();
    }
    let fraction = u64::from(remainder) * 1_000_000 / u64::from(denominator);
    format!("{whole}.{fraction:06}")
        .trim_end_matches('0')
        .to_string()
}

/// Build the per-frame FFmpeg filter fragment for a segment's `effect_kernel`,
/// or `None` when the segment has no (or an unknown) kernel. The fragment is a
/// self-contained single-input chain meant to sit directly after the segment's
/// `scale/crop/fps` node (it operates on the composed WxH frame), mirroring how
/// the cloud render path (`compose/vfx.py`) applies the shared effects-core
/// kernels — so the desktop encode matches the preview and cloud frame-for-frame.
fn segment_effect_filter(segment: &Segment, width: u32, height: u32) -> Option<String> {
    let kernel = segment.effect_kernel.as_deref().map(str::trim)?;
    if kernel.is_empty() {
        return None;
    }
    // Output duration (seconds) of this segment after the speed change: the
    // source span is (out-in) ms of media, played at speed_milli/1000×, so the
    // rendered length is span_ms / speed_milli seconds. Drives normalized time.
    let span_ms = segment.source_out_ms.saturating_sub(segment.source_in_ms);
    let duration_s = f64::from(span_ms) / f64::from(segment.speed_milli.max(1));
    match kernel {
        "push-in" => Some(kernel_push_in(duration_s, width, height)),
        "ken-burns" => Some(kernel_ken_burns(duration_s, width, height)),
        "handheld" => Some(kernel_handheld(duration_s, width, height)),
        "shake" => Some(kernel_shake(duration_s, width, height)),
        "rgb-split" => kernel_rgb_split(),
        "film-grain" => kernel_film_grain(),
        _ => None, // unknown kernel id — emit no fragment (never a fake filter)
    }
}

/// Normalized-time progress term `(t/duration)` for the ffexpr easing (clamped
/// inside ffexpr). Mirrors `vfx._progress_expr`.
fn progress_expr(duration_s: f64) -> String {
    let d = if duration_s > 0.0 { duration_s } else { 1.0 };
    format!("(t/{})", ffexpr::fmt_g(d, 6))
}

/// Per-frame up-scale (rounded UP to an even size so it always covers the crop
/// window) then crop back to WxH, pinning the pixel aspect. Mirrors
/// `vfx._scale_crop`.
fn scale_crop(zoom_expr: &str, crop_x: &str, crop_y: &str, w: u32, h: u32) -> String {
    format!(
        "scale=w='ceil({w}*{zoom_expr}/2)*2':h='ceil({h}*{zoom_expr}/2)*2':eval=frame,\
crop={w}:{h}:x='{crop_x}':y='{crop_y}',setsar=1"
    )
}

/// Eased centred zoom-in — mirrors `push_in` / `vfx._kernel_push_in`.
fn kernel_push_in(duration_s: f64, w: u32, h: u32) -> String {
    let z = ffexpr::push_in_zoom_expr(&progress_expr(duration_s), ffexpr::PUSH_IN_INTENSITY);
    scale_crop(&z, "(in_w-out_w)/2", "(in_h-out_h)/2", w, h)
}

/// Linear pan + zoom — mirrors `ken_burns` / `vfx._kernel_ken_burns`. The
/// kernel's normalized pan is mapped to pixels and clamped inside the crop room.
fn kernel_ken_burns(duration_s: f64, w: u32, h: u32) -> String {
    let kb = ffexpr::ken_burns_expr(
        &progress_expr(duration_s),
        ffexpr::KEN_BURNS_ZOOM,
        ffexpr::KEN_BURNS_PAN_X,
        ffexpr::KEN_BURNS_PAN_Y,
    );
    let crop_x = format!("clip((in_w-out_w)/2+({})*{w},0,in_w-out_w)", kb.x);
    let crop_y = format!("clip((in_h-out_h)/2+({})*{h},0,in_h-out_h)", kb.y);
    scale_crop(&kb.zoom, &crop_x, &crop_y, w, h)
}

/// Deterministic micro-shake (dx, dy, rot) — mirrors `handheld` /
/// `vfx._kernel_handheld`. A small constant up-scale opens room for the
/// translation + rotation so no edge shows.
fn kernel_handheld(duration_s: f64, w: u32, h: u32) -> String {
    let hh = ffexpr::handheld_expr(
        &progress_expr(duration_s),
        ffexpr::HANDHELD_INTENSITY,
        ffexpr::HANDHELD_SEED,
    );
    let margin = ffexpr::fmt_g(1.0 + 4.0 * ffexpr::HANDHELD_INTENSITY, 6);
    format!(
        "scale=w='ceil({w}*{margin}/2)*2':h='ceil({h}*{margin}/2)*2':eval=frame,\
rotate='{rot}':ow=iw:oh=ih:c=black,\
crop={w}:{h}:x='clip((in_w-out_w)/2+({dx})*{w},0,in_w-out_w)':\
y='clip((in_h-out_h)/2+({dy})*{h},0,in_h-out_h)',setsar=1",
        rot = hh.rot,
        dx = hh.dx,
        dy = hh.dy,
    )
}

/// Impact shake whose amplitude (pixels) decays over the clip as
/// `intensity*(1-t)^decay` — the `shake` VFX kernel's curve, applied as a
/// sin/cos crop translate. With no per-segment params the kernel defaults apply
/// (intensity 8px, decay 3), so the peak amplitude at `t=0` bounds the up-scale.
fn kernel_shake(duration_s: f64, w: u32, h: u32) -> String {
    // Peak amplitude at t=0 equals the kernel's `intensity` default.
    let peak = shake_amplitude(0.0);
    let margin = 2.0 * peak; // pixels of headroom on each axis
    // Per-frame decaying amplitude: intensity*(1-clip(tn))^3 (default decay=3).
    let u = format!("(1-{})", ffexpr::clamp01_expr(&progress_expr(duration_s)));
    let amp = format!("({}*{u}*{u}*{u})", ffexpr::fmt_g(peak, 9));
    format!(
        "scale=w='ceil(({w}+{margin})/2)*2':h='ceil(({h}+{margin})/2)*2':eval=frame,\
crop={w}:{h}:x='(in_w-out_w)/2+({amp})*sin(t*40)':y='(in_h-out_h)/2+({amp})*cos(t*40)',setsar=1",
        margin = ffexpr::fmt_g(margin, 6),
    )
}

/// The `shake` kernel's amplitude (pixels) at normalized time `t`, with default
/// params — the single numeric source of truth for the fragment's headroom.
fn shake_amplitude(t: f64) -> f64 {
    rf_effects::apply("shake", t, &rf_effects::Params::new())
        .ok()
        .and_then(|out| out.into_iter().find(|(k, _)| k == "amplitude").map(|(_, v)| v))
        .unwrap_or(0.0)
}

/// Chromatic-aberration shift (pixels) sampled at the `rgb_split` kernel's peak
/// (`t=0.5`). `rgbashift` carries a constant per-render offset, so — like
/// `vfx._vfx_fragment("glitch")` — the peak shift is rendered as that constant.
fn kernel_rgb_split() -> Option<String> {
    let shift = sample_kernel("rgb-split", 0.5, "shift_px")?.round() as i64;
    Some(format!("rgbashift=rh={shift}:bh=-{shift}"))
}

/// Constant grain + vignette sampled from the `film_grain` kernel (its output is
/// time-invariant). The `grain` fraction (0..1) maps to `noise=alls` (0..100),
/// mirroring `vfx._vfx_fragment("film_burn")`.
fn kernel_film_grain() -> Option<String> {
    let grain = sample_kernel("film-grain", 0.0, "grain")?;
    let alls = (grain * 100.0).round() as i64;
    Some(format!("noise=alls={alls}:allf=t,vignette=PI/4"))
}

/// Sample one numeric output of a kernel at time `t` (default params).
fn sample_kernel(id: &str, t: f64, key: &str) -> Option<f64> {
    rf_effects::apply(id, t, &rf_effects::Params::new())
        .ok()
        .and_then(|out| out.into_iter().find(|(k, _)| k == key).map(|(_, v)| v))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rf_project::{Overlay, OverlayPosition, Segment, TimelineExport};

    fn target() -> EncodeTarget {
        EncodeTarget {
            width: 1080,
            height: 1920,
            fps: 30,
            quality: Quality::Standard,
            watermark_free: true,
        }
    }

    #[test]
    fn hardware_uses_bitrate_not_crf() {
        let caps = Capabilities {
            videotoolbox: true,
            ..Default::default()
        };
        let argv = build_encode_argv(Platform::MacOs, &caps, "in.mp4", "out.mp4", &target());
        assert!(argv.contains(&"h264_videotoolbox".to_string()));
        assert!(argv.contains(&"-b:v".to_string()));
        assert!(argv.contains(&"8000k".to_string()));
        assert!(!argv.contains(&"-crf".to_string()));
    }

    #[test]
    fn software_fallback_uses_crf_and_preset() {
        let argv = build_encode_argv(
            Platform::Linux,
            &Capabilities::default(),
            "in.mp4",
            "out.mp4",
            &target(),
        );
        assert!(argv.contains(&"libx264".to_string()));
        assert!(argv.contains(&"-crf".to_string()));
        assert!(argv.contains(&"21".to_string()));
    }

    #[test]
    fn always_faststart_and_portrait_scale() {
        let argv = build_encode_argv(
            Platform::Linux,
            &Capabilities::default(),
            "in.mp4",
            "out.mp4",
            &target(),
        );
        assert!(argv.contains(&"+faststart".to_string()));
        let vf = argv.iter().find(|a| a.contains("scale=")).unwrap();
        assert!(vf.contains("1080:1920") && vf.contains("fps=30"));
    }

    #[test]
    fn output_is_last_arg() {
        let argv = build_encode_argv(
            Platform::Linux,
            &Capabilities::default(),
            "in.mp4",
            "out.mp4",
            &target(),
        );
        assert_eq!(argv.last().unwrap(), "out.mp4");
    }

    #[test]
    fn paid_tier_burns_no_watermark() {
        // target() is watermark_free: true — no drawtext in the chain.
        let argv = build_encode_argv(
            Platform::Linux,
            &Capabilities::default(),
            "in.mp4",
            "out.mp4",
            &target(),
        );
        let vf = argv.iter().find(|a| a.contains("scale=")).unwrap();
        assert!(
            !vf.contains("drawtext"),
            "paid tier must not burn a mark: {vf}"
        );
    }

    #[test]
    fn free_tier_burns_brand_mark_after_scale() {
        let free = EncodeTarget {
            watermark_free: false,
            ..target()
        };
        let argv = build_encode_argv(
            Platform::Linux,
            &Capabilities::default(),
            "in.mp4",
            "out.mp4",
            &free,
        );
        let vf = argv.iter().find(|a| a.contains("scale=")).unwrap();
        assert!(vf.contains("drawtext"));
        assert!(vf.contains(FREE_EXPORT_MARK));
        // The mark comes after the scale/crop/fps so it lands on the final frame.
        assert!(vf.find("scale=").unwrap() < vf.find("drawtext").unwrap());
        // Font size scales with height (1920 / 28 = 68).
        assert!(vf.contains("fontsize=68"));
    }

    #[test]
    fn watermark_font_size_has_a_floor() {
        // A tiny frame still gets a legible mark (floor of 18px).
        let tiny = EncodeTarget {
            width: 240,
            height: 320,
            watermark_free: false,
            ..target()
        };
        let vf = build_vf_chain(&tiny);
        assert!(vf.contains("fontsize=18")); // 320/28 = 11 -> floored to 18
    }

    fn timeline() -> TimelineExport {
        TimelineExport {
            segments: vec![
                Segment {
                    source_in_ms: 1_250,
                    source_out_ms: 3_250,
                    speed_milli: 250,
                    caption: "slow".into(),
                    effect_kernel: None,
                },
                Segment {
                    source_in_ms: 5_000,
                    source_out_ms: 7_000,
                    speed_milli: 4_000,
                    caption: "fast".into(),
                    effect_kernel: None,
                },
            ],
            overlays: vec![Overlay {
                text: "hook".into(),
                start_ms: 0,
                end_ms: 1_000,
                position: OverlayPosition::Top,
            }],
        }
    }

    #[test]
    fn timeline_command_trims_speeds_and_concats_audio_video_in_order() {
        let argv = build_timeline_encode_argv(
            Platform::Linux,
            &Capabilities::default(),
            "source.mp4",
            "out.mp4",
            &target(),
            &timeline(),
            Some("/tmp/timeline.ass"),
            true,
        )
        .unwrap();
        let graph = argv
            .get(
                argv.iter()
                    .position(|arg| arg == "-filter_complex")
                    .unwrap()
                    + 1,
            )
            .unwrap();
        assert!(graph.contains("trim=start=1.25:end=3.25"));
        assert!(graph.contains("setpts=(PTS-STARTPTS)*1000/250"));
        assert!(graph.contains("atempo=0.5,atempo=0.5[a0]"));
        assert!(graph.contains("atempo=2,atempo=2[a1]"));
        assert!(graph.contains("[v0][a0][v1][a1]concat=n=2:v=1:a=1"));
        assert!(graph.contains("ass=/tmp/timeline.ass[videoout]"));
        assert!(argv.windows(2).any(|pair| pair == ["-map", "[timelinea]"]));
    }

    #[test]
    fn timeline_command_handles_silent_source_without_fake_audio() {
        let argv = build_timeline_encode_argv(
            Platform::Linux,
            &Capabilities::default(),
            "source.mp4",
            "out.mp4",
            &target(),
            &timeline(),
            None,
            false,
        )
        .unwrap();
        let graph = argv
            .get(
                argv.iter()
                    .position(|arg| arg == "-filter_complex")
                    .unwrap()
                    + 1,
            )
            .unwrap();
        assert!(!graph.contains("[0:a]"));
        assert!(graph.contains("[v0][v1]concat=n=2:v=1:a=0[timelinev]"));
        assert!(argv.contains(&"-an".into()));
        assert!(!argv.contains(&"-c:a".into()));
    }

    #[test]
    fn atempo_chain_preserves_odd_per_mille_speeds() {
        assert_eq!(atempo_chain(2_001), "atempo=2,atempo=1.0005");
        assert_eq!(atempo_chain(3_999), "atempo=2,atempo=1.9995");
    }
}
