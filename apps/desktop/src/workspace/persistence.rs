//! Versioned, non-secret workspace cache owned by the background worker.

use std::fs;
use std::io;

use serde::{Deserialize, Serialize};

use crate::api::WalletTransferResult;
use crate::config::app_data_dir;
use crate::domain::{BrollDraft, JobSnapshot, ReelDraft};
use crate::workspace::{DesktopState, PendingWalletTransfer};

const CACHE_VERSION: u8 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub(crate) struct WorkspaceCache {
    version: u8,
    pub reel_draft: ReelDraft,
    pub broll_draft: BrollDraft,
    pub jobs: Vec<JobSnapshot>,
    pub selected_job_id: Option<String>,
    /// Last known transfer snapshot. It contains no internal Mint account id.
    #[serde(default)]
    pub wallet_transfer: Option<WalletTransferResult>,
    #[serde(default)]
    pub pending_wallet_transfer: Option<PendingWalletTransfer>,
}

impl WorkspaceCache {
    pub(crate) fn snapshot(state: &DesktopState) -> Self {
        let mut jobs = state.jobs.clone();
        for job in &mut jobs {
            // Signed preview URLs expire and are never durable cache data.
            job.result_url.clear();
        }
        Self {
            version: CACHE_VERSION,
            reel_draft: state.reel_draft.clone(),
            broll_draft: state.broll_draft.clone(),
            jobs,
            selected_job_id: state.selected_job_id.clone(),
            wallet_transfer: state.wallet_transfer.clone(),
            pending_wallet_transfer: state.pending_wallet_transfer.clone(),
        }
    }

    pub(crate) fn restore(self, state: &mut DesktopState) {
        state.reel_draft = self.reel_draft;
        state.broll_draft = self.broll_draft;
        state.jobs = self.jobs;
        state.selected_job_id = self
            .selected_job_id
            .filter(|id| state.jobs.iter().any(|job| &job.id == id));
        state.wallet_transfer = self.wallet_transfer;
        state.pending_wallet_transfer = self.pending_wallet_transfer;
    }
}

pub(crate) fn load() -> io::Result<Option<WorkspaceCache>> {
    let path = app_data_dir()?.join("workspace-v1.json");
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error),
    };
    let cache: WorkspaceCache = serde_json::from_slice(&bytes)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    if cache.version != CACHE_VERSION {
        return Ok(None);
    }
    Ok(Some(cache))
}

pub(crate) fn save(cache: &WorkspaceCache) -> io::Result<()> {
    let directory = app_data_dir()?;
    fs::create_dir_all(&directory)?;
    let path = directory.join("workspace-v1.json");
    let temporary = directory.join("workspace-v1.tmp");
    let bytes = serde_json::to_vec(cache).map_err(io::Error::other)?;
    fs::write(&temporary, bytes)?;
    fs::rename(temporary, path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pending_transfer_survives_snapshot_and_old_cache_defaults_empty() {
        let state = DesktopState {
            pending_wallet_transfer: Some(PendingWalletTransfer {
                version: 1,
                source_account_id: String::new(),
                source_kind: String::new(),
                source_label: String::new(),
                challenge_id: String::new(),
                challenge_expires_at: String::new(),
                recipient_handle: "bob".into(),
                amount_micros: 2_000_000,
                idempotency_key: "desktop-transfer-one".into(),
                submitted: true,
            }),
            ..DesktopState::default()
        };
        let cache = WorkspaceCache::snapshot(&state);
        let mut restored = DesktopState::default();
        cache.restore(&mut restored);
        assert_eq!(
            restored
                .pending_wallet_transfer
                .as_ref()
                .map(|pending| pending.idempotency_key.as_str()),
            Some("desktop-transfer-one")
        );

        let old = serde_json::json!({
            "version": 1,
            "reel_draft": ReelDraft::default(),
            "broll_draft": BrollDraft::default(),
            "jobs": [],
            "selected_job_id": null
        });
        let old: WorkspaceCache = serde_json::from_value(old).unwrap();
        assert!(old.wallet_transfer.is_none());
        assert!(old.pending_wallet_transfer.is_none());
    }

    #[test]
    fn legacy_pending_is_submitted_and_has_no_workspace_source() {
        let pending: PendingWalletTransfer = serde_json::from_value(serde_json::json!({
            "recipient_handle": "bob",
            "amount_micros": 2_000_000,
            "idempotency_key": "stable-old-key"
        }))
        .unwrap();
        assert_eq!(pending.version, 1);
        assert!(pending.submitted);
        assert!(pending.source_account_id.is_empty());
        assert!(pending.challenge_id.is_empty());
    }
}
