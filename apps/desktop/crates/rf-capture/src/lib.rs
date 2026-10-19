//! Native screen-capture command builder (`rf-capture`). Emits the platform's
//! ffmpeg screen-grab input flags — avfoundation (macOS), gdigrab (Windows),
//! x11grab (Linux) — for recording the source screen that later composes under
//! the avatar. Pure argv assembly (no capture here); the runtime spawns it.

use rf_hardware::Platform;

/// A sub-rectangle of the screen to capture, in pixels. Applied per-demuxer:
/// x11grab uses `-video_size` + a `:0.0+X,Y` input offset, gdigrab uses
/// `-video_size`/`-offset_x`/`-offset_y`, and avfoundation (which can't offset
/// at the input) crops after capture with a `-vf crop` filter.
#[derive(Debug, Clone)]
pub struct Region {
    pub width: u32,
    pub height: u32,
    pub x: u32,
    pub y: u32,
}

#[derive(Debug, Clone)]
pub struct CaptureSpec {
    pub fps: u32,
    /// Platform screen selector: avfoundation index ("1"), gdigrab "desktop", or
    /// an x11 display (":0.0").
    pub source: String,
    pub output: String,
    /// Capture only this sub-rectangle; `None` = the whole display.
    pub region: Option<Region>,
    /// Auto-stop after this many seconds; `None` = record until the runtime
    /// signals stop.
    pub max_seconds: Option<u32>,
}

