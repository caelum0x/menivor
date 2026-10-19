//! Desktop-side domain for the unified **media gateway** (`rf-gateway`) — the
//! OpenRouter-style `/images` (sync) + `/videos` (async poll) surface, one key +
//! one wallet balance. This crate is the Rust mirror of
//! `app/domains/gateway/media_gateway.py` + `media_catalog.py`: it builds request
//! bodies, parses the response envelope, normalizes poll status, estimates the
//! integer-micro cost, and runs a wallet pre-flight — **purely**. The actual
//! HTTP call (via `ureq` in the runtime) is out of scope here, exactly like
//! `rf-sync` keeps transport in the runtime. Deterministic + unit-tested.

use serde::{Deserialize, Serialize};

/// 1 USD in integer microdollars — the money unit shared with the API wallet.
pub const USD_MICROS: u64 = 1_000_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Modality {
    Image,
    Video,
    Audio,
}

/// A routable model in the unified catalog (mirrors `MediaModel` in the API).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MediaModel {
    pub id: String,
    pub modality: Modality,
    pub provider: String,
    pub price_micros: u64,
    pub unit: String,
    #[serde(default)]
    pub max_seconds: u32,
    #[serde(default)]
    pub description: String,
}

impl MediaModel {
    /// Integer-micro cost for a request. Image = flat per-image price; video =
    /// per-second price × seconds clamped to `[1, max_seconds]`. Matches the
    /// server's `create_video`/`create_image` charge exactly.
    pub fn estimate_cost_micros(&self, seconds: u32) -> u64 {
        match self.modality {
            // Image + audio are flat per-generation; video is per-second.
            Modality::Image | Modality::Audio => self.price_micros,
            Modality::Video => self.price_micros * clamp_seconds(seconds, self.max_seconds) as u64,
        }
    }
}

/// Clamp a requested duration the same way the gateway does: at least 1s, and no
/// more than the model's `max_seconds` when that cap is set (0 = uncapped).
pub fn clamp_seconds(seconds: u32, max_seconds: u32) -> u32 {
    let s = seconds.max(1);
    if max_seconds > 0 {
        s.min(max_seconds)
    } else {
        s
    }
}

/// Render integer microdollars as a short `$` string, e.g. `84_000 -> "$0.084"`,
/// `2_000_000 -> "$2.00"`. Sub-10¢ amounts use 3 decimals (per-second prices).
pub fn format_usd_micros(micros: u64) -> String {
    let usd = micros as f64 / USD_MICROS as f64;
    let digits = if usd != 0.0 && usd < 0.1 { 3 } else { 2 };
    format!("${:.*}", digits, usd)
}

/// Render a person handle with `@` while leaving typed/Mint routes intact.
pub fn format_wallet_destination(raw: &str) -> String {
    let destination = raw.trim().trim_start_matches('@');
    if destination.starts_with("ait1")
        || ["workspace:", "agent:", "service:"]
            .iter()
            .any(|prefix| destination.starts_with(prefix))
    {
        destination.to_owned()
    } else {
        format!("@{destination}")
    }
}

/// Validate one public wallet route before interpolating it into an HTTP path.
pub fn valid_wallet_destination(destination: &str) -> bool {
    if destination.is_empty() {
        return false;
    }
    if destination.starts_with("ait1") {
        return destination.len() <= 128
            && destination
                .chars()
                .all(|character| character.is_ascii_alphanumeric());
    }
    if let Some((kind, slug)) = destination.split_once(':') {
        return matches!(kind, "workspace" | "agent" | "service")
            && (3..=48).contains(&slug.len())
            && slug.chars().all(|character| {
                character.is_ascii_lowercase() || character.is_ascii_digit() || character == '-'
            })
            && slug.chars().next().is_some_and(|character| {
                character.is_ascii_lowercase() || character.is_ascii_digit()
            })
            && slug.chars().last().is_some_and(|character| {
                character.is_ascii_lowercase() || character.is_ascii_digit()
            });
    }
    destination.len() <= 64
        && destination
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "._-".contains(character))
}

/// Handles are case-insensitive; Mint addresses are exact routing values.
pub fn wallet_destinations_equal(left: &str, right: &str) -> bool {
    let left = left.trim().trim_start_matches('@');
    let right = right.trim().trim_start_matches('@');
    if left.starts_with("ait1") || right.starts_with("ait1") {
        left == right
    } else {
        left.eq_ignore_ascii_case(right)
    }
}

/// Exact editable USD decimal for an integer-micro amount (no float round-trip).
pub fn usd_micros_decimal(micros: u64) -> String {
    let whole = micros / USD_MICROS;
    let fraction = micros % USD_MICROS;
    if fraction == 0 {
        return whole.to_string();
    }
    let fraction = format!("{fraction:06}").trim_end_matches('0').to_owned();
    format!("{whole}.{fraction}")
}

/// Parse a positive USD decimal into exact integer microdollars without floats.
pub fn parse_usd_micros(raw: &str) -> Option<u64> {
    let value = raw.trim();
    let mut pieces = value.split('.');
    let whole = pieces.next()?;
    let fraction = pieces.next().unwrap_or("");
    if pieces.next().is_some()
        || whole.is_empty()
        || !whole.bytes().all(|byte| byte.is_ascii_digit())
        || fraction.len() > 6
        || !fraction.bytes().all(|byte| byte.is_ascii_digit())
    {
        return None;
    }
    let whole_micros = whole.parse::<u64>().ok()?.checked_mul(USD_MICROS)?;
    let padded = format!("{fraction:0<6}");
    let fraction_micros = padded.parse::<u64>().ok()?;
    let total = whole_micros.checked_add(fraction_micros)?;
    (total > 0).then_some(total)
}

/// Whether an HTTP response proves a transfer command did not mutate Mint.
///
/// All unlisted statuses retain the durable pending command and its stable
/// idempotency key. This intentionally treats 408, 425, 429, every 5xx response
/// and transport/invalid-response failures as ambiguous and retryable.
pub fn is_definitive_transfer_failure_status(status: u16) -> bool {
    matches!(status, 400 | 401 | 402 | 403 | 404 | 409 | 410 | 422)
}

// --------------------------------------------------------------------------- //
// Poll status
// --------------------------------------------------------------------------- //

/// Normalized video-generation status (provider strings collapse into three).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GenStatus {
    InProgress,
    Completed,
    Failed,
}

