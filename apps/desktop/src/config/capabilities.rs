//! Authenticated server capability and connection snapshots.

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) enum ConnectionState {
    #[default]
    Disconnected,
    Checking,
    Connected,
    Failed,
}

impl ConnectionState {
    pub(crate) fn label(self) -> &'static str {
        match self {
            Self::Disconnected => "Not connected",
            Self::Checking => "Checking connection…",
            Self::Connected => "Connected",
            Self::Failed => "Connection needs attention",
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(crate) struct GenerationCapabilities {
    pub loaded: bool,
    pub mode: String,
    pub reels: bool,
    pub broll: bool,
}
