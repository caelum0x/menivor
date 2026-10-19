//! Shared test fixtures (`rf-testkit`) for the desktop engine crates — small
//! deterministic builders so each crate's tests (and integration tests across
//! crates) start from a consistent sample project without duplicating setup.

use rf_clipfarm::FanoutMatrix;
use rf_project::timeline::{Overlay, OverlayPosition, Segment, TimelineExport};
use rf_project::{AssetRef, Project, Shot};

/// A deterministic 2-shot sample project used across engine-crate tests.
pub fn sample_project() -> Project {
    let mut p = Project::new("proj-test", "Test Reel");
    p.shots.push(Shot {
        shot_id: "sc1-s1".into(),
        order: 0,
        camera_motion: "dolly_in".into(),
        duration_ms: 3000,
        prompt: "hero enters".into(),
        seed: 1,
    });
    p.shots.push(Shot {
        shot_id: "sc1-s2".into(),
        order: 1,
        camera_motion: "pan_right".into(),
        duration_ms: 2000,
        prompt: "the reveal".into(),
        seed: 2,
    });
    p.assets.push(AssetRef {
        cas_key: "deadbeef".into(),
        kind: "clip".into(),
        local_path: "/tmp/clip.mp4".into(),
    });
    p.estimate_micros = 100_000;
    p
}

/// N deterministic asset CAS keys ("asset-0", "asset-1", …) for sync/CAS tests.
pub fn sample_asset_keys(n: usize) -> Vec<String> {
    (0..n).map(|i| format!("asset-{i}")).collect()
}

/// A deterministic 2-segment timeline with one overlay, for editor/export tests.
/// Segment 1 runs 0–2s at 1.0×; segment 2 runs 3–5s at 2.0× (→1s out).
pub fn sample_timeline() -> TimelineExport {
    TimelineExport {
        segments: vec![
            Segment {
                source_in_ms: 0,
                source_out_ms: 2000,
                speed_milli: 1000,
                caption: "hook".into(),
                effect_kernel: Some("push-in".into()),
            },
            Segment {
                source_in_ms: 3000,
                source_out_ms: 5000,
                speed_milli: 2000,
                caption: String::new(),
                effect_kernel: None,
            },
        ],
        overlays: vec![Overlay {
            text: "buy now".into(),
            start_ms: 0,
            end_ms: 1500,
            position: OverlayPosition::Bottom,
        }],
    }
}

/// A small deterministic clipfarm matrix (2 bodies × 2 hooks × 1 account) for
/// fan-out / pacing tests.
pub fn sample_fanout_matrix() -> FanoutMatrix {
    FanoutMatrix {
        bodies: vec!["body-a".into(), "body-b".into()],
        hooks: vec!["hook-1".into(), "hook-2".into()],
        templates: vec!["tpl".into()],
        aspects: vec!["9:16".into()],
        accounts: vec!["acct".into()],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sample_project_is_deterministic() {
        assert_eq!(sample_project(), sample_project());
        assert_eq!(sample_project().total_duration_ms(), 5000);
    }

    #[test]
    fn asset_keys_are_stable() {
        assert_eq!(sample_asset_keys(3), vec!["asset-0", "asset-1", "asset-2"]);
    }

    #[test]
    fn sample_timeline_is_valid_and_deterministic() {
        let t = sample_timeline();
        assert_eq!(t, sample_timeline());
        assert!(t.validate().is_ok());
        // 2000ms @1.0x + 2000ms @2.0x (→1000ms) = 3000ms out.
        assert_eq!(t.output_ms(), 3000);
    }

    #[test]
    fn sample_matrix_expands_to_full_product() {
        let m = sample_fanout_matrix();
        let plan = rf_clipfarm::plan_fanout(&m, &std::collections::HashSet::new());
        assert_eq!(plan.total_combinations, 4); // 2 bodies × 2 hooks
        assert_eq!(plan.specs.len(), 4);
    }
}
