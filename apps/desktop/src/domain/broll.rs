//! Native AI B-roll form state.

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct BrollDraft {
    pub prompt: String,
    pub mode: BrollMode,
    pub preset: String,
    pub image_key: String,
    pub workflow_id: String,
}

impl Default for BrollDraft {
    fn default() -> Self {
        Self {
            prompt: String::new(),
            mode: BrollMode::TextToVideo,
            preset: "Cinematic".into(),
            image_key: String::new(),
            workflow_id: String::new(),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) enum BrollMode {
    TextToVideo,
    ImageToVideo,
}

impl BrollMode {
    pub(crate) fn label(self) -> &'static str {
        match self {
            Self::TextToVideo => "Text to video",
            Self::ImageToVideo => "Image to video",
        }
    }
}
