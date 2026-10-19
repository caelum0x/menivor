//! Resolve and inspect the packaged FFmpeg/ffprobe toolchain.

use std::collections::BTreeSet;
use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum MediaTool {
    Ffmpeg,
    Ffprobe,
}

impl MediaTool {
    fn binary_name(self) -> &'static str {
        match self {
            Self::Ffmpeg => "ffmpeg",
            Self::Ffprobe => "ffprobe",
        }
    }

    fn override_name(self) -> &'static str {
        match self {
            Self::Ffmpeg => "MENIVOR_FFMPEG_PATH",
            Self::Ffprobe => "MENIVOR_FFPROBE_PATH",
        }
    }

    fn platform_binary_name(self) -> String {
        if cfg!(target_os = "windows") {
            format!("{}.exe", self.binary_name())
        } else {
            self.binary_name().into()
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ToolSource {
    ExplicitOverride,
    Packaged,
    Path,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ResolvedMediaTool {
    pub path: PathBuf,
    pub source: ToolSource,
}

pub(crate) fn resolve_media_tool(tool: MediaTool) -> Result<ResolvedMediaTool, String> {
    let explicit = std::env::var_os(tool.override_name());
    let current_exe = std::env::current_exe()
        .map_err(|error| format!("Resolve current executable for media tools: {error}"))?;
    let appdir = std::env::var_os("APPDIR").map(PathBuf::from);
    resolve_media_tool_with(tool, explicit, &current_exe, appdir.as_deref(), |path| {
        path.is_file()
    })
}

fn resolve_media_tool_with(
    tool: MediaTool,
    explicit: Option<OsString>,
    current_exe: &Path,
    appdir: Option<&Path>,
    exists: impl Fn(&Path) -> bool,
) -> Result<ResolvedMediaTool, String> {
    if let Some(explicit) = explicit {
        let path = PathBuf::from(explicit);
        if !path.is_absolute() {
            return Err(format!(
                "{} must be an absolute path.",
                tool.override_name()
            ));
        }
        let canonical = path.canonicalize().map_err(|error| {
            format!(
                "Resolve {} override {}: {error}",
                tool.binary_name(),
                path.display()
            )
        })?;
        if !exists(&canonical) {
            return Err(format!(
                "{} override is not a regular file.",
                tool.binary_name()
            ));
        }
        return Ok(ResolvedMediaTool {
            path: canonical,
            source: ToolSource::ExplicitOverride,
        });
    }

    let binary = tool.platform_binary_name();
    let mut candidates = Vec::new();
    if cfg!(target_os = "macos") {
        if let Some(macos_dir) = current_exe.parent() {
            if let Some(contents_dir) = macos_dir.parent() {
                candidates.push(contents_dir.join("Resources/bin").join(&binary));
            }
        }
    } else if cfg!(target_os = "windows") {
        if let Some(binary_dir) = current_exe.parent() {
            candidates.push(binary_dir.join(&binary));
        }
    } else {
        if let Some(appdir) = appdir {
            if appdir.is_absolute() {
                candidates.push(appdir.join("usr/bin").join(&binary));
            }
        }
        if let Some(binary_dir) = current_exe.parent() {
            candidates.push(binary_dir.join(&binary));
        }
    }
    if let Some(path) = candidates.into_iter().find(|path| exists(path)) {
        return Ok(ResolvedMediaTool {
            path,
            source: ToolSource::Packaged,
        });
    }
    Ok(ResolvedMediaTool {
        path: PathBuf::from(tool.binary_name()),
        source: ToolSource::Path,
    })
}

pub(crate) fn media_command(tool: MediaTool) -> Result<Command, String> {
    Ok(Command::new(resolve_media_tool(tool)?.path))
}

pub(crate) fn ffmpeg_has_filter(name: &str) -> Result<bool, String> {
    let mut command = media_command(MediaTool::Ffmpeg)?;
    let output = command
        .args(["-hide_banner", "-filters"])
        .stdin(Stdio::null())
        .output()
        .map_err(|error| format!("Inspect ffmpeg filters: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "Inspect ffmpeg filters: ffmpeg exited with {}",
            output.status
        ));
    }
    Ok(parse_capability_names(&output.stdout).contains(name))
}

pub(crate) fn inspect_release_toolchain() -> Result<String, String> {
    let ffmpeg = resolve_media_tool(MediaTool::Ffmpeg)?;
    let ffprobe = resolve_media_tool(MediaTool::Ffprobe)?;
    let filters = run_capability_listing(&ffmpeg.path, "-filters")?;
    let encoders = run_capability_listing(&ffmpeg.path, "-encoders")?;
    let required_filters = [
        "ass", "trim", "atrim", "setpts", "asetpts", "concat", "overlay", "scale", "crop", "fps",
    ];
    let required_encoders = ["libx264", "aac"];
    let missing_filters = required_filters
        .iter()
        .filter(|name| !filters.contains(**name))
        .copied()
        .collect::<Vec<_>>();
    let missing_encoders = required_encoders
        .iter()
        .filter(|name| !encoders.contains(**name))
        .copied()
        .collect::<Vec<_>>();
    if !missing_filters.is_empty() || !missing_encoders.is_empty() {
        let mut details = Vec::new();
        if !missing_filters.is_empty() {
            details.push(format!("filters: {}", missing_filters.join(", ")));
        }
        if !missing_encoders.is_empty() {
            details.push(format!("encoders: {}", missing_encoders.join(", ")));
        }
        return Err(format!(
            "Packaged ffmpeg is missing required capabilities: {}.",
            details.join("; ")
        ));
    }
    let status = Command::new(&ffprobe.path)
        .arg("-version")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|error| format!("Start packaged ffprobe: {error}"))?;
    if !status.success() {
        return Err(format!("Packaged ffprobe exited with {status}."));
    }
    Ok(format!(
        "Media toolchain ready: ffmpeg={} ({:?}), ffprobe={} ({:?})",
        ffmpeg.path.display(),
        ffmpeg.source,
        ffprobe.path.display(),
        ffprobe.source
    ))
}

fn run_capability_listing(binary: &Path, argument: &str) -> Result<BTreeSet<String>, String> {
    let output = Command::new(binary)
        .args([OsStr::new("-hide_banner"), OsStr::new(argument)])
        .stdin(Stdio::null())
        .output()
        .map_err(|error| format!("Inspect {}: {error}", binary.display()))?;
    if !output.status.success() {
        return Err(format!("{} {argument} failed.", binary.display()));
    }
    Ok(parse_capability_names(&output.stdout))
}

fn parse_capability_names(bytes: &[u8]) -> BTreeSet<String> {
    String::from_utf8_lossy(bytes)
        .lines()
        .filter_map(|line| line.split_whitespace().nth(1).map(str::to_owned))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_override_is_absolute_and_precedes_packaged_candidates() {
        let current = Path::new("/Applications/Menivor.app/Contents/MacOS/reelforge-desktop");
        assert!(resolve_media_tool_with(
            MediaTool::Ffmpeg,
            Some(OsString::from("relative/ffmpeg")),
            current,
            None,
            |_| true
        )
        .is_err());
        let resolved = resolve_media_tool_with(MediaTool::Ffmpeg, None, current, None, |path| {
            path.ends_with("Contents/Resources/bin/ffmpeg")
        })
        .unwrap();
        if cfg!(target_os = "macos") {
            assert_eq!(resolved.source, ToolSource::Packaged);
        } else {
            assert_eq!(resolved.source, ToolSource::Path);
        }
    }

    #[test]
    fn linux_appdir_precedes_adjacent_binary_and_path() {
        let resolved = resolve_media_tool_with(
            MediaTool::Ffprobe,
            None,
            Path::new("/opt/menivor/reelforge-desktop"),
            Some(Path::new("/tmp/Menivor.AppDir")),
            |path| path == Path::new("/tmp/Menivor.AppDir/usr/bin/ffprobe"),
        )
        .unwrap();
        if cfg!(target_os = "linux") {
            assert_eq!(resolved.source, ToolSource::Packaged);
            assert_eq!(
                resolved.path,
                Path::new("/tmp/Menivor.AppDir/usr/bin/ffprobe")
            );
        }
    }

    #[test]
    fn capability_parser_handles_ffmpeg_filter_and_encoder_tables() {
        let names = parse_capability_names(
            b" T.. ass V->V Burn subtitles\n .. trim V->V Trim input\n V..... libx264 H.264\n A..... aac AAC\n",
        );
        assert!(names.contains("ass"));
        assert!(names.contains("trim"));
        assert!(names.contains("libx264"));
        assert!(names.contains("aac"));
    }
}
