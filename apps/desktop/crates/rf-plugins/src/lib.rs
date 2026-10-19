//! Plugin host (`rf-plugins`) — the manifest + capability gate for Extism WASM
//! plugins that extend the desktop app (custom effects, exporters, importers). A
//! plugin declares the capabilities it needs; the host grants only those on the
//! allowlist and denies a plugin requesting anything outside its declared set.
//! Pure manifest + permission logic; the WASM runtime is wired in the app layer.

use serde::{Deserialize, Serialize};
use std::collections::HashSet;

/// Capabilities a plugin may request (the host's full vocabulary).
pub const KNOWN_CAPABILITIES: &[&str] = &[
    "fs.read.assets",
    "fs.write.exports",
    "render.enqueue",
    "net.fetch",
    "clipboard",
];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PluginManifest {
    pub name: String,
    pub version: String,
    #[serde(default)]
    pub capabilities: Vec<String>,
    #[serde(default)]
    pub entry: String, // wasm export name
}

#[derive(Debug, PartialEq, Eq)]
pub enum LoadDecision {
    /// Granted with exactly these capabilities.
    Granted(Vec<String>),
    /// Known capabilities the user has not approved yet — the host must prompt
    /// for consent before loading. Carries the pending set (sorted, deduped).
    NeedsConsent { pending: Vec<String> },
    /// Denied: the plugin requested a capability not in the host vocabulary
    /// (fail-closed).
    Denied { unknown: Vec<String> },
}

/// Why a manifest is structurally invalid (checked before any capability gate).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ManifestError {
    MissingName,
    MissingVersion,
    MissingEntry,
}

impl std::fmt::Display for ManifestError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ManifestError::MissingName => write!(f, "manifest is missing a name"),
            ManifestError::MissingVersion => write!(f, "manifest is missing a version"),
            ManifestError::MissingEntry => write!(f, "manifest is missing a wasm entry export"),
        }
    }
}

impl std::error::Error for ManifestError {}

impl PluginManifest {
    /// Reject a structurally malformed manifest: a plugin with no name/version is
    /// unidentifiable and one with no `entry` export can never be invoked, so it
    /// must not load even if its capabilities are all valid.
    pub fn validate(&self) -> Result<(), ManifestError> {
        if self.name.trim().is_empty() {
            return Err(ManifestError::MissingName);
        }
        if self.version.trim().is_empty() {
            return Err(ManifestError::MissingVersion);
        }
        if self.entry.trim().is_empty() {
            return Err(ManifestError::MissingEntry);
        }
        Ok(())
    }
}

fn dedup_sorted(mut v: Vec<String>) -> Vec<String> {
    v.sort();
    v.dedup();
    v
}

/// Validate a manifest against the host's known capabilities. A plugin requesting
/// an unknown capability is DENIED (fail-closed); otherwise granted its declared
/// (deduped) set. Equivalent to an allowlist of the entire host vocabulary — use
/// [`evaluate_with_allowlist`] to gate on the user's actual approvals.
pub fn evaluate(manifest: &PluginManifest) -> LoadDecision {
    let all_known: HashSet<String> = KNOWN_CAPABILITIES.iter().map(|s| s.to_string()).collect();
    evaluate_with_allowlist(manifest, &all_known)
}

/// Evaluate against BOTH the host vocabulary and the user's `approved` allowlist.
/// Precedence is fail-closed: an unknown capability DENIES the load; a known but
/// unapproved capability requires consent; only when every requested capability
/// is known and approved is the plugin granted its (deduped) set.
pub fn evaluate_with_allowlist(
    manifest: &PluginManifest,
    approved: &HashSet<String>,
) -> LoadDecision {
    let known: HashSet<&str> = KNOWN_CAPABILITIES.iter().copied().collect();

    let unknown = dedup_sorted(
        manifest
            .capabilities
            .iter()
            .filter(|c| !known.contains(c.as_str()))
            .cloned()
            .collect(),
    );
    if !unknown.is_empty() {
        return LoadDecision::Denied { unknown };
    }

    // Known but not yet approved by the user → needs an explicit consent prompt.
    let pending = dedup_sorted(
        manifest
            .capabilities
            .iter()
            .filter(|c| !approved.contains(c.as_str()))
            .cloned()
            .collect(),
    );
    if !pending.is_empty() {
        return LoadDecision::NeedsConsent { pending };
    }

    LoadDecision::Granted(dedup_sorted(manifest.capabilities.clone()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn manifest(caps: &[&str]) -> PluginManifest {
        PluginManifest {
            name: "cool-fx".into(),
            version: "1.0.0".into(),
            capabilities: caps.iter().map(|s| s.to_string()).collect(),
            entry: "run".into(),
        }
    }

    #[test]
    fn grants_known_capabilities() {
        let d = evaluate(&manifest(&["fs.read.assets", "render.enqueue"]));
        assert_eq!(
            d,
            LoadDecision::Granted(vec!["fs.read.assets".into(), "render.enqueue".into()])
        );
    }

    #[test]
    fn denies_unknown_capability_fail_closed() {
        let d = evaluate(&manifest(&["fs.read.assets", "system.exec"]));
        assert_eq!(
            d,
            LoadDecision::Denied {
                unknown: vec!["system.exec".into()]
            }
        );
    }

    #[test]
    fn manifest_roundtrips() {
        let m = manifest(&["clipboard"]);
        let json = serde_json::to_string(&m).unwrap();
        let back: PluginManifest = serde_json::from_str(&json).unwrap();
        assert_eq!(m, back);
    }

    #[test]
    fn dedupes_granted_caps() {
        let d = evaluate(&manifest(&["clipboard", "clipboard"]));
        assert_eq!(d, LoadDecision::Granted(vec!["clipboard".into()]));
    }

    fn allowlist(caps: &[&str]) -> HashSet<String> {
        caps.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn allowlist_grants_only_approved_capabilities() {
        let m = manifest(&["fs.read.assets", "net.fetch"]);
        // Both known + approved -> granted.
        let d = evaluate_with_allowlist(&m, &allowlist(&["fs.read.assets", "net.fetch"]));
        assert_eq!(
            d,
            LoadDecision::Granted(vec!["fs.read.assets".into(), "net.fetch".into()])
        );
    }

    #[test]
    fn allowlist_requires_consent_for_unapproved_known_caps() {
        let m = manifest(&["fs.read.assets", "net.fetch"]);
        // `net.fetch` is known but NOT approved -> consent required (not granted).
        let d = evaluate_with_allowlist(&m, &allowlist(&["fs.read.assets"]));
        assert_eq!(
            d,
            LoadDecision::NeedsConsent {
                pending: vec!["net.fetch".into()]
            }
        );
    }

    #[test]
    fn allowlist_still_denies_unknown_before_consent() {
        let m = manifest(&["system.exec", "net.fetch"]);
        // Unknown capability fails closed even if nothing is approved.
        let d = evaluate_with_allowlist(&m, &allowlist(&[]));
        assert_eq!(
            d,
            LoadDecision::Denied {
                unknown: vec!["system.exec".into()]
            }
        );
    }

    #[test]
    fn validate_rejects_missing_fields() {
        let mut m = manifest(&["clipboard"]);
        assert!(m.validate().is_ok());
        m.entry = "".into();
        assert_eq!(m.validate(), Err(ManifestError::MissingEntry));
        m.entry = "run".into();
        m.name = "  ".into();
        assert_eq!(m.validate(), Err(ManifestError::MissingName));
    }
}
