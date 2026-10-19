//! The offline `.reelforge` project bundle (`rf-project`). A self-contained,
//! versioned manifest describing a reel/film project — tracks, shots, asset
//! references (content-addressed via `rf-assets`), and the wallet pre-flight
//! estimate — so a creator can work offline and later reconcile with the cloud
//! (`rf-sync`). Serde-serialized to JSON; forward-compatible via `schema_version`.

use serde::{Deserialize, Serialize};

pub mod timeline;
pub use timeline::{Overlay, OverlayPosition, Segment, TimelineError, TimelineExport};

pub const SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Project {
    #[serde(default = "default_schema")]
    pub schema_version: u32,
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub aspect: String,
    #[serde(default)]
    pub shots: Vec<Shot>,
    #[serde(default)]
    pub assets: Vec<AssetRef>,
    /// Optional non-destructive one-source edit rendered by the desktop local
    /// executor. Absent for ordinary generation projects and legacy bundles.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timeline: Option<TimelineExport>,
    /// Reserved wallet estimate (micro-USD) for the pending render.
    #[serde(default)]
    pub estimate_micros: u64,
}

fn default_schema() -> u32 {
    SCHEMA_VERSION
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Shot {
    pub shot_id: String,
    pub order: u32,
    #[serde(default)]
    pub camera_motion: String,
    pub duration_ms: u32,
    #[serde(default)]
    pub prompt: String,
    #[serde(default)]
    pub seed: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AssetRef {
    /// Content-addressed key (sha256) — resolved by `rf-assets` CAS store.
    pub cas_key: String,
    pub kind: String, // clip | image | audio
    #[serde(default)]
    pub local_path: String,
}

#[derive(Debug)]
pub enum ProjectError {
    Serialize(String),
    Deserialize(String),
    UnsupportedVersion(u32),
}

impl Project {
    pub fn new(id: impl Into<String>, title: impl Into<String>) -> Self {
        Project {
            schema_version: SCHEMA_VERSION,
            id: id.into(),
            title: title.into(),
            aspect: "9:16".into(),
            shots: Vec::new(),
            assets: Vec::new(),
            timeline: None,
            estimate_micros: 0,
        }
    }

    /// Serialize the bundle manifest to pretty JSON (the `.reelforge` payload).
    pub fn to_json(&self) -> Result<String, ProjectError> {
        serde_json::to_string_pretty(self).map_err(|e| ProjectError::Serialize(e.to_string()))
    }

    /// Load a bundle manifest, rejecting a newer schema than this build understands.
    pub fn from_json(data: &str) -> Result<Project, ProjectError> {
        let project: Project =
            serde_json::from_str(data).map_err(|e| ProjectError::Deserialize(e.to_string()))?;
        if project.schema_version > SCHEMA_VERSION {
            return Err(ProjectError::UnsupportedVersion(project.schema_version));
        }
        Ok(project)
    }

    pub fn total_duration_ms(&self) -> u32 {
        self.shots.iter().map(|s| s.duration_ms).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> Project {
        let mut p = Project::new("proj-1", "Ep 1");
        p.shots.push(Shot {
            shot_id: "sc1-s1".into(),
            order: 0,
            camera_motion: "dolly_in".into(),
            duration_ms: 3500,
            prompt: "Nova walks in".into(),
            seed: 12345,
        });
        p.shots.push(Shot {
            shot_id: "sc1-s2".into(),
            order: 1,
            camera_motion: "pan_right".into(),
            duration_ms: 2500,
            prompt: "the reveal".into(),
            seed: 67890,
        });
        p.assets.push(AssetRef {
            cas_key: "abc123".into(),
            kind: "clip".into(),
            local_path: "".into(),
        });
        p.estimate_micros = 120_000;
        p
    }

    #[test]
    fn roundtrips_through_json() {
        let p = sample();
        let json = p.to_json().unwrap();
        let back = Project::from_json(&json).unwrap();
        assert_eq!(p, back);
    }

    #[test]
    fn total_duration_sums_shots() {
        assert_eq!(sample().total_duration_ms(), 6000);
    }

    #[test]
    fn rejects_newer_schema() {
        let json = r#"{"schema_version": 999, "id": "x", "title": "y"}"#;
        assert!(matches!(
            Project::from_json(json),
            Err(ProjectError::UnsupportedVersion(999))
        ));
    }

    #[test]
    fn missing_optional_fields_default() {
        // A minimal manifest (only required fields) loads with sensible defaults.
        let json = r#"{"id": "x", "title": "y"}"#;
        let p = Project::from_json(json).unwrap();
        assert_eq!(p.schema_version, SCHEMA_VERSION);
        assert!(p.shots.is_empty() && p.assets.is_empty());
    }
}
