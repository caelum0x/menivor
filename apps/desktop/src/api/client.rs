//! Synchronous authenticated transport owned by the background worker.

use std::fs::File;
use std::io;
use std::path::Path;
use std::time::Duration;

use serde::{Deserialize, Serialize};

use super::auth::API_KEY_HEADER;
use super::errors::{connection_failure, status_failure};
use super::models::{Envelope, PilotCapabilitiesDto};
use super::{ApiFailure, ApiFailureKind};
use crate::config::normalize_api_base;

const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);

// Deliberately not `Debug`: the authenticated client owns an API key.
#[derive(Clone)]
pub(crate) struct ApiClient {
    pub(super) base_url: String,
    pub(super) api_key: String,
    pub(super) agent: ureq::Agent,
}

impl ApiClient {
    pub(crate) fn new(base_url: &str, api_key: &str) -> Result<Self, ApiFailure> {
        let base_url = normalize_api_base(base_url);
        if !base_url.starts_with("http://") && !base_url.starts_with("https://") {
            return Err(ApiFailure {
                kind: ApiFailureKind::Request,
                status: None,
                message: "API base URL must start with http:// or https://".into(),
            });
        }
        if api_key.trim().is_empty() {
            return Err(ApiFailure {
                kind: ApiFailureKind::InvalidCredentials,
                status: None,
                message: "Enter and save a Menivor API key before connecting. Use \"Get an API key\" in Settings to create one.".into(),
            });
        }
        let config = ureq::Agent::config_builder()
            .timeout_global(Some(REQUEST_TIMEOUT))
            .http_status_as_error(false)
            .build();
        Ok(Self {
            base_url,
            api_key: api_key.trim().to_owned(),
            agent: config.into(),
        })
    }

    pub(crate) fn check_connection(&self) -> Result<(), ApiFailure> {
        let _: serde_json::Value = self.get("/me")?;
        Ok(())
    }

    pub(crate) fn get_generation_capabilities(&self) -> Result<(String, bool, bool), ApiFailure> {
        let value: PilotCapabilitiesDto = self.get("/pilot/capabilities")?;
        // A populated product runtime is an additional readiness gate. Older
        // servers omit this additive field, which remains compatible.
        let runtime_ready = value
            .product
            .get("runtime")
            .and_then(|runtime| runtime.get("storage_ready"))
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(true);
        Ok((
            value.mode,
            value.generation.reels,
            value.generation.broll && runtime_ready,
        ))
    }

    /// Stream a signed result URL to a user-chosen file on disk.
    ///
    /// Signed preview URLs are short-lived, so opening one in a browser tab is
    /// not a durable copy. This writes the finished bytes to a file the creator
    /// owns. The URL is already authenticated by its signature, so the API key
    /// header is deliberately not attached. The URL-scheme guard mirrors
    /// `media::playback::open_signed_preview` so only http(s) references reach
    /// the network transport.
    pub(crate) fn download_to_path(&self, url: &str, dest: &Path) -> Result<(), ApiFailure> {
        if !(url.starts_with("https://") || url.starts_with("http://")) {
            return Err(ApiFailure {
                kind: ApiFailureKind::InvalidResponse,
                status: None,
                message: "The API returned an invalid result URL.".into(),
            });
        }
        let mut response = self.agent.get(url).call().map_err(connection_failure)?;
        let status = response.status().as_u16();
        if !(200..300).contains(&status) {
            return Err(status_failure(
                status,
                "The signed result URL has expired or is no longer available. Refresh the library and try again.",
            ));
        }
        let mut file = File::create(dest).map_err(|error| ApiFailure {
            kind: ApiFailureKind::Request,
            status: None,
            message: format!("cannot create {}: {error}", dest.display()),
        })?;
        let mut reader = response.body_mut().as_reader();
        io::copy(&mut reader, &mut file).map_err(|error| ApiFailure {
            kind: ApiFailureKind::Request,
            status: None,
            message: format!("cannot write {}: {error}", dest.display()),
        })?;
        file.sync_all().map_err(|error| ApiFailure {
            kind: ApiFailureKind::Request,
            status: None,
            message: format!("cannot finalize {}: {error}", dest.display()),
        })?;
        Ok(())
    }

    pub(super) fn get<T>(&self, path: &str) -> Result<T, ApiFailure>
    where
        T: for<'de> Deserialize<'de>,
    {
        let response = self
            .agent
            .get(self.url(path))
            .header(API_KEY_HEADER, &self.api_key)
            .call()
            .map_err(connection_failure)?;
        parse_envelope(response)
    }

    pub(super) fn post<B, T>(&self, path: &str, body: &B) -> Result<T, ApiFailure>
    where
        B: Serialize,
        T: for<'de> Deserialize<'de>,
    {
        let response = self
            .agent
            .post(self.url(path))
            .header(API_KEY_HEADER, &self.api_key)
            .send_json(body)
            .map_err(connection_failure)?;
        parse_envelope(response)
    }

    pub(super) fn post_idempotent<B, T>(
        &self,
        path: &str,
        body: &B,
        idempotency_key: &str,
    ) -> Result<T, ApiFailure>
    where
        B: Serialize,
        T: for<'de> Deserialize<'de>,
    {
        let response = self
            .agent
            .post(self.url(path))
            .header(API_KEY_HEADER, &self.api_key)
            .header("Idempotency-Key", idempotency_key)
            .send_json(body)
            .map_err(connection_failure)?;
        parse_envelope(response)
    }

    pub(super) fn delete<T>(&self, path: &str) -> Result<T, ApiFailure>
    where
        T: for<'de> Deserialize<'de>,
    {
        let response = self
            .agent
            .delete(self.url(path))
            .header(API_KEY_HEADER, &self.api_key)
            .call()
            .map_err(connection_failure)?;
        parse_envelope(response)
    }

    pub(super) fn url(&self, path: &str) -> String {
        format!("{}{}", self.base_url, path)
    }
}

fn parse_envelope<T>(mut response: ureq::http::Response<ureq::Body>) -> Result<T, ApiFailure>
where
    T: for<'de> Deserialize<'de>,
{
    let status = response.status().as_u16();
    let correlation_id = response
        .headers()
        .get("X-Correlation-ID")
        .and_then(|value| value.to_str().ok())
        .unwrap_or("")
        .to_owned();
    let body = response
        .body_mut()
        .read_to_string()
        .map_err(connection_failure)?;
    if !(200..300).contains(&status) {
        let message = response_message(&body)
            .unwrap_or_else(|| format!("Menivor API request failed with HTTP {status}."));
        let visible_message = if correlation_id.is_empty() || message.contains(&correlation_id) {
            message
        } else {
            format!("{message} (correlation {correlation_id})")
        };
        return Err(status_failure(status, &visible_message));
    }
    serde_json::from_str::<Envelope<T>>(&body)
        .map(|envelope| envelope.data)
        .map_err(|error| ApiFailure {
            kind: ApiFailureKind::InvalidResponse,
            status: Some(status),
            message: format!("Menivor API returned an invalid response: {error}"),
        })
}

fn response_message(body: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(body).ok()?;
    for key in ["message", "detail", "error"] {
        if let Some(message) = value.get(key).and_then(serde_json::Value::as_str) {
            if !message.trim().is_empty() {
                return Some(message.trim().to_owned());
            }
        }
    }
    None
}
