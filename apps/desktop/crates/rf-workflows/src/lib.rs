//! ReelForge desktop Rust port of `@reelforge/comfy-workflow-schema` (golden-parity).
//!
//! ComfyUI graphs as pinned, versioned artifacts: workflow descriptors carry
//! node commits + weight refs + a locked input contract, and each version is
//! pinned by an FNV-1a-32 hash over its canonical identity. This port is
//! byte-identical to the TypeScript (`src/pin.ts`, `src/catalog.ts`) and Python
//! (`reelforge_comfy_workflow`) ports so the render-farm registry, adapters, and
//! desktop all reference one immutable workflow identity.
//!
//! Public surface: [`graph_hash`], [`validate_inputs`], [`get_workflow`],
//! [`list_workflows`], and the [`WorkflowDescriptor`] / [`InputSlot`] DTOs.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// The declared type of a workflow input slot.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SlotType {
    Int,
    String,
    Image,
    Video,
    Audio,
}

impl SlotType {
    /// Canonical lowercase token used in the graph-hash identity string.
    fn as_str(self) -> &'static str {
        match self {
            SlotType::Int => "int",
            SlotType::String => "string",
            SlotType::Image => "image",
            SlotType::Video => "video",
            SlotType::Audio => "audio",
        }
    }
}

/// Default value for an input slot — either an integer or a string, mirroring
/// the TS `number | string` union.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum DefaultValue {
    Int(i64),
    Str(String),
}

impl DefaultValue {
    /// Canonical string form used in the identity string (`${s.default ?? ""}`).
    fn canon(&self) -> String {
        match self {
            DefaultValue::Int(n) => n.to_string(),
            DefaultValue::Str(s) => s.clone(),
        }
    }
}

/// A single locked input in a workflow's contract.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct InputSlot {
    pub name: String,
    #[serde(rename = "type")]
    pub slot_type: SlotType,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub default: Option<DefaultValue>,
    #[serde(default, skip_serializing_if = "is_false")]
    pub required: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub min: Option<i64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max: Option<i64>,
}

#[allow(clippy::trivially_copy_pass_by_ref)]
fn is_false(b: &bool) -> bool {
    !*b
}

/// A pinned ComfyUI workflow descriptor (node commits + weights + input contract).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkflowDescriptor {
    pub slug: String,
    pub category: String,
    pub description: String,
    /// `BTreeMap` keeps commits sorted by node name — matching the canonical
    /// (and golden-serialized) key order.
    pub node_commits: BTreeMap<String, String>,
    pub weight_refs: Vec<String>,
    pub inputs: Vec<InputSlot>,
}

/// Canonical identity string: slug, category, sorted commits, sorted weights,
/// and the input contract. Integer/string-only so the bytes are identical
/// across the TS and Python ports.
fn canon(d: &WorkflowDescriptor) -> String {
    // `node_commits` is a BTreeMap, so iteration is already key-sorted.
    let commits = d
        .node_commits
        .iter()
        .map(|(k, v)| format!("{k}={v}"))
        .collect::<Vec<_>>()
        .join(";");

    let mut weight_refs = d.weight_refs.clone();
    weight_refs.sort();
    let weights = weight_refs.join(",");

    let inputs = d
        .inputs
        .iter()
        .map(|s| {
            let default = s
                .default
                .as_ref()
                .map(DefaultValue::canon)
                .unwrap_or_default();
            format!(
                "{}:{}:{}:{}",
                s.name,
                s.slot_type.as_str(),
                default,
                u8::from(s.required)
            )
        })
        .collect::<Vec<_>>()
        .join(";");

    format!(
        "{}|{}|{}|{}|{}",
        d.slug, d.category, commits, weights, inputs
    )
}

/// FNV-1a-32 hex pin of a workflow descriptor (reproducibility identity).
pub fn graph_hash(d: &WorkflowDescriptor) -> String {
    let mut h: u32 = 0x811c_9dc5;
    for byte in canon(d).as_bytes() {
        h ^= u32::from(*byte);
        h = h.wrapping_mul(0x0100_0193);
    }
    format!("{h:08x}")
}

