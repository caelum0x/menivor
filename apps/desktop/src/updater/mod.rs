mod apply;
mod channel;
mod checker;
mod download;

use std::path::Path;
use std::time::Duration;
use std::{fs, fs::OpenOptions};

pub(crate) use channel::ReleaseChannel;
pub(crate) use checker::AvailableUpdate;
pub(crate) use download::StagedUpdate;

use crate::config::app_data_dir;

pub(crate) fn check_for_update(channel: ReleaseChannel) -> Result<Option<AvailableUpdate>, String> {
    let config = channel::UpdateConfig::from_build(channel)?;
    let request_config = ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(30)))
        .http_status_as_error(false)
        .max_redirects(0)
        .build();
    let mut response = ureq::Agent::new_with_config(request_config)
        .get(&config.manifest_url)
        .call()
        .map_err(|error| format!("Check Menivor updates: {error}"))?;
    let status = response.status().as_u16();
    if !(200..300).contains(&status) {
        return Err(format!("Update manifest returned HTTP {status}."));
    }
    let bytes = response
        .body_mut()
        .with_config()
        .limit(checker::MAX_MANIFEST_BYTES + 1)
        .read_to_vec()
        .map_err(|error| format!("Read update manifest: {error}"))?;
    let (platform, arch) = checker::current_target();
    let update =
        checker::verify_manifest(&bytes, &config, env!("CARGO_PKG_VERSION"), platform, arch)?;
    if let Some(update) = update.as_ref() {
        enforce_release_high_water(
            &updates_root()?,
            update.release.channel,
            &update.release.version,
        )?;
    }
    Ok(update)
}

pub(crate) fn download_update(update: &AvailableUpdate) -> Result<StagedUpdate, String> {
    let root = updates_root()?;
    let staged = download::download_and_stage(update, &root)?;
    download::persist_staged_pointer(&root, &staged)?;
    Ok(staged)
}

pub(crate) fn install_update(staged: &StagedUpdate) -> Result<(), String> {
    verify_staged_trust(staged, &updates_root()?)?;
    apply::launch_verified_installer(staged)
}

pub(crate) fn load_staged_update() -> Result<Option<StagedUpdate>, String> {
    let root = updates_root()?;
    let Some(staged) = download::load_staged_pointer(&root)? else {
        return Ok(None);
    };
    verify_staged_trust(&staged, &root)?;
    Ok(Some(staged))
}

fn updates_root() -> Result<std::path::PathBuf, String> {
    Ok(app_data_dir()
        .map_err(|error| format!("Resolve update staging directory: {error}"))?
        .join("updates"))
}

fn enforce_release_high_water(
    root: &Path,
    channel: ReleaseChannel,
    candidate: &str,
) -> Result<(), String> {
    let candidate = semver::Version::parse(candidate)
        .map_err(|error| format!("Invalid update high-water version: {error}"))?;
    let directory = root.join("seen-releases").join(channel.to_string());
    fs::create_dir_all(&directory)
        .map_err(|error| format!("Create update replay state: {error}"))?;
    let mut highest = None;
    for entry in
        fs::read_dir(&directory).map_err(|error| format!("Read update replay state: {error}"))?
    {
        let entry = entry.map_err(|error| format!("Read update replay entry: {error}"))?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        let Ok(version) = semver::Version::parse(&name) else {
            continue;
        };
        if highest.as_ref().is_none_or(|known| version > *known) {
            highest = Some(version);
        }
    }
    if highest.as_ref().is_some_and(|known| candidate < *known) {
        return Err(format!(
            "Refusing replay of update {candidate}; this installation already observed {}.",
            highest.unwrap()
        ));
    }
    let marker = directory.join(candidate.to_string());
    if !marker.exists() {
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&marker)
            .and_then(|file| file.sync_all())
            .map_err(|error| format!("Persist update replay state: {error}"))?;
        #[cfg(unix)]
        let _ = std::fs::File::open(&directory).and_then(|directory| directory.sync_all());
    }
    Ok(())
}

fn verify_staged_trust(staged: &StagedUpdate, root: &Path) -> Result<(), String> {
    let config = channel::UpdateConfig::from_build(staged.channel)?;
    let (platform, arch) = checker::current_target();
    verify_staged_trust_with_config(
        staged,
        root,
        &config,
        env!("CARGO_PKG_VERSION"),
        platform,
        arch,
    )
}

