use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::channel::ReleaseChannel;
use super::checker::{AvailableUpdate, UpdateArtifact, MAX_ARTIFACT_BYTES};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct StagedUpdate {
    pub version: String,
    pub channel: ReleaseChannel,
    pub platform: String,
    pub arch: String,
    pub kind: String,
    pub artifact_path: PathBuf,
    pub size_bytes: u64,
    pub sha256: String,
    pub signed_manifest: Vec<u8>,
}

pub(crate) fn download_and_stage(
    update: &AvailableUpdate,
    updates_root: &Path,
) -> Result<StagedUpdate, String> {
    if !update.artifact.url.starts_with("https://") {
        return Err("Refusing a non-HTTPS update artifact URL.".into());
    }
    let config = ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(300)))
        .http_status_as_error(false)
        .max_redirects(0)
        .build();
    let mut response = ureq::Agent::new_with_config(config)
        .get(&update.artifact.url)
        .call()
        .map_err(|error| format!("Download update artifact: {error}"))?;
    let status = response.status().as_u16();
    if !(200..300).contains(&status) {
        return Err(format!("Update artifact download returned HTTP {status}."));
    }
    if let Some(length) = response
        .headers()
        .get("Content-Length")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok())
    {
        if length != update.artifact.size_bytes {
            return Err(
                "Update artifact Content-Length does not match the signed manifest.".into(),
            );
        }
    }
    let bytes = response
        .body_mut()
        .with_config()
        .limit(update.artifact.size_bytes.saturating_add(1))
        .read_to_vec()
        .map_err(|error| format!("Read update artifact: {error}"))?;
    stage_verified_bytes(update, &bytes, updates_root)
}

pub(crate) fn stage_verified_bytes(
    update: &AvailableUpdate,
    bytes: &[u8],
    updates_root: &Path,
) -> Result<StagedUpdate, String> {
    verify_artifact_bytes(&update.artifact, bytes)?;
    let release_dir = updates_root.join("staged").join(&update.release.version);
    fs::create_dir_all(&release_dir)
        .map_err(|error| format!("Create update staging directory: {error}"))?;
    let file_name = format!(
        "menivor-{}-{}.{}",
        update.artifact.platform, update.artifact.arch, update.artifact.kind
    );
    let artifact_path = release_dir.join(file_name);
    reject_symlink(&artifact_path)?;
    atomic_write(&artifact_path, bytes)?;
    #[cfg(unix)]
    if update.artifact.kind == "appimage" {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = fs::metadata(&artifact_path)
            .map_err(|error| format!("Inspect staged AppImage permissions: {error}"))?
            .permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&artifact_path, permissions)
            .map_err(|error| format!("Make staged AppImage executable: {error}"))?;
    }
    let staged = StagedUpdate {
        version: update.release.version.clone(),
        channel: update.release.channel,
        platform: update.artifact.platform.clone(),
        arch: update.artifact.arch.clone(),
        kind: update.artifact.kind.clone(),
        artifact_path,
        size_bytes: update.artifact.size_bytes,
        sha256: update.artifact.sha256.clone(),
        signed_manifest: update.signed_manifest.clone(),
    };
    let metadata = serde_json::to_vec_pretty(&staged)
        .map_err(|error| format!("Serialize staged update metadata: {error}"))?;
    atomic_write(&release_dir.join("staged-update.json"), &metadata)?;
    Ok(staged)
}

pub(crate) fn verify_staged_update(staged: &StagedUpdate) -> Result<(), String> {
    let bytes = fs::read(&staged.artifact_path)
        .map_err(|error| format!("Read staged update artifact: {error}"))?;
    verify_artifact_bytes(
        &UpdateArtifact {
            platform: staged.platform.clone(),
            arch: staged.arch.clone(),
            kind: staged.kind.clone(),
            url: "https://verified-at-download.invalid/artifact".into(),
            size_bytes: staged.size_bytes,
            sha256: staged.sha256.clone(),
        },
        &bytes,
    )
}

