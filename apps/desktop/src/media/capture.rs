//! Immutable file-selection snapshots passed to the background uploader.

use std::path::PathBuf;

use crate::media::probe::content_type_for_path;
use crate::workspace::UploadTarget;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct UploadSelection {
    pub path: PathBuf,
    pub content_type: String,
    pub target: UploadTarget,
}

impl UploadSelection {
    /// Snapshot a picked file for upload, or the user-facing reason it is not
    /// an acceptable file for `target`.
    pub(crate) fn from_path(path: PathBuf, target: UploadTarget) -> Result<Self, String> {
        let content_type = content_type_for_path(&path, target)?.to_owned();
        Ok(Self {
            path,
            content_type,
            target,
        })
    }
}