fn verify_staged_trust_with_config(
    staged: &StagedUpdate,
    root: &Path,
    config: &channel::UpdateConfig,
    current_version: &str,
    platform: &str,
    arch: &str,
) -> Result<(), String> {
    let trusted = checker::verify_manifest(
        &staged.signed_manifest,
        config,
        current_version,
        platform,
        arch,
    )?
    .ok_or_else(|| "The staged update is not newer than this Menivor build.".to_string())?;
    let expected_path = root
        .join("staged")
        .join(&trusted.release.version)
        .join(format!(
            "menivor-{}-{}.{}",
            trusted.artifact.platform, trusted.artifact.arch, trusted.artifact.kind
        ));
    if staged.version != trusted.release.version
        || staged.channel != trusted.release.channel
        || staged.platform != trusted.artifact.platform
        || staged.arch != trusted.artifact.arch
        || staged.kind != trusted.artifact.kind
        || staged.size_bytes != trusted.artifact.size_bytes
        || staged.sha256 != trusted.artifact.sha256
        || staged.artifact_path != expected_path
    {
        return Err("Staged update metadata does not match its signed manifest.".into());
    }
    download::verify_staged_update(staged)
}

pub(crate) fn staged_path_label(staged: &StagedUpdate) -> String {
    staged
        .artifact_path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("verified installer")
        .to_owned()
}

#[allow(dead_code)]
fn _path_is_confined_for_documentation(path: &Path) -> bool {
    path.is_absolute()
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::Engine;
    use ring::rand::SystemRandom;
    use ring::signature::{Ed25519KeyPair, KeyPair};
    use sha2::{Digest, Sha256};

    #[test]
    fn release_high_water_refuses_an_older_signed_replay() {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "menivor-update-replay-{}-{nonce}",
            std::process::id()
        ));
        enforce_release_high_water(&root, ReleaseChannel::Stable, "1.2.0").unwrap();
        enforce_release_high_water(&root, ReleaseChannel::Stable, "1.2.0").unwrap();
        enforce_release_high_water(&root, ReleaseChannel::Stable, "1.3.0").unwrap();
        assert!(
            enforce_release_high_water(&root, ReleaseChannel::Stable, "1.2.9")
                .unwrap_err()
                .contains("replay")
        );
        enforce_release_high_water(&root, ReleaseChannel::Beta, "1.2.9-beta.1").unwrap();
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn restored_stage_is_rebound_to_its_signed_manifest_and_exact_path() {
        let key_bytes = Ed25519KeyPair::generate_pkcs8(&SystemRandom::new()).unwrap();
        let key = Ed25519KeyPair::from_pkcs8(key_bytes.as_ref()).unwrap();
        let artifact_bytes = b"verified appimage";
        let artifact = checker::UpdateArtifact {
            platform: "linux".into(),
            arch: "x86_64".into(),
            kind: "appimage".into(),
            url: "https://updates.example/menivor.AppImage".into(),
            size_bytes: artifact_bytes.len() as u64,
            sha256: format!("{:x}", Sha256::digest(artifact_bytes)),
        };
        let release = checker::ReleaseManifest {
            channel: ReleaseChannel::Stable,
            version: "1.2.3".into(),
            published_at: "2026-08-28T00:00:00Z".into(),
            notes_url: "https://updates.example/1.2.3".into(),
            artifacts: vec![artifact.clone()],
        };
        let signed = checker::SignedManifest {
            schema_version: checker::MANIFEST_SCHEMA_VERSION,
            key_id: "release-1".into(),
            signature_base64: base64::engine::general_purpose::STANDARD.encode(
                key.sign(&checker::canonical_release_bytes(&release))
                    .as_ref(),
            ),
            release: release.clone(),
        };
        let signed_manifest = serde_json::to_vec(&signed).unwrap();
        let config = channel::UpdateConfig {
            channel: ReleaseChannel::Stable,
            manifest_url: "https://updates.example/stable.json".into(),
            key_id: "release-1".into(),
            public_key_base64: base64::engine::general_purpose::STANDARD
                .encode(key.public_key().as_ref()),
        };
        let available = AvailableUpdate {
            release,
            artifact,
            signed_manifest,
        };
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "menivor-staged-trust-{}-{nonce}",
            std::process::id()
        ));
        let staged = download::stage_verified_bytes(&available, artifact_bytes, &root).unwrap();
        verify_staged_trust_with_config(&staged, &root, &config, "1.0.0", "linux", "x86_64")
            .unwrap();

        let mut forged_path = staged.clone();
        forged_path.artifact_path = root.join("attacker.AppImage");
        assert!(verify_staged_trust_with_config(
            &forged_path,
            &root,
            &config,
            "1.0.0",
            "linux",
            "x86_64"
        )
        .unwrap_err()
        .contains("does not match"));
        let mut forged_digest = staged;
        forged_digest.sha256 = "0".repeat(64);
        assert!(verify_staged_trust_with_config(
            &forged_digest,
            &root,
            &config,
            "1.0.0",
            "linux",
            "x86_64"
        )
        .unwrap_err()
        .contains("does not match"));
        let _ = fs::remove_dir_all(root);
    }
}
