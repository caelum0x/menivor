//! Reviewed picker data for the create-reel UI (`/avatars`, `/voices`,
//! `/catalog/*`). The backend wraps these lists in the standard envelope, but the
//! inner payload varies between a bare array and a keyed object (`{ avatars: [] }`),
//! so parsing is intentionally shape-tolerant and never fails a connect flow.

use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::{ApiClient, ApiFailure};

/// One selectable catalog row (avatar, voice, or caption style). `id` is the
/// value sent to `POST /jobs`; `display` is the human label shown in the picker.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub(crate) struct CatalogEntry {
    pub id: String,
    pub display: String,
}

impl ApiClient {
    /// Avatars available to the caller (`GET /avatars`).
    pub(crate) fn list_avatars(&self) -> Result<Vec<CatalogEntry>, ApiFailure> {
        Ok(extract_entries(self.get::<Value>("/avatars")?))
    }

    /// Voices available to the caller (`GET /voices`).
    pub(crate) fn list_voices(&self) -> Result<Vec<CatalogEntry>, ApiFailure> {
        Ok(extract_entries(self.get::<Value>("/voices")?))
    }

    /// Reviewed caption styles (`GET /catalog/caption-styles`).
    pub(crate) fn list_caption_styles(&self) -> Result<Vec<CatalogEntry>, ApiFailure> {
        Ok(extract_entries(self.get::<Value>("/catalog/caption-styles")?))
    }
}

/// Accept either a bare array or an object whose first array field holds the rows.
fn extract_entries(value: Value) -> Vec<CatalogEntry> {
    let array = match value {
        Value::Array(items) => items,
        Value::Object(map) => map
            .into_iter()
            .find_map(|(_, item)| match item {
                Value::Array(items) => Some(items),
                _ => None,
            })
            .unwrap_or_default(),
        _ => Vec::new(),
    };
    array.into_iter().filter_map(entry_from_value).collect()
}

/// Pull a stable id + display label from a heterogeneous catalog row. Rows that
/// carry no recognizable identifier (including bare strings) are dropped.
fn entry_from_value(value: Value) -> Option<CatalogEntry> {
    if let Value::String(id) = &value {
        let id = id.trim();
        return (!id.is_empty()).then(|| CatalogEntry {
            id: id.to_owned(),
            display: id.to_owned(),
        });
    }
    let object = value.as_object()?;
    let id = ["id", "avatar_id", "voice_id", "value", "slug", "key", "name"]
        .iter()
        .find_map(|key| object.get(*key).and_then(Value::as_str))
        .map(str::trim)
        .filter(|id| !id.is_empty())?
        .to_owned();
    let display = ["label", "title", "display_name", "name"]
        .iter()
        .find_map(|key| object.get(*key).and_then(Value::as_str))
        .map(str::trim)
        .filter(|label| !label.is_empty())
        .map(str::to_owned)
        .unwrap_or_else(|| id.clone());
    Some(CatalogEntry { id, display })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_bare_array_of_objects() {
        let value = serde_json::json!([
            {"avatar_id": "hg_1", "display_name": "Ava"},
            {"avatar_id": "hg_2", "name": "Ben"}
        ]);
        let entries = extract_entries(value);
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].id, "hg_1");
        assert_eq!(entries[0].display, "Ava");
        assert_eq!(entries[1].display, "Ben");
    }

    #[test]
    fn parses_keyed_object_wrapper() {
        let value = serde_json::json!({"voices": [
            {"voice_id": "elevenlabs:xyz", "label": "Narrator"}
        ]});
        let entries = extract_entries(value);
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].id, "elevenlabs:xyz");
        assert_eq!(entries[0].display, "Narrator");
    }

    #[test]
    fn parses_bare_string_rows_and_drops_empty() {
        let value = serde_json::json!(["captions_bold", "", {"noise": true}]);
        let entries = extract_entries(value);
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].id, "captions_bold");
        assert_eq!(entries[0].display, "captions_bold");
    }

    #[test]
    fn falls_back_to_id_when_no_label() {
        let value = serde_json::json!([{"id": "clean"}]);
        let entries = extract_entries(value);
        assert_eq!(entries[0].display, "clean");
    }
}