fn verify_artifact_bytes(artifact: &UpdateArtifact, bytes: &[u8]) -> Result<(), String> {
    if artifact.size_bytes == 0 || artifact.size_bytes > MAX_ARTIFACT_BYTES {
        return Err("Signed update size is outside the supported limit.".into());
    }
    if bytes.len() as u64 != artifact.size_bytes {
        return Err(format!(
            "Update artifact size mismatch: expected {}, received {} bytes.",
            artifact.size_bytes,
            bytes.len()
        ));
    }
    let digest = format!("{:x}", Sha256::digest(bytes));
    if digest != artifact.sha256 {
        return Err("Update artifact SHA-256 does not match the signed manifest.".into());
    }
    Ok(())
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "Update staging path has no parent.".to_string())?;
    let temporary = parent.join(format!(
        ".{}.temporary",
        path.file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("update")
    ));
    if path.exists() {
        reject_symlink(path)?;
        let existing =
            fs::read(path).map_err(|error| format!("Read existing staged update file: {error}"))?;
        if existing == bytes {
            return Ok(());
        }
        return Err("Existing staged update file has different bytes.".into());
    }
    reject_symlink(&temporary)?;
    let mut file = File::create(&temporary)
        .map_err(|error| format!("Create temporary update file: {error}"))?;
    file.write_all(bytes)
        .map_err(|error| format!("Write temporary update file: {error}"))?;
    file.sync_all()
        .map_err(|error| format!("Fsync temporary update file: {error}"))?;
    fs::rename(&temporary, path)
        .map_err(|error| format!("Publish staged update atomically: {error}"))?;
    #[cfg(unix)]
    let _ = File::open(parent).and_then(|directory| directory.sync_all());
    Ok(())
}

pub(super) fn persist_staged_pointer(
    updates_root: &Path,
    staged: &StagedUpdate,
) -> Result<(), String> {
    fs::create_dir_all(updates_root)
        .map_err(|error| format!("Create update state directory: {error}"))?;
    let bytes = serde_json::to_vec_pretty(staged)
        .map_err(|error| format!("Serialize staged update pointer: {error}"))?;
    let path = updates_root.join("current-staged.json");
    if path.exists() {
        reject_symlink(&path)?;
        fs::remove_file(&path)
            .map_err(|error| format!("Replace staged update pointer: {error}"))?;
    }
    atomic_write(&path, &bytes)
}

pub(super) fn load_staged_pointer(updates_root: &Path) -> Result<Option<StagedUpdate>, String> {
    let path = updates_root.join("current-staged.json");
    reject_symlink(&path)?;
    let bytes = match fs::read(&path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(format!("Read staged update pointer: {error}")),
    };
    let staged: StagedUpdate = serde_json::from_slice(&bytes)
        .map_err(|error| format!("Staged update pointer is corrupt: {error}"))?;
    verify_staged_update(&staged)?;
    Ok(Some(staged))
}

fn reject_symlink(path: &Path) -> Result<(), String> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            Err("Refusing a symlink update staging path.".into())
        }
        Ok(_) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!("Inspect update staging path: {error}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::updater::channel::ReleaseChannel;
    use crate::updater::checker::{ReleaseManifest, UpdateArtifact};

    fn update(bytes: &[u8]) -> AvailableUpdate {
        let artifact = UpdateArtifact {
            platform: "linux".into(),
            arch: "x86_64".into(),
            kind: "appimage".into(),
            url: "https://updates.example/menivor.AppImage".into(),
            size_bytes: bytes.len() as u64,
            sha256: format!("{:x}", Sha256::digest(bytes)),
        };
        AvailableUpdate {
            artifact: artifact.clone(),
            signed_manifest: b"test manifest fixture".to_vec(),
            release: ReleaseManifest {
                channel: ReleaseChannel::Stable,
                version: "1.2.3".into(),
                published_at: "2026-08-28T00:00:00Z".into(),
                notes_url: "https://updates.example/1.2.3".into(),
                artifacts: vec![artifact],
            },
        }
    }

    fn temporary_root() -> PathBuf {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("menivor-updater-{}-{nonce}", std::process::id()))
    }

    #[test]
    fn verified_bytes_stage_atomically_and_roundtrip_metadata() {
        let root = temporary_root();
        let bytes = b"signed installer bytes";
        let staged = stage_verified_bytes(&update(bytes), bytes, &root).unwrap();
        assert_eq!(fs::read(&staged.artifact_path).unwrap(), bytes);
        verify_staged_update(&staged).unwrap();
        let metadata: StagedUpdate = serde_json::from_slice(
            &fs::read(
                staged
                    .artifact_path
                    .parent()
                    .unwrap()
                    .join("staged-update.json"),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(metadata, staged);
        assert!(!staged.artifact_path.with_extension("temporary").exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn size_digest_and_post_stage_tamper_fail_closed() {
        let root = temporary_root();
        let bytes = b"correct";
        assert!(stage_verified_bytes(&update(bytes), b"wrong", &root)
            .unwrap_err()
            .contains("size mismatch"));
        let mut bad_digest = update(bytes);
        bad_digest.artifact.sha256 = "0".repeat(64);
        assert!(stage_verified_bytes(&bad_digest, bytes, &root)
            .unwrap_err()
            .contains("SHA-256"));
        let staged = stage_verified_bytes(&update(bytes), bytes, &root).unwrap();
        fs::write(&staged.artifact_path, b"tampered").unwrap();
        assert!(verify_staged_update(&staged).is_err());
        let _ = fs::remove_dir_all(root);
    }
}