impl GenStatus {
    /// Collapse a server/provider status string to a canonical state. Unknown
    /// but live statuses are treated as in-progress (safer than done/failed).
    pub fn normalize(raw: &str) -> GenStatus {
        match raw.trim().to_ascii_lowercase().as_str() {
            "completed" | "complete" | "succeeded" | "success" => GenStatus::Completed,
            "failed" | "error" | "canceled" | "cancelled" => GenStatus::Failed,
            _ => GenStatus::InProgress,
        }
    }

    pub fn is_terminal(self) -> bool {
        matches!(self, GenStatus::Completed | GenStatus::Failed)
    }
}

// --------------------------------------------------------------------------- //
// Wallet pre-flight (mirrors rf-sync's decision shape)
// --------------------------------------------------------------------------- //

#[derive(Debug, PartialEq, Eq)]
pub enum Preflight {
    /// Covered; `remaining_micros` is the balance after reserving the estimate.
    Ok { remaining_micros: u64 },
    /// Short by `shortfall_micros`; the user must top up before generating.
    Insufficient { shortfall_micros: u64 },
}

/// Can `estimate_micros` be reserved from `available_micros`?
pub fn wallet_preflight(estimate_micros: u64, available_micros: u64) -> Preflight {
    if available_micros >= estimate_micros {
        Preflight::Ok {
            remaining_micros: available_micros - estimate_micros,
        }
    } else {
        Preflight::Insufficient {
            shortfall_micros: estimate_micros - available_micros,
        }
    }
}

