//! Authenticated person-to-person AI-token transfer contract.

use rf_gateway::{
    valid_wallet_destination, Credits, WalletReceiveAddress, WalletRecipient, WalletSavedRecipient,
    WalletSource, WalletTransferChallenge, WalletTransferResult,
};
use serde::{Deserialize, Serialize};

use super::{ApiClient, ApiFailure, ApiFailureKind};

#[derive(Serialize)]
struct TransferRequest<'a> {
    source_account_id: &'a str,
    challenge_id: &'a str,
    recipient_handle: &'a str,
    amount_micros: u64,
}

#[derive(Serialize)]
struct ChallengeRequest<'a> {
    source_account_id: &'a str,
    recipient_handle: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    saved_recipient_id: Option<&'a str>,
    amount_micros: u64,
}

#[derive(Deserialize)]
struct SourcesResponse {
    sources: Vec<WalletSource>,
}

#[derive(Deserialize)]
struct SavedRecipientsResponse {
    recipients: Vec<WalletSavedRecipient>,
}

#[derive(Serialize)]
struct SaveRecipientRequest<'a> {
    source_account_id: &'a str,
    recipient_handle: &'a str,
    label: &'a str,
}

#[derive(Serialize)]
struct ReceiveAddressRequest<'a> {
    source_account_id: &'a str,
}

impl ApiClient {
    /// Read the Mint-authoritative balance for one already-authorized source.
    pub(crate) fn get_wallet_source_balance(
        &self,
        source_account_id: &str,
    ) -> Result<Credits, ApiFailure> {
        let source = validate_transfer_id(source_account_id)?;
        self.get(&format!("/wallet?source_account_id={source}"))
    }

    pub(crate) fn get_wallet_receive_address(
        &self,
        source_account_id: &str,
    ) -> Result<WalletReceiveAddress, ApiFailure> {
        let source = validate_transfer_id(source_account_id)?;
        self.post(
            "/wallet/receive-addresses",
            &ReceiveAddressRequest {
                source_account_id: source,
            },
        )
    }

    pub(crate) fn list_wallet_sources(&self) -> Result<Vec<WalletSource>, ApiFailure> {
        self.get::<SourcesResponse>("/wallet/sources")
            .map(|value| value.sources)
    }

    pub(crate) fn create_wallet_transfer_challenge(
        &self,
        source_account_id: &str,
        recipient_handle: &str,
        saved_recipient_id: Option<&str>,
        amount_micros: u64,
        idempotency_key: &str,
    ) -> Result<WalletTransferChallenge, ApiFailure> {
        self.post_idempotent(
            "/wallet/transfer-challenges",
            &ChallengeRequest {
                source_account_id,
                recipient_handle,
                saved_recipient_id,
                amount_micros,
            },
            idempotency_key,
        )
    }

    /// Resolve an exact public handle or Mint address. Never searches by email.
    pub(crate) fn resolve_wallet_recipient(
        &self,
        raw_handle: &str,
    ) -> Result<WalletRecipient, ApiFailure> {
        let handle = raw_handle.trim().trim_start_matches('@');
        if !valid_wallet_destination(handle) {
            return Err(ApiFailure {
                kind: ApiFailureKind::Request,
                status: None,
                message: "Enter a public handle, typed destination, or ait1 receive address."
                    .into(),
            });
        }
        self.get(&format!("/wallet/recipients/{handle}"))
    }

    /// Atomically send Mint-backed AI tokens using the caller's stable key.
    pub(crate) fn send_wallet_transfer(
        &self,
        source_account_id: &str,
        challenge_id: &str,
        recipient_handle: &str,
        amount_micros: u64,
        idempotency_key: &str,
    ) -> Result<WalletTransferResult, ApiFailure> {
        self.post_idempotent(
            "/wallet/transfers",
            &TransferRequest {
                source_account_id,
                challenge_id,
                recipient_handle,
                amount_micros,
            },
            idempotency_key,
        )
    }

    pub(crate) fn list_saved_recipients(
        &self,
        source_account_id: &str,
    ) -> Result<Vec<WalletSavedRecipient>, ApiFailure> {
        let source = validate_transfer_id(source_account_id)?;
        self.get::<SavedRecipientsResponse>(&format!(
            "/wallet/saved-recipients?source_account_id={source}"
        ))
        .map(|value| value.recipients)
    }

    pub(crate) fn save_wallet_recipient(
        &self,
        source_account_id: &str,
        recipient_handle: &str,
        label: &str,
    ) -> Result<WalletSavedRecipient, ApiFailure> {
        self.post(
            "/wallet/saved-recipients",
            &SaveRecipientRequest {
                source_account_id,
                recipient_handle,
                label,
            },
        )
    }

    pub(crate) fn delete_wallet_recipient(
        &self,
        source_account_id: &str,
        saved_recipient_id: &str,
    ) -> Result<serde_json::Value, ApiFailure> {
        let source = validate_transfer_id(source_account_id)?;
        let saved = validate_transfer_id(saved_recipient_id)?;
        self.delete(&format!(
            "/wallet/saved-recipients/{saved}?source_account_id={source}"
        ))
    }

    /// Recover one sender-owned transfer. This GET can never create a transfer.
    pub(crate) fn get_wallet_transfer(
        &self,
        raw_transfer_id: &str,
    ) -> Result<WalletTransferResult, ApiFailure> {
        let transfer_id = validate_transfer_id(raw_transfer_id)?;
        self.get(&format!("/wallet/transfers/{transfer_id}"))
    }
}

fn validate_transfer_id(raw_transfer_id: &str) -> Result<&str, ApiFailure> {
    let transfer_id = raw_transfer_id.trim();
    if transfer_id.is_empty()
        || transfer_id.len() > 128
        || !transfer_id
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "._-".contains(character))
    {
        return Err(ApiFailure {
            kind: ApiFailureKind::Request,
            status: None,
            message: "Enter a valid transfer ID (letters, numbers, ., _ or -).".into(),
        });
    }
    Ok(transfer_id)
}

#[cfg(test)]
mod tests {
    use super::validate_transfer_id;

    #[test]
    fn transfer_id_is_confined_to_one_path_segment() {
        assert_eq!(validate_transfer_id(" tr_123 ").unwrap(), "tr_123");
        assert!(validate_transfer_id("../wallet").is_err());
        assert!(validate_transfer_id("tr/other").is_err());
        assert!(validate_transfer_id("").is_err());
    }
}
