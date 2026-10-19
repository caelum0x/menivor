//! Non-secret desktop configuration and server capability snapshots.

mod capabilities;
mod preferences;

pub(crate) use capabilities::{ConnectionState, GenerationCapabilities};
pub(crate) use preferences::{
    app_data_dir, normalize_api_base, web_origin_for_api_base, Preferences, DEFAULT_WEB_ORIGIN,
};