/// Public handle resolved for a person-to-person AI-token transfer.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WalletRecipient {
    pub handle: String,
    pub display_name: String,
    #[serde(default)]
    pub kind: String,
    pub can_receive: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct WalletSourceLimits {
    pub per_transfer_micros: u64,
    pub daily_micros: u64,
    pub daily_used_micros: u64,
    pub daily_remaining_micros: Option<u64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct WalletSource {
    pub source_account_id: String,
    pub kind: String,
    pub label: String,
    #[serde(default)]
    pub role: String,
    #[serde(default)]
    pub can_send: bool,
    #[serde(default)]
    pub limits: WalletSourceLimits,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WalletReceiveAddress {
    /// Public Mint destination. It cannot authorize a debit.
    pub address: String,
    pub source: WalletSource,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WalletChallengeRecipient {
    pub handle: String,
    pub display_name: String,
    #[serde(default)]
    pub kind: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WalletTransferChallenge {
    pub challenge_id: String,
    pub source: WalletSource,
    pub recipient: WalletChallengeRecipient,
    pub amount_micros: u64,
    pub binding_sha256: String,
    pub expires_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WalletSavedRecipient {
    pub saved_recipient_id: String,
    pub handle: String,
    pub display_name: String,
    pub label: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WalletTransferBalance {
    pub available_micros: u64,
    #[serde(default)]
    pub held_micros: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WalletTransferParty {
    pub handle: String,
    #[serde(default)]
    pub display_name: String,
    #[serde(default)]
    pub kind: String,
}

/// Portable, account-safe proof for the sender leg of a Mint transfer.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WalletTransferReceiptProof {
    pub sequence: u64,
    pub operation: String,
    pub operation_hash: String,
    pub amount_micros: i64,
    pub receipt_hash: String,
    pub signature: String,
}

/// Canonical POST/GET transfer view shared by the desktop API and workspace.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WalletTransferResult {
    pub transfer_id: String,
    #[serde(default)]
    pub source: WalletSource,
    pub recipient: WalletTransferParty,
    pub amount_micros: u64,
    pub amount_usd: String,
    pub status: String,
    pub mint_first_seq: Option<u64>,
    #[serde(default)]
    pub idempotent_replay: bool,
    #[serde(default)]
    pub created_at: Option<String>,
    #[serde(default)]
    pub completed_at: Option<String>,
    #[serde(default)]
    pub sender_balance: Option<WalletTransferBalance>,
    #[serde(default)]
    pub receipt_proof: Option<WalletTransferReceiptProof>,
}

// --------------------------------------------------------------------------- //
// Request bodies (the runtime POSTs these as JSON)
// --------------------------------------------------------------------------- //

/// Body for `POST /images` — synchronous image generation.
pub fn image_request(model: &str, prompt: &str) -> serde_json::Value {
    serde_json::json!({ "model": model, "prompt": prompt })
}

/// Body for `POST /videos` — submit an async video job. `image_url` is included
/// only when non-empty (image-to-video providers require it).
pub fn video_request(
    model: &str,
    prompt: &str,
    duration: u32,
    aspect_ratio: &str,
    image_url: &str,
) -> serde_json::Value {
    let mut body = serde_json::json!({
        "model": model,
        "prompt": prompt,
        "duration": duration.max(1),
        "aspect_ratio": aspect_ratio,
    });
    if !image_url.is_empty() {
        body["image_url"] = serde_json::Value::String(image_url.to_string());
    }
    body
}

/// Identity-bound variant of [`video_request`]. The server resolves and freezes
/// this passport version before dispatch; omitting `identity_version` selects
/// the latest locked version.
pub fn video_request_with_identity(
    model: &str,
    prompt: &str,
    duration: u32,
    aspect_ratio: &str,
    image_url: &str,
    identity_passport_id: &str,
    identity_version: Option<u32>,
) -> serde_json::Value {
    let mut body = video_request(model, prompt, duration, aspect_ratio, image_url);
    body["identity_passport_id"] = serde_json::Value::String(identity_passport_id.to_string());
    if let Some(version) = identity_version {
        body["identity_version"] = serde_json::json!(version);
    }
    body
}

/// Body for `POST /media/audio` — submit an async music/audio job (mirrors the
/// server `AudioBody`: `{ model, prompt, instrumental }`). Like a video job it
/// is polled to a terminal result and parses as a [`VideoJob`] (the server
/// returns the same `MediaJob` envelope for audio).
pub fn audio_request(model: &str, prompt: &str, instrumental: bool) -> serde_json::Value {
    serde_json::json!({
        "model": model,
        "prompt": prompt,
        "instrumental": instrumental,
    })
}

// --------------------------------------------------------------------------- //
// Response parsing (envelope: { status, data?, message? })
// --------------------------------------------------------------------------- //

#[derive(Debug, PartialEq, Eq)]
pub enum GatewayError {
    /// The body was not valid JSON.
    BadJson,
    /// A non-2xx envelope (carries the server status + message).
    Api { status: u16, message: String },
    /// The envelope was 2xx but the payload was missing/misshaped.
    MissingData,
}

/// Unwrap the MPT-style envelope, returning the `data` payload for a 2xx status
/// or a typed error otherwise (mirrors the SDK/web envelope handling).
pub fn parse_envelope_data(raw: &str) -> Result<serde_json::Value, GatewayError> {
    let env: serde_json::Value = serde_json::from_str(raw).map_err(|_| GatewayError::BadJson)?;
    let status = env.get("status").and_then(|v| v.as_u64()).unwrap_or(0) as u16;
    if !(200..300).contains(&status) {
        let message = env
            .get("message")
            .and_then(|v| v.as_str())
            .unwrap_or("gateway error")
            .to_string();
        return Err(GatewayError::Api { status, message });
    }
    env.get("data").cloned().ok_or(GatewayError::MissingData)
}

/// A synchronous image result (`POST /images`).
#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct ImageResult {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub status: String,
    pub url: String,
    #[serde(default)]
    pub cost_micros: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MediaSettlementReceiptProof {
    #[serde(default)]
    pub sequence: u64,
    #[serde(default)]
    pub operation: String,
    #[serde(default)]
    pub operation_hash: String,
    #[serde(default)]
    pub amount_micros: u64,
    #[serde(default)]
    pub receipt_hash: String,
    #[serde(default)]
    pub signature: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
pub struct MediaExecutionState {
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub provider_request_id: String,
    #[serde(default)]
    pub resumable: bool,
    /// Durable local lineage is additive; cloud/API responses omit it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub local: Option<MediaLocalExecutionHistory>,
}

/// Historical lease retained on an attempt after that lease stops being live.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MediaLocalAttemptLease {
    pub node_id: String,
    pub leased_at_s: u64,
    pub expires_at_s: u64,
}

/// Verification result for one local output. Paths are artifact-root-relative.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MediaLocalArtifactVerification {
    pub verified: bool,
    pub status: String,
    #[serde(default)]
    pub content_id: Option<String>,
    #[serde(default)]
    pub sha256: Option<String>,
    #[serde(default)]
    pub observed_sha256: Option<String>,
    #[serde(default)]
    pub byte_length: Option<u64>,
    #[serde(default)]
    pub relative_reference: Option<String>,
    pub execution_fingerprint: String,
    #[serde(default)]
    pub verified_at_s: Option<u64>,
}

impl MediaLocalArtifactVerification {
    /// Whether the shared reference is a normalized, portable forward-slash
    /// relative path. Native separators stay inside the desktop runtime.
    pub fn has_safe_relative_reference(&self) -> bool {
        self.relative_reference
            .as_deref()
            .map(is_safe_local_artifact_reference)
            .unwrap_or(true)
    }
}

/// Reject absolute, drive-qualified, URI-like and traversal artifact references.
pub fn is_safe_local_artifact_reference(reference: &str) -> bool {
    if reference.is_empty()
        || reference.starts_with('/')
        || reference.starts_with('\\')
        || reference.contains('\\')
        || reference.contains('\0')
        || reference.contains(':')
    {
        return false;
    }
    reference
        .split('/')
        .all(|component| !component.is_empty() && component != "." && component != "..")
}

/// One immutable desktop-local execution attempt. `attempt` is one-based.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MediaLocalAttempt {
    pub attempt: u32,
    pub attempt_id: String,
    pub state: String,
    pub outcome: String,
    pub started_at_s: u64,
    #[serde(default)]
    pub finished_at_s: Option<u64>,
    #[serde(default)]
    pub lease: Option<MediaLocalAttemptLease>,
    #[serde(default)]
    pub artifact_verification: Option<MediaLocalArtifactVerification>,
    #[serde(default)]
    pub retry_parent_attempt: Option<u32>,
    #[serde(default)]
    pub retry_reason: Option<String>,
}

/// Restart-durable, zero-cost local lineage nested under `execution.local`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MediaLocalExecutionHistory {
    pub schema: String,
    pub executor: String,
    pub execution_fingerprint: String,
    #[serde(default)]
    pub attempts: Vec<MediaLocalAttempt>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MediaSettlementAttestation {
    #[serde(default)]
    pub format: String,
    #[serde(default)]
    pub payload_base64url: String,
    #[serde(default)]
    pub digest_sha256: String,
    #[serde(default)]
    pub signer_key_id: String,
    #[serde(default)]
    pub signature_hex: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MediaSettlementEvidence {
    pub request_id: String,
    pub principal: String,
    pub payer_account: String,
    pub receipt: MediaSettlementReceiptProof,
    #[serde(default)]
    pub rail: String,
    #[serde(default)]
    pub outcome: String,
    #[serde(default)]
    pub verified: Option<bool>,
    #[serde(default)]
    pub attestation: Option<MediaSettlementAttestation>,
    #[serde(default)]
    pub settled_at_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MediaSourceSettlementReceipt {
    pub request_id: String,
    pub payer_account: String,
    #[serde(flatten)]
    pub proof: MediaSettlementReceiptProof,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MediaMarginSource {
    pub request_id: String,
    pub source: String,
    pub outcome: String,
    pub model: String,
    pub provider: String,
    #[serde(default)]
    pub cogs_micros: u64,
    pub source_settlement_receipt: MediaSourceSettlementReceipt,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MediaIdentityBinding {
    pub passport_id: String,
    #[serde(default)]
    pub version: u32,
    #[serde(default)]
    pub content_digest: String,
    #[serde(default)]
    pub provider: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub provenance_id: String,
    #[serde(default)]
    pub request_id: String,
    #[serde(default)]
    pub payer_account: String,
    #[serde(default)]
    pub settled_at_ms: u64,
    #[serde(default)]
    pub receipt: Option<MediaSettlementReceiptProof>,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct MediaIdentityOption {
    pub passport_id: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub version: u32,
    #[serde(default)]
    pub content_digest: String,
    #[serde(default)]
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MediaProvenanceExport {
    pub schema: String,
    pub generation_id: String,
    pub modality: String,
    pub model: String,
    pub provider: String,
    pub status: String,
    pub output_url: String,
    pub correlation_id: String,
    pub identity: MediaIdentityBinding,
    #[serde(default)]
    pub settlement_evidence: Option<MediaSettlementEvidence>,
    #[serde(default)]
    pub margin_source: Option<MediaMarginSource>,
}

/// Spendable credits + lifetime gateway spend (`GET /credits`).
#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct Credits {
    #[serde(default)]
    pub available_micros: u64,
    #[serde(default)]
    pub reserved_micros: u64,
    #[serde(default)]
    pub total_gateway_spend_micros: u64,
    #[serde(default)]
    pub currency: String,
}

/// One row of spend-by-model usage (`GET /media/usage`).
#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct UsageRow {
    pub model: String,
    #[serde(default)]
    pub jobs: u64,
    #[serde(default)]
    pub spend_micros: u64,
    #[serde(default)]
    pub seconds: u64,
}

/// Per-generation cost/status detail (`GET /media/generation/{id}`) — the
/// OpenRouter-style `/generation?id=` inspection view (mirrors the API's
/// `media_usage.generation` dict).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct GenerationDetail {
    pub id: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub modality: String,
    #[serde(default)]
    pub provider: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub seconds: u64,
    #[serde(default)]
    pub held_cost_micros: u64,
    #[serde(default)]
    pub actual_cost_micros: u64,
    #[serde(default)]
    pub effective_cost_micros: u64,
    #[serde(default)]
    pub cost_micros: u64,
    #[serde(default)]
    pub settlement_status: String,
    #[serde(default)]
    pub settlement_rail: String,
    #[serde(default)]
    pub output_url: String,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub error: String,
    #[serde(default)]
    pub correlation_id: String,
    #[serde(default)]
    pub provider_request_id: String,
    #[serde(default)]
    pub execution: MediaExecutionState,
    #[serde(default)]
    pub created_at: Option<String>,
    #[serde(default)]
    pub updated_at: Option<String>,
    #[serde(default)]
    pub is_terminal: bool,
    #[serde(default)]
    pub identity: Option<MediaIdentityBinding>,
    #[serde(default)]
    pub settlement_evidence: Option<MediaSettlementEvidence>,
    #[serde(default)]
    pub margin_source: Option<MediaMarginSource>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SettlementProofOutcome {
    Captured,
    Released,
    Pending,
    Unsigned,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SettlementProofView {
    pub outcome: SettlementProofOutcome,
    pub outcome_label: String,
    pub charge_label: String,
    pub proof_label: String,
    pub operation: Option<String>,
    pub receipt_hash: Option<String>,
    pub signature: Option<String>,
    pub signed: bool,
    pub verified: bool,
}

impl GenerationDetail {
    /// The billed cost: actual once settled, else the reserved hold.
    pub fn effective_cost_micros(&self) -> u64 {
        if self.gen_status() == GenStatus::Failed {
            return 0;
        }
        if self.effective_cost_micros > 0 {
            self.effective_cost_micros
        } else if self.actual_cost_micros > 0 {
            self.actual_cost_micros
        } else {
            self.held_cost_micros
        }
    }

    pub fn gen_status(&self) -> GenStatus {
        GenStatus::normalize(&self.status)
    }

    pub fn is_terminal(&self) -> bool {
        self.gen_status().is_terminal()
    }

    /// Interpret settlement evidence without treating status as proof of a charge.
    /// Desktop-local work is always presented as zero-cost and unsigned.
    pub fn settlement_proof_view(&self) -> SettlementProofView {
        if self.execution.kind == "desktop_local"
            || matches!(self.settlement_rail.as_str(), "local" | "desktop_local")
        {
            return SettlementProofView {
                outcome: SettlementProofOutcome::Unsigned,
                outcome_label: "Unsigned local execution".into(),
                charge_label: "$0.00 charged".into(),
                proof_label: "No settlement receipt (local)".into(),
                operation: None,
                receipt_hash: None,
                signature: None,
                signed: false,
                verified: false,
            };
        }

        if let Some(evidence) = &self.settlement_evidence {
            let receipt = &evidence.receipt;
            let operation = receipt.operation.trim();
            let normalized = operation.to_ascii_lowercase();
            let captured = normalized == "capture" || normalized.ends_with(".capture");
            let released = normalized == "release"
                || normalized == "void"
                || normalized.ends_with(".release")
                || normalized.ends_with(".void");
            let receipt_hash = non_empty(&receipt.receipt_hash).or_else(|| {
                evidence
                    .attestation
                    .as_ref()
                    .and_then(|attestation| non_empty(&attestation.digest_sha256))
            });
            let signature = non_empty(&receipt.signature).or_else(|| {
                evidence
                    .attestation
                    .as_ref()
                    .and_then(|attestation| non_empty(&attestation.signature_hex))
            });
            let signed = receipt_hash.is_some() && signature.is_some();
            let verified = evidence.verified == Some(true);

            return SettlementProofView {
                outcome: if captured {
                    SettlementProofOutcome::Captured
                } else if released {
                    SettlementProofOutcome::Released
                } else {
                    SettlementProofOutcome::Unknown
                },
                outcome_label: if captured {
                    "Captured from receipt"
                } else if released {
                    "Released from receipt"
                } else {
                    "Unknown receipt operation"
                }
                .into(),
                charge_label: if captured {
                    format!("{} charged", format_usd_micros(receipt.amount_micros))
                } else if released {
                    "$0.00 charged".into()
                } else {
                    format!(
                        "Receipt amount {}",
                        format_usd_micros(receipt.amount_micros)
                    )
                },
                proof_label: if verified && signed {
                    "Verified signed settlement receipt"
                } else if signed {
                    "Signed receipt · verification not reported"
                } else {
                    "Unsigned receipt data"
                }
                .into(),
                operation: (!operation.is_empty()).then(|| operation.to_string()),
                receipt_hash,
                signature,
                signed,
                verified,
            };
        }

        if self.settlement_status == "held" {
            return SettlementProofView {
                outcome: SettlementProofOutcome::Pending,
                outcome_label: "Pending settlement".into(),
                charge_label: format!(
                    "$0.00 charged · {} held",
                    format_usd_micros(self.held_cost_micros)
                ),
                proof_label: "No settlement receipt yet".into(),
                operation: None,
                receipt_hash: None,
                signature: None,
                signed: false,
                verified: false,
            };
        }

        let zero_charge =
            self.gen_status() == GenStatus::Failed || self.settlement_status == "released";
        SettlementProofView {
            outcome: SettlementProofOutcome::Unsigned,
            outcome_label: "Settlement unverified".into(),
            charge_label: if zero_charge {
                "$0.00 charged".into()
            } else {
                format!(
                    "Reported cost {}",
                    format_usd_micros(self.effective_cost_micros())
                )
            },
            proof_label: "No signed settlement receipt".into(),
            operation: None,
            receipt_hash: None,
            signature: None,
            signed: false,
            verified: false,
        }
    }
}

fn non_empty(value: &str) -> Option<String> {
    let value = value.trim();
    (!value.is_empty()).then(|| value.to_string())
}

/// Submit, poll, timeline, and detail all deserialize to one durable shape.
pub type VideoJob = GenerationDetail;

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct GenerationPage {
    #[serde(default)]
    pub generations: Vec<GenerationDetail>,
    #[serde(default)]
    pub limit: u64,
    #[serde(default)]
    pub offset: u64,
    #[serde(default)]
    pub has_more: bool,
}

/// Deserialize a typed value out of an already-unwrapped `data` payload.
pub fn parse_data<T: for<'de> Deserialize<'de>>(
    data: &serde_json::Value,
) -> Result<T, GatewayError> {
    serde_json::from_value(data.clone()).map_err(|_| GatewayError::MissingData)
}

/// Total spend across usage rows (integer-micro), for a header/summary line.
pub fn usage_total_spend_micros(rows: &[UsageRow]) -> u64 {
    rows.iter().map(|r| r.spend_micros).sum()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn video_model() -> MediaModel {
        MediaModel {
            id: "kwaivgi/kling-v1.6".into(),
            modality: Modality::Video,
            provider: "kling-fal".into(),
            price_micros: 84_000,
            unit: "second".into(),
            max_seconds: 10,
            description: String::new(),
        }
    }

    fn image_model() -> MediaModel {
        MediaModel {
            id: "openai/gpt-image-1".into(),
            modality: Modality::Image,
            provider: "openai-image".into(),
            price_micros: 40_000,
            unit: "image".into(),
            max_seconds: 0,
            description: String::new(),
        }
    }

    #[test]
    fn video_cost_is_per_second_clamped() {
        let m = video_model();
        assert_eq!(m.estimate_cost_micros(5), 5 * 84_000);
        // clamps to max_seconds (10) and to a floor of 1s.
        assert_eq!(m.estimate_cost_micros(20), 10 * 84_000);
        assert_eq!(m.estimate_cost_micros(0), 84_000);
    }

    #[test]
    fn image_cost_is_flat() {
        assert_eq!(image_model().estimate_cost_micros(999), 40_000);
    }

    #[test]
    fn audio_cost_is_flat_per_generation() {
        let m = MediaModel {
            id: "suno/v4".into(),
            modality: Modality::Audio,
            provider: "suno".into(),
            price_micros: 80_000,
            unit: "clip".into(),
            max_seconds: 0,
            description: String::new(),
        };
        assert_eq!(m.estimate_cost_micros(0), 80_000);
        assert_eq!(m.estimate_cost_micros(240), 80_000); // duration-independent
    }

    #[test]
    fn formats_micros_as_usd() {
        assert_eq!(format_usd_micros(84_000), "$0.084");
        assert_eq!(format_usd_micros(2_000_000), "$2.00");
        assert_eq!(format_usd_micros(0), "$0.00");
    }

    #[test]
    fn formats_and_compares_handles_and_public_wallet_addresses() {
        assert_eq!(format_wallet_destination("bob"), "@bob");
        assert_eq!(format_wallet_destination("@bob"), "@bob");
        assert_eq!(format_wallet_destination("ait1qRoute"), "ait1qRoute");
        assert_eq!(
            format_wallet_destination("agent:caption-bot"),
            "agent:caption-bot"
        );
        assert!(wallet_destinations_equal("Bob", "@bob"));
        assert!(wallet_destinations_equal("ait1qRoute", "ait1qRoute"));
        assert!(!wallet_destinations_equal("ait1qRoute", "ait1qroute"));
    }

    #[test]
    fn recipient_validation_accepts_every_product_destination_kind() {
        assert!(valid_wallet_destination("alice"));
        assert!(valid_wallet_destination("ait1qrecipient123"));
        assert!(valid_wallet_destination("workspace:video-studio"));
        assert!(valid_wallet_destination("agent:caption-bot"));
        assert!(valid_wallet_destination("service:render-farm"));

        assert!(!valid_wallet_destination("agent:ab"));
        assert!(!valid_wallet_destination("agent:-caption"));
        assert!(!valid_wallet_destination("person:alice"));
        assert!(!valid_wallet_destination("agent:Caption-Bot"));
        assert!(!valid_wallet_destination("../agent:caption-bot"));
    }

    #[test]
    fn parses_usd_without_floating_point() {
        assert_eq!(parse_usd_micros("5"), Some(5_000_000));
        assert_eq!(parse_usd_micros("0.000001"), Some(1));
        assert_eq!(parse_usd_micros("12.34"), Some(12_340_000));
        assert_eq!(parse_usd_micros("0"), None);
        assert_eq!(parse_usd_micros("1.0000001"), None);
        assert_eq!(parse_usd_micros("1.2.3"), None);
    }

    #[test]
    fn transfer_failure_classification_preserves_ambiguous_outcomes() {
        for status in [400, 401, 402, 403, 404, 409, 410, 422] {
            assert!(is_definitive_transfer_failure_status(status));
        }
        for status in [0, 408, 425, 429, 500, 502, 503] {
            assert!(!is_definitive_transfer_failure_status(status));
        }
    }

    #[test]
    fn formats_editable_usd_without_losing_micros() {
        assert_eq!(usd_micros_decimal(5_000_000), "5");
        assert_eq!(usd_micros_decimal(12_340_001), "12.340001");
        assert_eq!(usd_micros_decimal(1), "0.000001");
    }

    #[test]
    fn status_normalizes_and_detects_terminal() {
        assert_eq!(GenStatus::normalize("SUCCEEDED"), GenStatus::Completed);
        assert_eq!(GenStatus::normalize("failed"), GenStatus::Failed);
        assert_eq!(GenStatus::normalize("in_progress"), GenStatus::InProgress);
        assert_eq!(GenStatus::normalize("weird"), GenStatus::InProgress);
        assert!(GenStatus::Completed.is_terminal());
        assert!(!GenStatus::InProgress.is_terminal());
    }

    #[test]
    fn preflight_ok_and_short() {
        assert_eq!(
            wallet_preflight(420_000, 1_000_000),
            Preflight::Ok {
                remaining_micros: 580_000
            }
        );
        assert_eq!(
            wallet_preflight(420_000, 100_000),
            Preflight::Insufficient {
                shortfall_micros: 320_000
            }
        );
    }

    #[test]
    fn transfer_view_parses_portable_receipt_and_nullable_recovery_proof() {
        let proved: WalletTransferResult = serde_json::from_value(serde_json::json!({
            "transfer_id": "tr_1",
            "recipient": {"handle": "bob"},
            "amount_micros": 2_000_000,
            "amount_usd": "2.00",
            "status": "completed",
            "mint_first_seq": 7,
            "idempotent_replay": false,
            "created_at": null,
            "completed_at": "2026-08-27T00:00:00Z",
            "receipt_proof": {
                "sequence": 7,
                "operation": "transfer",
                "operation_hash": "op-hash",
                "amount_micros": -2_000_000,
                "receipt_hash": "receipt-hash",
                "signature": "signature"
            }
        }))
        .unwrap();
        assert_eq!(
            proved
                .receipt_proof
                .as_ref()
                .map(|proof| proof.receipt_hash.as_str()),
            Some("receipt-hash")
        );

        let mut unproved = serde_json::to_value(&proved).unwrap();
        unproved["receipt_proof"] = serde_json::Value::Null;
        let unproved: WalletTransferResult = serde_json::from_value(unproved).unwrap();
        assert!(unproved.receipt_proof.is_none());
    }

    #[test]
    fn video_request_omits_empty_image_url() {
        let b = video_request("m", "p", 5, "9:16", "");
        assert!(b.get("image_url").is_none());
        assert_eq!(b["duration"], 5);
        let b2 = video_request("m", "p", 0, "9:16", "https://img/x.png");
        assert_eq!(b2["image_url"], "https://img/x.png");
        assert_eq!(b2["duration"], 1); // floored
    }

    #[test]
    fn identity_video_request_pins_passport_version() {
        let body = video_request_with_identity(
            "runwayml/gen-4",
            "walk through rain",
            5,
            "9:16",
            "https://owned/ref.png",
            "psp_owner",
            Some(3),
        );
        assert_eq!(body["identity_passport_id"], "psp_owner");
        assert_eq!(body["identity_version"], 3);
        assert_eq!(body["image_url"], "https://owned/ref.png");
    }

    #[test]
    fn parses_identity_options_and_portable_provenance() {
        let options: Vec<MediaIdentityOption> = serde_json::from_value(serde_json::json!([
            {
                "passport_id": "psp_1",
                "kind": "character",
                "version": 3,
                "content_digest": "ni:///sha-256;locked",
                "status": "locked"
            }
        ]))
        .unwrap();
        assert_eq!(options[0].version, 3);

        let proof: MediaProvenanceExport = serde_json::from_value(serde_json::json!({
            "schema": "menivor.media-provenance/v1",
            "generation_id": "job_1",
            "modality": "video",
            "model": "runwayml/gen-4",
            "provider": "runway",
            "status": "completed",
            "output_url": "https://cdn/out.mp4",
            "correlation_id": "gateway:job_1",
            "identity": {
                "passport_id": "psp_1",
                "version": 3,
                "content_digest": "ni:///sha-256;locked",
                "provider": "runway",
                "status": "attested",
                "provenance_id": "gen_ext_1",
                "request_id": "job_1",
                "payer_account": "acct_owner",
                "settled_at_ms": 123,
                "receipt": null
            }
        }))
        .unwrap();
        assert_eq!(proof.identity.provenance_id, "gen_ext_1");
    }

    #[test]
    fn image_request_shape() {
        let b = image_request("openai/gpt-image-1", "a red panda");
        assert_eq!(b["model"], "openai/gpt-image-1");
        assert_eq!(b["prompt"], "a red panda");
    }

    #[test]
    fn audio_request_shape() {
        let b = audio_request("suno/v4", "lofi beat to study to", true);
        assert_eq!(b["model"], "suno/v4");
        assert_eq!(b["prompt"], "lofi beat to study to");
        assert_eq!(b["instrumental"], true);
        // Defaults to vocals when not instrumental.
        let vocal = audio_request("suno/v4", "a pop hook", false);
        assert_eq!(vocal["instrumental"], false);
    }

    #[test]
    fn audio_job_parses_like_video_job() {
        // The server returns the same MediaJob envelope for audio; VideoJob parses it.
        let raw = r#"{"status":200,"data":{"id":"a1","model":"suno/v4","status":"in_progress","url":"","cost_micros":80000}}"#;
        let data = parse_envelope_data(raw).unwrap();
        let job: VideoJob = parse_data(&data).unwrap();
        assert_eq!(job.id, "a1");
        assert!(!job.is_terminal());
        assert_eq!(job.cost_micros, 80_000);
    }

    #[test]
    fn envelope_unwraps_success_data() {
        let raw = r#"{"status":200,"data":{"id":"v1","status":"completed","url":"https://cdn/o.mp4","cost_micros":420000},"message":null}"#;
        let data = parse_envelope_data(raw).unwrap();
        let job: VideoJob = parse_data(&data).unwrap();
        assert_eq!(job.id, "v1");
        assert!(job.is_terminal());
        assert_eq!(job.url, "https://cdn/o.mp4");
        assert_eq!(job.cost_micros, 420_000);
    }

    #[test]
    fn envelope_maps_api_error() {
        let raw = r#"{"status":503,"data":null,"message":"req-1: GEMINI_API_KEY not configured"}"#;
        match parse_envelope_data(raw) {
            Err(GatewayError::Api { status, message }) => {
                assert_eq!(status, 503);
                assert!(message.contains("GEMINI_API_KEY"));
            }
            other => panic!("expected Api error, got {other:?}"),
        }
    }

    #[test]
    fn envelope_rejects_bad_json() {
        assert_eq!(parse_envelope_data("not json"), Err(GatewayError::BadJson));
    }

    #[test]
    fn parses_credits_and_usage_total() {
        let raw = r#"{"status":200,"data":{"available_micros":99580000,"reserved_micros":0,"total_gateway_spend_micros":420000,"currency":"USD"}}"#;
        let data = parse_envelope_data(raw).unwrap();
        let c: Credits = parse_data(&data).unwrap();
        assert_eq!(c.available_micros, 99_580_000);
        assert_eq!(c.total_gateway_spend_micros, 420_000);

        let rows = vec![
            UsageRow {
                model: "a".into(),
                jobs: 1,
                spend_micros: 420_000,
                seconds: 5,
            },
            UsageRow {
                model: "b".into(),
                jobs: 2,
                spend_micros: 80_000,
                seconds: 0,
            },
        ];
        assert_eq!(usage_total_spend_micros(&rows), 500_000);
    }

    #[test]
    fn image_result_deserializes() {
        let raw = r#"{"status":200,"data":{"model":"openai/gpt-image-1","url":"https://oai/p.png","cost_micros":40000}}"#;
        let data = parse_envelope_data(raw).unwrap();
        let img: ImageResult = parse_data(&data).unwrap();
        assert_eq!(img.url, "https://oai/p.png");
        assert_eq!(img.cost_micros, 40_000);
    }

    #[test]
    fn generation_detail_parses_and_picks_effective_cost() {
        let raw = r#"{"status":200,"data":{"id":"v1","model":"kwaivgi/kling-v1.6","modality":"video","provider":"prism:kling-fal","status":"completed","seconds":5,"held_cost_micros":420000,"actual_cost_micros":420000,"effective_cost_micros":420000,"cost_micros":420000,"settlement_status":"settled","output_url":"https://cdn/o.mp4","url":"https://cdn/o.mp4","error":"","correlation_id":"gateway_v1","provider_request_id":"gen_prism_1","execution":{"kind":"prism","provider_request_id":"gen_prism_1","resumable":false},"settlement_evidence":{"request_id":"gateway_v1","principal":"acct_1","payer_account":"acct_1","settled_at_ms":1234,"receipt":{"sequence":7,"operation":"hold.capture","operation_hash":"op","amount_micros":420000,"receipt_hash":"hash","signature":"sig"}}}}"#;
        let data = parse_envelope_data(raw).unwrap();
        let detail: GenerationDetail = parse_data(&data).unwrap();
        assert_eq!(detail.id, "v1");
        assert_eq!(detail.modality, "video");
        assert_eq!(detail.provider, "prism:kling-fal");
        assert_eq!(detail.effective_cost_micros(), 420_000);
        assert_eq!(detail.execution.kind, "prism");
        assert_eq!(detail.execution.provider_request_id, "gen_prism_1");
        assert!(!detail.execution.resumable);
        assert_eq!(
            detail
                .settlement_evidence
                .as_ref()
                .unwrap()
                .receipt
                .signature,
            "sig"
        );
        let proof = detail.settlement_proof_view();
        assert_eq!(proof.outcome, SettlementProofOutcome::Captured);
        assert_eq!(proof.charge_label, "$0.42 charged");
        assert_eq!(proof.operation.as_deref(), Some("hold.capture"));
        assert_eq!(proof.receipt_hash.as_deref(), Some("hash"));
        assert_eq!(proof.signature.as_deref(), Some("sig"));
        assert!(proof.signed);
        assert!(!proof.verified);
        assert_eq!(
            proof.proof_label,
            "Signed receipt · verification not reported"
        );

        // In progress: no actual cost yet -> effective falls back to the hold.
        let mut pending = detail.clone();
        pending.actual_cost_micros = 0;
        pending.effective_cost_micros = 0;
        pending.status = "in_progress".into();
        assert_eq!(pending.effective_cost_micros(), 420_000);

        pending.status = "failed".into();
        assert_eq!(pending.effective_cost_micros(), 0);
    }

    #[test]
    fn generation_detail_keeps_cloud_rows_backward_compatible() {
        let detail: GenerationDetail = serde_json::from_value(serde_json::json!({
            "id": "cloud-1",
            "status": "in_progress",
            "execution": {
                "kind": "prism",
                "provider_request_id": "provider-1",
                "resumable": true
            }
        }))
        .unwrap();
        assert!(detail.execution.local.is_none());

        let encoded = serde_json::to_value(&detail).unwrap();
        assert!(encoded["execution"].get("local").is_none());
    }

    #[test]
    fn local_generation_history_roundtrips_verified_retry_lineage() {
        let detail: GenerationDetail = serde_json::from_value(serde_json::json!({
            "id": "local-1",
            "model": "local-render",
            "modality": "video",
            "provider": "desktop-local",
            "status": "completed",
            "held_cost_micros": 0,
            "actual_cost_micros": 0,
            "effective_cost_micros": 0,
            "cost_micros": 0,
            "settlement_status": "released",
            "output_url": "",
            "url": "",
            "execution": {
                "kind": "desktop_local",
                "provider_request_id": "local-1",
                "resumable": false,
                "local": {
                    "schema": "menivor.desktop-local-execution/v1",
                    "executor": "ffmpeg-local-v1",
                    "execution_fingerprint": "fp-1",
                    "attempts": [{
                        "attempt": 1,
                        "attempt_id": "attempt-1",
                        "state": "failed",
                        "outcome": "artifact_corrupt",
                        "started_at_s": 10,
                        "finished_at_s": 12,
                        "lease": {
                            "node_id": "desktop-node",
                            "leased_at_s": 10,
                            "expires_at_s": 20
                        },
                        "artifact_verification": {
                            "verified": false,
                            "status": "digest_mismatch",
                            "content_id": null,
                            "sha256": "aa",
                            "observed_sha256": "bb",
                            "byte_length": null,
                            "relative_reference": null,
                            "execution_fingerprint": "fp-1",
                            "verified_at_s": null
                        },
                        "retry_parent_attempt": null,
                        "retry_reason": null
                    }, {
                        "attempt": 2,
                        "attempt_id": "attempt-2",
                        "state": "completed",
                        "outcome": "verified",
                        "started_at_s": 13,
                        "finished_at_s": 15,
                        "lease": {
                            "node_id": "desktop-node",
                            "leased_at_s": 13,
                            "expires_at_s": 23
                        },
                        "artifact_verification": {
                            "verified": true,
                            "status": "verified",
                            "content_id": "cc",
                            "sha256": "cc",
                            "observed_sha256": null,
                            "byte_length": 42,
                            "relative_reference": "outputs/cc/output.mp4",
                            "execution_fingerprint": "fp-1",
                            "verified_at_s": 15
                        },
                        "retry_parent_attempt": 1,
                        "retry_reason": "artifact_corrupt"
                    }]
                }
            },
            "settlement_evidence": null,
            "margin_source": null
        }))
        .unwrap();

        let local = detail.execution.local.as_ref().unwrap();
        assert_eq!(local.attempts.len(), 2);
        assert_eq!(local.attempts[1].retry_parent_attempt, Some(1));
        let verified = local.attempts[1].artifact_verification.as_ref().unwrap();
        assert!(verified.verified);
        assert!(verified.has_safe_relative_reference());
        assert_eq!(detail.effective_cost_micros(), 0);
        assert!(detail.settlement_evidence.is_none());
        assert!(detail.margin_source.is_none());
        assert_eq!(detail.settlement_status, "released");
        assert!(detail.output_url.is_empty());
        assert!(detail.url.is_empty());
        let proof = detail.settlement_proof_view();
        assert_eq!(proof.outcome, SettlementProofOutcome::Unsigned);
        assert_eq!(proof.outcome_label, "Unsigned local execution");
        assert_eq!(proof.charge_label, "$0.00 charged");
        assert_eq!(proof.proof_label, "No settlement receipt (local)");
        assert!(proof.receipt_hash.is_none());
        assert!(proof.signature.is_none());
        assert!(!proof.signed);
        assert!(!proof.verified);

        let encoded = serde_json::to_value(&detail).unwrap();
        let encoded_text = encoded.to_string();
        assert!(!encoded_text.contains("file://"));
        assert!(!encoded_text.contains("/Users/"));
        assert!(!encoded_text.contains("lease_token"));
        let restored: GenerationDetail = serde_json::from_value(encoded).unwrap();
        assert_eq!(restored, detail);
    }

    #[test]
    fn settlement_proof_distinguishes_release_from_unverified_failure() {
        let mut detail: GenerationDetail = serde_json::from_value(serde_json::json!({
            "id": "failed-1",
            "status": "failed",
            "held_cost_micros": 420000,
            "effective_cost_micros": 420000,
            "settlement_status": "released",
            "execution": { "kind": "prism" }
        }))
        .unwrap();

        let unverified = detail.settlement_proof_view();
        assert_eq!(unverified.outcome, SettlementProofOutcome::Unsigned);
        assert_eq!(unverified.outcome_label, "Settlement unverified");
        assert_eq!(unverified.charge_label, "$0.00 charged");

        detail.settlement_evidence = Some(MediaSettlementEvidence {
            request_id: "request-1".into(),
            principal: "account-1".into(),
            payer_account: "account-1".into(),
            rail: "mint".into(),
            outcome: "released".into(),
            verified: Some(true),
            attestation: Some(MediaSettlementAttestation {
                format: "mint-hold-settlement-attestation-v1".into(),
                payload_base64url: "payload".into(),
                digest_sha256: "attestation-digest".into(),
                signer_key_id: "signer-1".into(),
                signature_hex: "attestation-signature".into(),
            }),
            settled_at_ms: 1,
            receipt: MediaSettlementReceiptProof {
                sequence: 2,
                operation: "hold.release".into(),
                operation_hash: "operation-hash".into(),
                amount_micros: 420_000,
                receipt_hash: "receipt-hash".into(),
                signature: "receipt-signature".into(),
            },
        });
        let released = detail.settlement_proof_view();
        assert_eq!(released.outcome, SettlementProofOutcome::Released);
        assert_eq!(released.outcome_label, "Released from receipt");
        assert_eq!(released.charge_label, "$0.00 charged");
        assert_eq!(released.signature.as_deref(), Some("receipt-signature"));
        assert!(released.signed);
        assert!(released.verified);
        assert_eq!(released.proof_label, "Verified signed settlement receipt");

        detail.settlement_rail = "local".into();
        let local = detail.settlement_proof_view();
        assert_eq!(local.outcome, SettlementProofOutcome::Unsigned);
        assert_eq!(local.charge_label, "$0.00 charged");
        assert!(local.receipt_hash.is_none());
        assert!(!local.verified);
    }

    #[test]
    fn local_artifact_reference_rejects_escape_and_absolute_forms() {
        assert!(is_safe_local_artifact_reference("outputs/aa/output.mp4"));
        for unsafe_reference in [
            "../output.mp4",
            "outputs/../output.mp4",
            "/tmp/output.mp4",
            r"C:\\tmp\\output.mp4",
            r"\\server\\share\\output.mp4",
            r"outputs\\aa\\output.mp4",
            "file://artifact/output.mp4",
            "outputs//output.mp4",
        ] {
            assert!(
                !is_safe_local_artifact_reference(unsafe_reference),
                "accepted unsafe artifact reference {unsafe_reference:?}"
            );
        }
    }

    #[test]
    fn generation_page_restores_safe_timeline_rows() {
        let data = serde_json::json!({
            "generations": [{
                "id": "job-1",
                "model": "kwaivgi/kling-v1.6",
                "modality": "video",
                "provider": "prism:kling-fal",
                "status": "completed",
                "seconds": 5,
                "held_cost_micros": 84_000,
                "actual_cost_micros": 80_000,
                "effective_cost_micros": 80_000,
                "settlement_status": "settled",
                "output_url": "https://cdn/out.mp4",
                "error": "",
                "correlation_id": "gateway:job-1",
                "created_at": "2026-08-27T00:00:00Z",
                "updated_at": "2026-08-27T00:01:00Z",
                "is_terminal": true
            }],
            "limit": 24,
            "offset": 0,
            "has_more": false
        });
        let page: GenerationPage = parse_data(&data).unwrap();
        assert_eq!(page.generations.len(), 1);
        assert_eq!(page.generations[0].effective_cost_micros(), 80_000);
        assert_eq!(page.generations[0].correlation_id, "gateway:job-1");
        assert!(page.generations[0].is_terminal);
    }

    #[test]
    fn media_model_roundtrips_json() {
        let m = video_model();
        let s = serde_json::to_string(&m).unwrap();
        let back: MediaModel = serde_json::from_str(&s).unwrap();
        assert_eq!(back.id, m.id);
        assert_eq!(back.modality, Modality::Video);
    }

    #[test]
    fn account_source_challenge_parses_limits_without_internal_ref() {
        let value = serde_json::json!({
            "challenge_id": "challenge_1",
            "source": {
                "source_account_id": "workspace_1", "kind": "workspace", "label": "Studio",
                "role": "owner", "can_send": true,
                "limits": {"per_transfer_micros": 5000000, "daily_micros": 20000000, "daily_used_micros": 3000000, "daily_remaining_micros": 17000000}
            },
            "recipient": {"handle": "bob", "display_name": "Bob"},
            "amount_micros": 2000000,
            "binding_sha256": "binding",
            "expires_at": "2099-01-01T00:00:00Z"
        });
        let challenge: WalletTransferChallenge = serde_json::from_value(value).unwrap();
        assert_eq!(challenge.source.source_account_id, "workspace_1");
        assert_eq!(
            challenge.source.limits.daily_remaining_micros,
            Some(17_000_000)
        );
        assert!(!serde_json::to_value(&challenge).unwrap()["source"]
            .as_object()
            .unwrap()
            .contains_key("ref"));
    }

    #[test]
    fn transfer_result_carries_safe_source_for_recovery_matching() {
        let value = serde_json::json!({
            "transfer_id": "tr_1",
            "source": {"source_account_id": "personal_1", "kind": "personal", "label": "Personal"},
            "recipient": {"handle": "bob"}, "amount_micros": 2000000, "amount_usd": "2.00",
            "status": "completed", "mint_first_seq": 7, "receipt_proof": null
        });
        let transfer: WalletTransferResult = serde_json::from_value(value).unwrap();
        assert_eq!(transfer.source.kind, "personal");
        assert_eq!(transfer.source.label, "Personal");
    }
}
