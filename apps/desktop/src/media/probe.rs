//! Lightweight local media classification used before presigned upload.

use std::path::Path;

use crate::workspace::UploadTarget;

/// The upload content type for `path`, or a user-facing reason it cannot be
/// uploaded to `target`. Unknown extensions are rejected rather than guessed, and
/// a file of the wrong kind (an image for a recording, a video for a reference
/// image) is refused before any presign/upload work starts.
pub(crate) fn content_type_for_path(
    path: &Path,
    target: UploadTarget,
) -> Result<&'static str, String> {
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    let content_type = match extension.as_str() {
        "mp4" | "m4v" => "video/mp4",
        "mov" => "video/quicktime",
        "webm" => "video/webm",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "webp" => "image/webp",
        _ => {
            return Err(match target {
                UploadTarget::ReelRecording => format!(
                    "{} is not a supported video. Use an .mp4, .mov, or .webm file.",
                    display_name(path)
                ),
                UploadTarget::BrollReference => format!(
                    "{} is not a supported image. Use a .png, .jpg, or .webp file.",
                    display_name(path)
                ),
            })
        }
    };
    match target {
        UploadTarget::ReelRecording if !content_type.starts_with("video/") => Err(format!(
            "{} is an image. The reel recording must be a video (.mp4, .mov, or .webm).",
            display_name(path)
        )),
        UploadTarget::BrollReference if !content_type.starts_with("image/") => Err(format!(
            "{} is a video. The reference must be an image (.png, .jpg, or .webp).",
            display_name(path)
        )),
        _ => Ok(content_type),
    }
}

/// `true` when `path` has a video extension the editor source analyzer accepts.
pub(crate) fn is_supported_video(path: &Path) -> bool {
    path.extension()
        .and_then(|value| value.to_str())
        .map(|value| value.to_ascii_lowercase())
        .is_some_and(|value| matches!(value.as_str(), "mp4" | "m4v" | "mov" | "webm"))
}

fn display_name(path: &Path) -> String {
    path.file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("The selected file")
        .to_owned()
}
