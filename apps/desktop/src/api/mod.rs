//! Typed transport for ReelForge's canonical `/api/v1` contract.

mod auth;
mod broll;
mod catalog;
mod client;
mod editor;
mod errors;
mod media;
mod models;
mod polling;
mod reels;
mod uploads;
mod wallet;

pub(crate) use catalog::CatalogEntry;
pub(crate) use client::ApiClient;
pub(crate) use errors::{ApiFailure, ApiFailureKind};
pub(crate) use models::{BrollGenerationDto, JobDto, TimelineExportJobDto};
pub(crate) use polling::POLL_INTERVAL;
// Media-gateway DTOs (re-exported from the shared `rf-gateway` domain crate).
#[allow(unused_imports)]
pub(crate) use rf_gateway::{
    Credits, GenerationDetail, GenerationPage, ImageResult, MediaIdentityOption, MediaModel,
    MediaProvenanceExport, UsageRow, VideoJob, WalletReceiveAddress, WalletRecipient,
    WalletSavedRecipient, WalletSource, WalletTransferChallenge, WalletTransferResult,
};
