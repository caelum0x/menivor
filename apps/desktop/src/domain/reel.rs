//! Native reel form state.

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct ReelDraft {
    pub video_subject: String,
    pub video_script: String,
    pub screen_recording_key: String,
    pub avatar_id: String,
    pub voice_name: String,
    pub caption_style: String,
    pub layout: String,
    pub language: String,
    pub target_duration_s: u32,
    pub platforms: Vec<String>,
    pub attached_broll_key: Option<String>,
}

impl Default for ReelDraft {
    fn default() -> Self {
        Self {
            video_subject: String::new(),
            video_script: String::new(),
            screen_recording_key: String::new(),
            avatar_id: String::new(),
            voice_name: String::new(),
            caption_style: "karaoke_yellow".into(),
            layout: "pip".into(),
            language: "auto".into(),
            target_duration_s: 30,
            platforms: Vec::new(),
            attached_broll_key: None,
        }
    }
}
