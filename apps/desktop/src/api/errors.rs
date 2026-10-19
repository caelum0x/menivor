//! Stable HTTP and product failure categories presented by the desktop UI.

use std::fmt;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ApiFailureKind {
    Connection,
    InvalidCredentials,
    Forbidden,
    InsufficientCredits,
    RateLimited,
    Unavailable,
    InvalidResponse,
    Request,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ApiFailure {
    pub kind: ApiFailureKind,
    pub status: Option<u16>,
    pub message: String,
}

impl fmt::Display for ApiFailure {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for ApiFailure {}

pub(super) fn connection_failure(error: impl fmt::Display) -> ApiFailure {
    ApiFailure {
        kind: ApiFailureKind::Connection,
        status: None,
        message: format!("Could not reach Menivor: {error}"),
    }
}

pub(super) fn status_failure(status: u16, message: &str) -> ApiFailure {
    let kind = match status {
        401 => ApiFailureKind::InvalidCredentials,
        402 => ApiFailureKind::InsufficientCredits,
        403 if message.to_ascii_lowercase().contains("api key") => {
            ApiFailureKind::InvalidCredentials
        }
        403 => ApiFailureKind::Forbidden,
        429 => ApiFailureKind::RateLimited,
        502 | 503 | 504 => ApiFailureKind::Unavailable,
        _ => ApiFailureKind::Request,
    };
    ApiFailure {
        kind,
        status: Some(status),
        message: message.to_owned(),
    }
}
