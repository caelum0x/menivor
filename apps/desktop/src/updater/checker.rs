use base64::Engine;
use ring::signature;
use semver::Version;
use serde::{Deserialize, Serialize};

use super::channel::{ReleaseChannel, UpdateConfig};

pub(crate) const MANIFEST_SCHEMA_VERSION: u32 = 1;
pub(crate) const MAX_MANIFEST_BYTES: u64 = 256 * 1024;
pub(crate) const MAX_ARTIFACT_BYTES: u64 = 1024 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct SignedManifest {
    pub schema_version: u32,
    pub key_id: String,
    pub release: ReleaseManifest,
    pub signature_base64: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct ReleaseManifest {
    pub channel: ReleaseChannel,
    pub version: String,
    pub published_at: String,
    pub notes_url: String,
    pub artifacts: Vec<UpdateArtifact>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct UpdateArtifact {
    pub platform: String,
    pub arch: String,
    pub kind: String,
    pub url: String,
    pub size_bytes: u64,
    pub sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct AvailableUpdate {
    pub release: ReleaseManifest,
    pub artifact: UpdateArtifact,
    pub signed_manifest: Vec<u8>,
}

pub(crate) fn current_target() -> (&'static str, &'static str) {
    let platform = if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        "linux"
    };
    let arch = if cfg!(target_arch = "aarch64") {
        "aarch64"
    } else if cfg!(target_arch = "x86_64") {
        "x86_64"
    } else {
        std::env::consts::ARCH
    };
    (platform, arch)
}

pub(crate) fn verify_manifest(
    bytes: &[u8],
    config: &UpdateConfig,
    current_version: &str,
    platform: &str,
    arch: &str,
) -> Result<Option<AvailableUpdate>, String> {
    if bytes.len() as u64 > MAX_MANIFEST_BYTES {
        return Err("The update manifest exceeds the 256 KiB limit.".into());
    }
    let signed: SignedManifest = serde_json::from_slice(bytes)
        .map_err(|error| format!("The update manifest is malformed: {error}"))?;
    validate_signed_manifest(&signed, config)?;
    let candidate = Version::parse(&signed.release.version)
        .map_err(|error| format!("The update version is invalid: {error}"))?;
    if config.channel == ReleaseChannel::Stable && !candidate.pre.is_empty() {
        return Err("The stable update channel cannot publish a prerelease version.".into());
    }
    let current = Version::parse(current_version)
        .map_err(|error| format!("The installed version is invalid: {error}"))?;
    if candidate <= current {
        return Ok(None);
    }
    let matches = signed
        .release
        .artifacts
        .iter()
        .filter(|artifact| artifact.platform == platform && artifact.arch == arch)
        .cloned()
        .collect::<Vec<_>>();
    let artifact = match matches.as_slice() {
        [artifact] => artifact.clone(),
        [] => {
            return Err(format!(
                "Version {candidate} has no artifact for {platform}/{arch}."
            ))
        }
        _ => {
            return Err(format!(
                "Version {candidate} has duplicate artifacts for {platform}/{arch}."
            ))
        }
    };
    Ok(Some(AvailableUpdate {
        release: signed.release,
        artifact,
        signed_manifest: bytes.to_vec(),
    }))
}

fn validate_signed_manifest(signed: &SignedManifest, config: &UpdateConfig) -> Result<(), String> {
    if signed.schema_version != MANIFEST_SCHEMA_VERSION {
        return Err(format!(
            "Unsupported update manifest schema {}.",
            signed.schema_version
        ));
    }
    if signed.key_id != config.key_id {
        return Err("The update manifest was signed by an untrusted key id.".into());
    }
    if signed.release.channel != config.channel {
        return Err("The update manifest channel does not match the requested channel.".into());
    }
    if signed.release.published_at.trim().is_empty() {
        return Err("The update manifest has no publication time.".into());
    }
    if !signed.release.notes_url.starts_with("https://") {
        return Err("The update release-notes URL must use HTTPS.".into());
    }
    if signed.release.artifacts.is_empty() {
        return Err("The update manifest contains no artifacts.".into());
    }
    for artifact in &signed.release.artifacts {
        validate_artifact(artifact)?;
    }
    let public_key = base64::engine::general_purpose::STANDARD
        .decode(&config.public_key_base64)
        .map_err(|_| "The embedded update trust root is not valid base64.".to_string())?;
    if public_key.len() != 32 {
        return Err("The embedded Ed25519 update trust root must be 32 bytes.".into());
    }
    let signature_bytes = base64::engine::general_purpose::STANDARD
        .decode(&signed.signature_base64)
        .map_err(|_| "The update signature is not valid base64.".to_string())?;
    signature::UnparsedPublicKey::new(&signature::ED25519, public_key)
        .verify(&canonical_release_bytes(&signed.release), &signature_bytes)
        .map_err(|_| "The update manifest signature is invalid.".to_string())
}

fn validate_artifact(artifact: &UpdateArtifact) -> Result<(), String> {
    if artifact.platform.trim().is_empty() || artifact.arch.trim().is_empty() {
        return Err("Every update artifact needs a platform and architecture.".into());
    }
    let valid_kind = matches!(
        (artifact.platform.as_str(), artifact.kind.as_str()),
        ("macos", "pkg") | ("windows", "msi") | ("linux", "appimage")
    );
    if !valid_kind {
        return Err(format!(
            "Unsupported update artifact kind {}/{}.",
            artifact.platform, artifact.kind
        ));
    }
    if !artifact.url.starts_with("https://") {
        return Err("Update artifact URLs must use HTTPS.".into());
    }
    if artifact.size_bytes == 0 || artifact.size_bytes > MAX_ARTIFACT_BYTES {
        return Err("Update artifact size is outside the 1 byte–1 GiB limit.".into());
    }
    if artifact.sha256.len() != 64
        || !artifact
            .sha256
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("Update artifact SHA-256 must be 64 lowercase hexadecimal characters.".into());
    }
    Ok(())
}

pub(crate) fn canonical_release_bytes(release: &ReleaseManifest) -> Vec<u8> {
    let mut artifacts = release.artifacts.clone();
    artifacts.sort_by(|left, right| {
        (
            &left.platform,
            &left.arch,
            &left.kind,
            &left.url,
            left.size_bytes,
            &left.sha256,
        )
            .cmp(&(
                &right.platform,
                &right.arch,
                &right.kind,
                &right.url,
                right.size_bytes,
                &right.sha256,
            ))
    });
    let canonical = ReleaseManifest {
        channel: release.channel,
        version: release.version.clone(),
        published_at: release.published_at.clone(),
        notes_url: release.notes_url.clone(),
        artifacts,
    };
    serde_json::to_vec(&canonical).expect("release manifest serialization cannot fail")
}

#[cfg(test)]
mod tests {
    use super::*;
    use ring::rand::SystemRandom;
    use ring::signature::{Ed25519KeyPair, KeyPair};

    fn artifact(platform: &str, arch: &str) -> UpdateArtifact {
        UpdateArtifact {
            platform: platform.into(),
            arch: arch.into(),
            kind: match platform {
                "macos" => "pkg",
                "windows" => "msi",
                _ => "appimage",
            }
            .into(),
            url: format!("https://updates.example/{platform}-{arch}"),
            size_bytes: 4,
            sha256: "0".repeat(64),
        }
    }

    fn signed_manifest() -> (Vec<u8>, UpdateConfig) {
        let key_bytes = Ed25519KeyPair::generate_pkcs8(&SystemRandom::new()).unwrap();
        let key = Ed25519KeyPair::from_pkcs8(key_bytes.as_ref()).unwrap();
        let release = ReleaseManifest {
            channel: ReleaseChannel::Stable,
            version: "1.2.3".into(),
            published_at: "2026-08-28T00:00:00Z".into(),
            notes_url: "https://updates.example/1.2.3".into(),
            artifacts: vec![artifact("linux", "x86_64"), artifact("macos", "aarch64")],
        };
        let signed = SignedManifest {
            schema_version: MANIFEST_SCHEMA_VERSION,
            key_id: "release-1".into(),
            signature_base64: base64::engine::general_purpose::STANDARD
                .encode(key.sign(&canonical_release_bytes(&release)).as_ref()),
            release,
        };
        let config = UpdateConfig {
            channel: ReleaseChannel::Stable,
            manifest_url: "https://updates.example/stable.json".into(),
            key_id: "release-1".into(),
            public_key_base64: base64::engine::general_purpose::STANDARD
                .encode(key.public_key().as_ref()),
        };
        (serde_json::to_vec(&signed).unwrap(), config)
    }

    #[test]
    fn verifies_signature_selects_exact_target_and_rejects_downgrade() {
        let (bytes, config) = signed_manifest();
        let update = verify_manifest(&bytes, &config, "1.0.0", "linux", "x86_64")
            .unwrap()
            .unwrap();
        assert_eq!(update.release.version, "1.2.3");
        assert_eq!(update.artifact.platform, "linux");
        assert!(verify_manifest(&bytes, &config, "1.2.3", "linux", "x86_64")
            .unwrap()
            .is_none());
        assert!(verify_manifest(&bytes, &config, "2.0.0", "linux", "x86_64")
            .unwrap()
            .is_none());
    }

    #[test]
    fn tamper_channel_key_and_duplicate_target_fail_closed() {
        let (bytes, config) = signed_manifest();
        let mut tampered: SignedManifest = serde_json::from_slice(&bytes).unwrap();
        tampered.release.version = "9.9.9".into();
        assert!(verify_manifest(
            &serde_json::to_vec(&tampered).unwrap(),
            &config,
            "1.0.0",
            "linux",
            "x86_64"
        )
        .unwrap_err()
        .contains("signature"));

        let mut wrong_channel = config.clone();
        wrong_channel.channel = ReleaseChannel::Beta;
        assert!(
            verify_manifest(&bytes, &wrong_channel, "1.0.0", "linux", "x86_64")
                .unwrap_err()
                .contains("channel")
        );

        let mut duplicate: SignedManifest = serde_json::from_slice(&bytes).unwrap();
        duplicate
            .release
            .artifacts
            .push(artifact("linux", "x86_64"));
        let key_bytes = Ed25519KeyPair::generate_pkcs8(&SystemRandom::new()).unwrap();
        let key = Ed25519KeyPair::from_pkcs8(key_bytes.as_ref()).unwrap();
        duplicate.key_id = "duplicate-key".into();
        duplicate.signature_base64 = base64::engine::general_purpose::STANDARD.encode(
            key.sign(&canonical_release_bytes(&duplicate.release))
                .as_ref(),
        );
        let duplicate_config = UpdateConfig {
            key_id: duplicate.key_id.clone(),
            public_key_base64: base64::engine::general_purpose::STANDARD
                .encode(key.public_key().as_ref()),
            ..config
        };
        assert!(verify_manifest(
            &serde_json::to_vec(&duplicate).unwrap(),
            &duplicate_config,
            "1.0.0",
            "linux",
            "x86_64"
        )
        .unwrap_err()
        .contains("duplicate"));
    }

    #[test]
    fn insecure_or_oversized_artifacts_are_rejected_even_when_signed() {
        let (bytes, config) = signed_manifest();
        let mut signed: SignedManifest = serde_json::from_slice(&bytes).unwrap();
        signed.release.artifacts[0].url = "http://updates.example/bad".into();
        // Validation happens before signature verification so the precise
        // policy failure is visible without accepting the modified payload.
        assert!(verify_manifest(
            &serde_json::to_vec(&signed).unwrap(),
            &config,
            "1.0.0",
            "linux",
            "x86_64"
        )
        .unwrap_err()
        .contains("HTTPS"));
        signed.release.artifacts[0].url = "https://updates.example/large".into();
        signed.release.artifacts[0].size_bytes = MAX_ARTIFACT_BYTES + 1;
        assert!(verify_manifest(
            &serde_json::to_vec(&signed).unwrap(),
            &config,
            "1.0.0",
            "linux",
            "x86_64"
        )
        .unwrap_err()
        .contains("1 byte–1 GiB"));
    }

    #[test]
    fn canonical_payload_has_a_cross_language_stable_shape() {
        let release = ReleaseManifest {
            channel: ReleaseChannel::Stable,
            version: "1.2.3".into(),
            published_at: "2026-08-28T00:00:00Z".into(),
            notes_url: "https://updates.example/1.2.3".into(),
            artifacts: vec![artifact("macos", "aarch64"), artifact("linux", "x86_64")],
        };
        assert_eq!(
            String::from_utf8(canonical_release_bytes(&release)).unwrap(),
            concat!(
                "{\"channel\":\"stable\",\"version\":\"1.2.3\",",
                "\"published_at\":\"2026-08-28T00:00:00Z\",",
                "\"notes_url\":\"https://updates.example/1.2.3\",\"artifacts\":[",
                "{\"platform\":\"linux\",\"arch\":\"x86_64\",\"kind\":\"appimage\",",
                "\"url\":\"https://updates.example/linux-x86_64\",\"size_bytes\":4,",
                "\"sha256\":\"0000000000000000000000000000000000000000000000000000000000000000\"},",
                "{\"platform\":\"macos\",\"arch\":\"aarch64\",\"kind\":\"pkg\",",
                "\"url\":\"https://updates.example/macos-aarch64\",\"size_bytes\":4,",
                "\"sha256\":\"0000000000000000000000000000000000000000000000000000000000000000\"}]}"
            )
        );
    }

    #[test]
    fn stable_channel_rejects_a_signed_prerelease() {
        let (bytes, config) = signed_manifest();
        let mut signed: SignedManifest = serde_json::from_slice(&bytes).unwrap();
        signed.release.version = "1.2.3-beta.1".into();
        // Re-signing is unnecessary for this policy assertion because channel
        // semantics are checked only after the original signature. Build a new
        // valid signature/key pair to prove the policy is independent of trust.
        let key_bytes = Ed25519KeyPair::generate_pkcs8(&SystemRandom::new()).unwrap();
        let key = Ed25519KeyPair::from_pkcs8(key_bytes.as_ref()).unwrap();
        signed.key_id = "prerelease-key".into();
        signed.signature_base64 = base64::engine::general_purpose::STANDARD
            .encode(key.sign(&canonical_release_bytes(&signed.release)).as_ref());
        let config = UpdateConfig {
            key_id: signed.key_id.clone(),
            public_key_base64: base64::engine::general_purpose::STANDARD
                .encode(key.public_key().as_ref()),
            ..config
        };
        assert!(verify_manifest(
            &serde_json::to_vec(&signed).unwrap(),
            &config,
            "1.0.0",
            "linux",
            "x86_64"
        )
        .unwrap_err()
        .contains("prerelease"));
    }
}