/// Validate submitted values against the workflow's input contract, returning a
/// list of human-readable error strings (empty when valid).
pub fn validate_inputs(d: &WorkflowDescriptor, values: &Map<String, Value>) -> Vec<String> {
    let mut errors: Vec<String> = Vec::new();
    for slot in &d.inputs {
        let present = values.contains_key(&slot.name);
        if slot.required && !present {
            errors.push(format!("missing required input '{}'", slot.name));
            continue;
        }
        if !present {
            continue;
        }
        let v = &values[&slot.name];
        match slot.slot_type {
            SlotType::Int => {
                // JSON `true`/`false` are not numbers, and non-integer floats
                // fail `is_i64`/`is_u64` — matching TS `Number.isInteger`.
                if !(v.is_i64() || v.is_u64()) {
                    errors.push(format!("input '{}' must be an int", slot.name));
                    continue;
                }
                let n = v.as_i64().unwrap_or(i64::MAX);
                if let Some(lo) = slot.min {
                    if n < lo {
                        errors.push(format!("input '{}' below min {lo}", slot.name));
                    }
                }
                if let Some(hi) = slot.max {
                    if n > hi {
                        errors.push(format!("input '{}' above max {hi}", slot.name));
                    }
                }
            }
            SlotType::String => {
                if !v.is_string() {
                    errors.push(format!("input '{}' must be a string", slot.name));
                }
            }
            SlotType::Image | SlotType::Video | SlotType::Audio => {}
        }
    }
    errors
}

/// Build the first-party workflow catalog (mirror of `catalog.ts` / `catalog.py`).
fn catalog() -> Vec<WorkflowDescriptor> {
    let int_slot = |name: &str, default: i64, min: i64, max: i64| InputSlot {
        name: name.to_string(),
        slot_type: SlotType::Int,
        default: Some(DefaultValue::Int(default)),
        required: false,
        min: Some(min),
        max: Some(max),
    };
    let req_slot = |name: &str, ty: SlotType| InputSlot {
        name: name.to_string(),
        slot_type: ty,
        default: None,
        required: true,
        min: None,
        max: None,
    };
    let commits = |pairs: &[(&str, &str)]| -> BTreeMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect()
    };
    let weights = |refs: &[&str]| refs.iter().map(|s| s.to_string()).collect::<Vec<_>>();

    vec![
        WorkflowDescriptor {
            slug: "wan-i2v".to_string(),
            category: "i2v".to_string(),
            description: "Wan 2.2 image-to-video (A14B).".to_string(),
            node_commits: commits(&[
                ("WanVideoWrapper", "a1b2c3d"),
                ("ComfyUI-VideoHelperSuite", "e4f5a6b"),
            ]),
            weight_refs: weights(&["wan2.2-i2v-a14b.safetensors", "umt5-xxl-enc.safetensors"]),
            inputs: vec![
                req_slot("image", SlotType::Image),
                int_slot("frames", 81, 16, 161),
                int_slot("steps", 20, 1, 60),
            ],
        },
        WorkflowDescriptor {
            slug: "flux-first-frame".to_string(),
            category: "t2i".to_string(),
            description: "FLUX first-frame T2I (schnell).".to_string(),
            node_commits: commits(&[("ComfyUI", "8f37cf8")]),
            weight_refs: weights(&["flux1-schnell.safetensors", "t5xxl_fp8.safetensors"]),
            inputs: vec![
                req_slot("prompt", SlotType::String),
                int_slot("steps", 4, 1, 12),
            ],
        },
        WorkflowDescriptor {
            slug: "lipsync-musetalk".to_string(),
            category: "lipsync".to_string(),
            description: "MuseTalk real-time lipsync.".to_string(),
            node_commits: commits(&[("ComfyUI-MuseTalk", "c7d8e9f")]),
            weight_refs: weights(&["musetalk.pth", "sd-vae-ft-mse.safetensors"]),
            inputs: vec![
                req_slot("video", SlotType::Video),
                req_slot("audio", SlotType::Audio),
            ],
        },
    ]
}

/// Fetch a workflow descriptor by slug, or an error string for an unknown slug
/// (mirror of the TS `throw new Error("unknown workflow ...")`).
pub fn get_workflow(slug: &str) -> Result<WorkflowDescriptor, String> {
    catalog()
        .into_iter()
        .find(|w| w.slug == slug)
        .ok_or_else(|| format!("unknown workflow {slug}"))
}