/// Build the ffmpeg argv to capture the screen on the given platform.
pub fn build_capture_argv(platform: Platform, spec: &CaptureSpec) -> Vec<String> {
    let mut argv: Vec<String> = vec!["-y".into()];
    // avfoundation can't offset-crop at the input, so a region becomes a post
    // `crop` filter instead of input flags.
    let mut crop_vf: Option<String> = None;
    match platform {
        Platform::MacOs => {
            // avfoundation: "-f avfoundation -framerate N -i <video>:<audio>"
            argv.extend([
                "-f".into(),
                "avfoundation".into(),
                "-framerate".into(),
                spec.fps.to_string(),
            ]);
            if let Some(r) = &spec.region {
                crop_vf = Some(format!("crop={}:{}:{}:{}", r.width, r.height, r.x, r.y));
            }
            argv.extend(["-i".into(), format!("{}:none", spec.source)]);
        }
        Platform::Windows => {
            argv.extend([
                "-f".into(),
                "gdigrab".into(),
                "-framerate".into(),
                spec.fps.to_string(),
            ]);
            if let Some(r) = &spec.region {
                argv.extend([
                    "-video_size".into(),
                    format!("{}x{}", r.width, r.height),
                    "-offset_x".into(),
                    r.x.to_string(),
                    "-offset_y".into(),
                    r.y.to_string(),
                ]);
            }
            argv.extend([
                "-i".into(),
                if spec.source.is_empty() {
                    "desktop".into()
                } else {
                    spec.source.clone()
                },
            ]);
        }
        Platform::Linux => {
            argv.extend([
                "-f".into(),
                "x11grab".into(),
                "-framerate".into(),
                spec.fps.to_string(),
            ]);
            let display = if spec.source.is_empty() {
                ":0.0".to_string()
            } else {
                spec.source.clone()
            };
            let input = if let Some(r) = &spec.region {
                argv.extend(["-video_size".into(), format!("{}x{}", r.width, r.height)]);
                format!("{}+{},{}", display, r.x, r.y)
            } else {
                display
            };
            argv.extend(["-i".into(), input]);
        }
    }
    if let Some(vf) = crop_vf {
        argv.extend(["-vf".into(), vf]);
    }
    // Optional hard duration cap so the recording auto-stops.
    if let Some(secs) = spec.max_seconds {
        argv.extend(["-t".into(), secs.to_string()]);
    }
    // Capture to a lossless-ish intermediate (re-encoded later by rf-encode).
    argv.extend([
        "-c:v".into(),
        "libx264".into(),
        "-preset".into(),
        "ultrafast".into(),
        "-pix_fmt".into(),
        "yuv420p".into(),
        spec.output.clone(),
    ]);
    argv
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spec(source: &str) -> CaptureSpec {
        CaptureSpec {
            fps: 30,
            source: source.to_string(),
            output: "cap.mp4".into(),
            region: None,
            max_seconds: None,
        }
    }

    fn region() -> Region {
        Region {
            width: 1280,
            height: 720,
            x: 100,
            y: 50,
        }
    }

    /// Index of the value following the first occurrence of `flag`, if present.
    fn val_after<'a>(argv: &'a [String], flag: &str) -> Option<&'a str> {
        argv.iter()
            .position(|a| a == flag)
            .and_then(|i| argv.get(i + 1))
            .map(|s| s.as_str())
    }

    #[test]
    fn macos_uses_avfoundation() {
        let argv = build_capture_argv(Platform::MacOs, &spec("1"));
        assert!(argv.contains(&"avfoundation".to_string()));
        assert!(argv.contains(&"1:none".to_string()));
        assert!(argv.contains(&"-framerate".to_string()));
    }

    #[test]
    fn windows_uses_gdigrab_default_desktop() {
        let argv = build_capture_argv(Platform::Windows, &spec(""));
        assert!(argv.contains(&"gdigrab".to_string()));
        assert!(argv.contains(&"desktop".to_string()));
    }

    #[test]
    fn linux_uses_x11grab_default_display() {
        let argv = build_capture_argv(Platform::Linux, &spec(""));
        assert!(argv.contains(&"x11grab".to_string()));
        assert!(argv.contains(&":0.0".to_string()));
    }

    #[test]
    fn output_is_last_and_ultrafast() {
        let argv = build_capture_argv(Platform::Linux, &spec(":0.0"));
        assert_eq!(argv.last().unwrap(), "cap.mp4");
        assert!(argv.contains(&"ultrafast".to_string()));
    }

    #[test]
    fn linux_region_sets_video_size_and_offset_input() {
        let mut s = spec(":0.0");
        s.region = Some(region());
        let argv = build_capture_argv(Platform::Linux, &s);
        assert_eq!(val_after(&argv, "-video_size"), Some("1280x720"));
        // x11grab encodes the offset in the input string.
        assert_eq!(val_after(&argv, "-i"), Some(":0.0+100,50"));
    }

    #[test]
    fn windows_region_uses_offset_flags() {
        let mut s = spec("");
        s.region = Some(region());
        let argv = build_capture_argv(Platform::Windows, &s);
        assert_eq!(val_after(&argv, "-video_size"), Some("1280x720"));
        assert_eq!(val_after(&argv, "-offset_x"), Some("100"));
        assert_eq!(val_after(&argv, "-offset_y"), Some("50"));
        assert_eq!(val_after(&argv, "-i"), Some("desktop"));
    }

    #[test]
    fn macos_region_becomes_a_crop_filter() {
        let mut s = spec("1");
        s.region = Some(region());
        let argv = build_capture_argv(Platform::MacOs, &s);
        // avfoundation can't offset the input; the region is a post crop filter.
        assert_eq!(val_after(&argv, "-vf"), Some("crop=1280:720:100:50"));
        assert!(!argv.contains(&"-video_size".to_string()));
    }

    #[test]
    fn max_seconds_adds_duration_cap_before_output() {
        let mut s = spec(":0.0");
        s.max_seconds = Some(45);
        let argv = build_capture_argv(Platform::Linux, &s);
        assert_eq!(val_after(&argv, "-t"), Some("45"));
        // The cap precedes the output file.
        let t = argv.iter().position(|a| a == "-t").unwrap();
        assert!(t < argv.len() - 1);
    }

    #[test]
    fn no_region_or_cap_by_default() {
        let argv = build_capture_argv(Platform::Linux, &spec(":0.0"));
        assert!(!argv.contains(&"-video_size".to_string()));
        assert!(!argv.contains(&"-t".to_string()));
        assert!(!argv.contains(&"-vf".to_string()));
    }
}
