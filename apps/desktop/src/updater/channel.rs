use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub(crate) enum ReleaseChannel {
    Stable,
    Beta,
}

impl fmt::Display for ReleaseChannel {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::Stable => "stable",
            Self::Beta => "beta",
        })
    }
}

impl FromStr for ReleaseChannel {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_ascii_lowercase().as_str() {
            "stable" => Ok(Self::Stable),
            "beta" => Ok(Self::Beta),
            _ => Err("Update channel must be stable or beta.".into()),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct UpdateConfig {
    pub channel: ReleaseChannel,
    pub manifest_url: String,
    pub key_id: String,
    pub public_key_base64: String,
}

impl UpdateConfig {
    pub(crate) fn from_build(channel: ReleaseChannel) -> Result<Self, String> {
        let manifest_url = match channel {
            ReleaseChannel::Stable => option_env!("MENIVOR_UPDATE_STABLE_URL"),
            ReleaseChannel::Beta => option_env!("MENIVOR_UPDATE_BETA_URL"),
        }
        .unwrap_or_default()
        .trim()
        .to_owned();
        let key_id = option_env!("MENIVOR_UPDATE_KEY_ID")
            .unwrap_or_default()
            .trim()
            .to_owned();
        let public_key_base64 = option_env!("MENIVOR_UPDATE_PUBLIC_KEY_BASE64")
            .unwrap_or_default()
            .trim()
            .to_owned();
        if manifest_url.is_empty() || key_id.is_empty() || public_key_base64.is_empty() {
            return Err(
                "This build has no signed update channel configured. Rebuild with the Menivor update URL, key id, and public trust root."
                    .into(),
            );
        }
        if !manifest_url.starts_with("https://") {
            return Err("The configured update manifest URL must use HTTPS.".into());
        }
        Ok(Self {
            channel,
            manifest_url,
            key_id,
            public_key_base64,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn channel_parser_is_strict() {
        assert_eq!("stable".parse(), Ok(ReleaseChannel::Stable));
        assert_eq!(" BETA ".parse(), Ok(ReleaseChannel::Beta));
        assert!("nightly".parse::<ReleaseChannel>().is_err());
    }
}