/// List catalog slugs (sorted), optionally filtered by category.
pub fn list_workflows(category: Option<&str>) -> Vec<String> {
    let mut slugs: Vec<String> = catalog()
        .into_iter()
        .filter(|w| category.is_none_or(|c| w.category == c))
        .map(|w| w.slug)
        .collect();
    slugs.sort();
    slugs
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn obj(v: Value) -> Map<String, Value> {
        v.as_object().unwrap().clone()
    }

    #[test]
    fn graph_hash_matches_golden_pins() {
        assert_eq!(graph_hash(&get_workflow("wan-i2v").unwrap()), "9ea52ffd");
        assert_eq!(
            graph_hash(&get_workflow("flux-first-frame").unwrap()),
            "3dcf90c3"
        );
        assert_eq!(
            graph_hash(&get_workflow("lipsync-musetalk").unwrap()),
            "dfe5e633"
        );
    }

    #[test]
    fn graph_hash_is_eight_lowercase_hex_and_deterministic() {
        let w = get_workflow("wan-i2v").unwrap();
        let h = graph_hash(&w);
        assert_eq!(h.len(), 8);
        assert!(h
            .chars()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
        assert_eq!(h, graph_hash(&w));
    }

    #[test]
    fn validate_wan_missing_required() {
        let w = get_workflow("wan-i2v").unwrap();
        let errs = validate_inputs(&w, &obj(json!({ "frames": 81 })));
        assert_eq!(errs, vec!["missing required input 'image'".to_string()]);
    }

    #[test]
    fn validate_wan_ok() {
        let w = get_workflow("wan-i2v").unwrap();
        let errs = validate_inputs(
            &w,
            &obj(json!({ "frames": 81, "image": "img.png", "steps": 20 })),
        );
        assert!(errs.is_empty());
    }

    #[test]
    fn validate_wan_above_max() {
        let w = get_workflow("wan-i2v").unwrap();
        let errs = validate_inputs(&w, &obj(json!({ "frames": 999, "image": "i" })));
        assert_eq!(errs, vec!["input 'frames' above max 161".to_string()]);
    }

    #[test]
    fn validate_below_min() {
        let w = get_workflow("wan-i2v").unwrap();
        let errs = validate_inputs(&w, &obj(json!({ "image": "i", "steps": 0 })));
        assert_eq!(errs, vec!["input 'steps' below min 1".to_string()]);
    }

    #[test]
    fn validate_int_type_rejects_float_and_bool() {
        let w = get_workflow("wan-i2v").unwrap();
        let errs = validate_inputs(&w, &obj(json!({ "image": "i", "frames": 20.5 })));
        assert_eq!(errs, vec!["input 'frames' must be an int".to_string()]);

        let errs = validate_inputs(&w, &obj(json!({ "image": "i", "frames": true })));
        assert_eq!(errs, vec!["input 'frames' must be an int".to_string()]);
    }

    #[test]
    fn validate_string_type() {
        let w = get_workflow("flux-first-frame").unwrap();
        let errs = validate_inputs(&w, &obj(json!({ "prompt": 42 })));
        assert_eq!(errs, vec!["input 'prompt' must be a string".to_string()]);
    }

    #[test]
    fn get_workflow_unknown_errors() {
        assert_eq!(
            get_workflow("nope").unwrap_err(),
            "unknown workflow nope".to_string()
        );
    }

    #[test]
    fn list_workflows_all_sorted() {
        assert_eq!(
            list_workflows(None),
            vec![
                "flux-first-frame".to_string(),
                "lipsync-musetalk".to_string(),
                "wan-i2v".to_string(),
            ]
        );
    }

    #[test]
    fn list_workflows_by_category() {
        assert_eq!(list_workflows(Some("i2v")), vec!["wan-i2v".to_string()]);
        assert!(list_workflows(Some("nope")).is_empty());
    }

    #[test]
    fn descriptor_roundtrips_through_json() {
        let w = get_workflow("flux-first-frame").unwrap();
        let s = serde_json::to_string(&w).unwrap();
        let back: WorkflowDescriptor = serde_json::from_str(&s).unwrap();
        assert_eq!(w, back);
    }
}
