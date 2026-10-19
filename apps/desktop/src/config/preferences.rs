//! Non-secret desktop preferences. API keys never belong in this store.

use std::fs;
use std::io;
use std::path::PathBuf;

/// The production Menivor API. A fresh install talks to it without any setup;
/// Settings can still point a dev build at a local or staging backend.
pub(crate) const DEFAULT_API_BASE: &str = "https://api.menivor.com/api/v1";

/// The local freegen sidecar URL. Used when `use_local_engine` is true.
pub(crate) const LOCAL_API_BASE: &str = "http://127.0.0.1:8765/api/v1";

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(crate) struct Preferences {
    pub api_base_url: String,
    /// Optional explicit location of the WolfCut editor (an `.app` bundle or
    /// executable). Empty means "look in the standard install locations".
    pub editor_path: String,
    /// When true, route all API calls to the local freegen sidecar instead of
    /// the cloud backend. No API key is required in this mode.
    pub use_local_engine: bool,
}

impl Preferences {
    pub(crate) fn normalized_api_base(&self) -> String {
        if self.use_local_engine {
            return LOCAL_API_BASE.to_owned();
        }
        normalize_api_base(&self.api_base_url)
    }

    /// Load only non-secret settings. A missing file is a normal first run.
    pub(crate) fn load() -> io::Result<Self> {
        let path = preference_path()?;
        let content = match fs::read_to_string(path) {
            Ok(content) => content,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(Self::default()),
            Err(error) => return Err(error),
        };
        let field = |name: &str| {
            content
                .lines()
                .find_map(|line| line.strip_prefix(name))
                .unwrap_or_default()
                .trim()
                .to_owned()
        };
        Ok(Self {
            api_base_url: field("api_base_url="),
            editor_path: field("editor_path="),
            use_local_engine: field("use_local_engine=") == "true",
        })
    }

    /// Persist the API origin atomically. The value is normalized and cannot
    /// contain a newline, so this tiny format cannot be used to inject fields.
    pub(crate) fn save(&self) -> io::Result<()> {
        let path = preference_path()?;
        let parent = path.parent().expect("preference path always has a parent");
        fs::create_dir_all(parent)?;
        let value = self.normalized_api_base();
        let editor = self.editor_path.trim();
        if [value.as_str(), editor]
            .iter()
            .any(|field| field.contains('\n') || field.contains('\r'))
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Settings values must be one line",
            ));
        }
        let temporary = path.with_extension("tmp");
        let mut body = format!("api_base_url={value}\n");
        if !editor.is_empty() {
            body.push_str(&format!("editor_path={editor}\n"));
        }
        if self.use_local_engine {
            body.push_str("use_local_engine=true\n");
        }
        fs::write(&temporary, body)?;
        fs::rename(temporary, path)
    }
}

fn preference_path() -> io::Result<PathBuf> {
    Ok(app_data_dir()?.join("preferences"))
}

pub(crate) fn app_data_dir() -> io::Result<PathBuf> {
    #[cfg(target_os = "macos")]
    let root = std::env::var_os("HOME")
        .map(PathBuf::from)
        .map(|path| path.join("Library/Application Support"));
    #[cfg(target_os = "windows")]
    let root = std::env::var_os("APPDATA").map(PathBuf::from);
    #[cfg(target_os = "linux")]
    let root = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".config")));
    #[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
    let root: Option<PathBuf> = None;

    root.map(|directory| directory.join("ReelForge"))
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::NotFound,
                "No OS preference directory is available",
            )
        })
}

/// Normalize a user-entered origin or v1 URL to the REST API base.
pub(crate) fn normalize_api_base(value: &str) -> String {
    let trimmed = value.trim().trim_end_matches('/');
    if trimmed.is_empty() {
        return DEFAULT_API_BASE.to_owned();
    }
    if trimmed.ends_with("/api/v1") {
        trimmed.to_owned()
    } else {
        format!("{trimmed}/api/v1")
    }
}

/// The public Menivor web app, used when the API base is not a hosted
/// `api.<domain>` origin (local or staging backends).
pub(crate) const DEFAULT_WEB_ORIGIN: &str = "https://menivor.com";

/// The web origin that pairs with an API base: `https://api.menivor.com/api/v1`
/// maps to `https://menivor.com`. Local/dev API bases (no `api.` host) fall back
/// to the public web app, where personal API keys are minted.
pub(crate) fn web_origin_for_api_base(api_base: &str) -> String {
    let normalized = normalize_api_base(api_base);
    let Some((scheme, rest)) = normalized.split_once("://") else {
        return DEFAULT_WEB_ORIGIN.to_owned();
    };
    let host = rest.split('/').next().unwrap_or_default();
    match host.strip_prefix("api.") {
        Some(domain) if !domain.is_empty() => format!("{scheme}://{domain}"),
        _ => DEFAULT_WEB_ORIGIN.to_owned(),
    }
}

#[cfg(test)]
mod tests {
    use super::normalize_api_base;

    #[test]
    fn normalizes_origin_and_v1_urls() {
        assert_eq!(
            normalize_api_base("https://api.example.com/"),
            "https://api.example.com/api/v1"
        );
        assert_eq!(
            normalize_api_base("https://api.example.com/api/v1/"),
            "https://api.example.com/api/v1"
        );
    }

    #[test]
    fn default_points_to_the_canonical_v1_api() {
        assert_eq!(
            super::Preferences::default().normalized_api_base(),
            "https://api.menivor.com/api/v1"
        );
    }
}
