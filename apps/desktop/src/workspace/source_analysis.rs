//! Bounded local media analysis for the mounted timeline editor.

use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::Stdio;

#[cfg(test)]
use std::process::Command;

use sha2::{Digest, Sha256};

use crate::media::toolchain::{media_command, MediaTool};

const MAX_SOURCE_DURATION_MS: u64 = 21_600_000;
const WAVEFORM_BUCKETS: usize = 120;
const ANALYSIS_SAMPLE_RATE: u32 = 100;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct EditorSourceAnalysis {
    pub request_id: String,
    pub path: PathBuf,
    pub display_name: String,
    pub duration_ms: u64,
    /// Normalized absolute peaks in the inclusive 0..=1000 range.
    pub waveform: Vec<u16>,
    pub source_sha256: String,
}

pub(super) fn analyze_editor_source(
    request_id: String,
    path: PathBuf,
) -> Result<EditorSourceAnalysis, String> {
    validate_source_path(&path)?;
    let source_sha256 = sha256_file(&path)?;
    let duration_ms = probe_duration_ms(&path)?;
    let waveform = if source_has_audio(&path)? {
        decode_waveform(&path)?
    } else {
        vec![0; WAVEFORM_BUCKETS]
    };
    if sha256_file(&path)? != source_sha256 {
        return Err("The editor source changed while it was being analyzed.".into());
    }
    let display_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("local source")
        .to_owned();
    Ok(EditorSourceAnalysis {
        request_id,
        source_sha256,
        path,
        display_name,
        duration_ms,
        waveform,
    })
}

fn validate_source_path(path: &Path) -> Result<(), String> {
    let extension = path
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    if !matches!(extension.as_str(), "mp4" | "mov" | "webm" | "mkv") {
        return Err("Choose an MP4, MOV, WebM, or MKV source video.".into());
    }
    let metadata = path
        .metadata()
        .map_err(|error| format!("inspect selected editor source: {error}"))?;
    if !metadata.is_file() {
        return Err("The selected editor source is not a regular file.".into());
    }
    Ok(())
}

fn probe_duration_ms(path: &Path) -> Result<u64, String> {
    let output = media_command(MediaTool::Ffprobe)?
        .args([
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
        ])
        .arg(path)
        .stdin(Stdio::null())
        .output()
        .map_err(|error| format!("start ffprobe for editor source: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "ffprobe could not inspect the editor source ({})",
            output.status
        ));
    }
    let seconds: f64 = String::from_utf8_lossy(&output.stdout)
        .trim()
        .parse()
        .map_err(|_| "ffprobe returned an invalid source duration".to_string())?;
    if !seconds.is_finite() || seconds <= 0.0 {
        return Err("The editor source has no positive finite duration.".into());
    }
    let duration_ms = (seconds * 1000.0).round() as u64;
    if duration_ms > MAX_SOURCE_DURATION_MS {
        return Err("The editor source exceeds the six-hour timeline limit.".into());
    }
    Ok(duration_ms)
}

fn source_has_audio(path: &Path) -> Result<bool, String> {
    let output = media_command(MediaTool::Ffprobe)?
        .args([
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
        ])
        .arg(path)
        .stdin(Stdio::null())
        .output()
        .map_err(|error| format!("start ffprobe for editor audio: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "ffprobe could not inspect editor audio ({})",
            output.status
        ));
    }
    Ok(!String::from_utf8_lossy(&output.stdout).trim().is_empty())
}

fn decode_waveform(path: &Path) -> Result<Vec<u16>, String> {
    let output = media_command(MediaTool::Ffmpeg)?
        .args(["-hide_banner", "-loglevel", "error", "-i"])
        .arg(path)
        .args([
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            &ANALYSIS_SAMPLE_RATE.to_string(),
            "-f",
            "f32le",
            "pipe:1",
        ])
        .stdin(Stdio::null())
        .stderr(Stdio::piped())
        .output()
        .map_err(|error| format!("start ffmpeg waveform analysis: {error}"))?;
    if !output.status.success() {
        let diagnostics = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "ffmpeg waveform analysis failed ({}): {}",
            output.status,
            diagnostics.trim()
        ));
    }
    Ok(normalize_waveform_bytes(&output.stdout, WAVEFORM_BUCKETS))
}

fn normalize_waveform_bytes(bytes: &[u8], buckets: usize) -> Vec<u16> {
    if buckets == 0 {
        return Vec::new();
    }
    let samples = bytes
        .chunks_exact(4)
        .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]).abs())
        .collect::<Vec<_>>();
    if samples.is_empty() {
        return vec![0; buckets];
    }
    let mut peaks = vec![0.0_f32; buckets];
    let sample_count = samples.len();
    for (index, sample) in samples.into_iter().enumerate() {
        if sample.is_finite() {
            let bucket = (index * buckets / sample_count).min(buckets - 1);
            peaks[bucket] = peaks[bucket].max(sample);
        }
    }
    let maximum = peaks.iter().copied().fold(0.0_f32, f32::max);
    if maximum <= f32::EPSILON {
        return vec![0; buckets];
    }
    peaks
        .into_iter()
        .map(|peak| ((peak / maximum) * 1000.0).round().clamp(0.0, 1000.0) as u16)
        .collect()
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut file = File::open(path).map_err(|error| format!("open editor source: {error}"))?;
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file
            .read(&mut buffer)
            .map_err(|error| format!("hash editor source: {error}"))?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(format!("sha256:{:x}", digest.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn samples(values: &[f32]) -> Vec<u8> {
        values
            .iter()
            .flat_map(|value| value.to_le_bytes())
            .collect()
    }

    #[test]
    fn waveform_is_bounded_normalized_and_ordered() {
        assert_eq!(
            normalize_waveform_bytes(&samples(&[0.25, -0.5, 1.0, -0.75]), 4),
            vec![250, 500, 1000, 750]
        );
    }

    #[test]
    fn waveform_handles_silence_empty_input_and_bucket_reduction() {
        assert_eq!(normalize_waveform_bytes(&samples(&[0.0; 8]), 3), vec![0; 3]);
        assert_eq!(normalize_waveform_bytes(&[], 3), vec![0; 3]);
        assert_eq!(
            normalize_waveform_bytes(&samples(&[0.1, 0.8, 0.2, 0.4]), 2),
            vec![1000, 500]
        );
        assert!(normalize_waveform_bytes(&[], 0).is_empty());
    }

    #[test]
    fn real_ffmpeg_analysis_reports_duration_audio_peaks_and_digest() {
        if ["ffmpeg", "ffprobe"].iter().any(|binary| {
            Command::new(binary)
                .arg("-version")
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status()
                .is_err()
        }) {
            return;
        }
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "menivor-source-analysis-{}-{nonce}",
            std::process::id()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let source = root.join("source.mp4");
        let generated = Command::new("ffmpeg")
            .args([
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=64x64:rate=30:duration=0.5",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=0.5",
                "-shortest",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-pix_fmt",
                "yuv420p",
            ])
            .arg(&source)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .unwrap();
        assert!(generated.success());

        let analysis = analyze_editor_source("request-1".into(), source).unwrap();
        assert!((450..=550).contains(&analysis.duration_ms));
        assert_eq!(analysis.waveform.len(), WAVEFORM_BUCKETS);
        assert_eq!(analysis.waveform.iter().copied().max(), Some(1000));
        assert!(analysis.waveform.iter().any(|peak| *peak > 0));
        assert_eq!(analysis.source_sha256.len(), 71);
        let _ = std::fs::remove_dir_all(root);
    }
}
