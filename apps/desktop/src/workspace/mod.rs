//! Background commands and UI-owned workspace state.

mod commands;
mod editor_handoff;
pub(crate) mod editor_project;
mod local_executor;
mod local_runtime;
mod persistence;
mod reducer;
mod source_analysis;
mod worker;

pub(crate) use crate::config::{ConnectionState, GenerationCapabilities};
pub(crate) use crate::domain::{BrollDraft, BrollMode, JobKind, JobSnapshot, JobState, ReelDraft};
pub(crate) use commands::{UploadTarget, WorkerCommand, WorkerUpdate};
pub(crate) use local_executor::LocalRenderRequest;
pub(crate) use persistence::WorkspaceCache;
pub(crate) use reducer::{DesktopState, PendingWalletTransfer};
pub(crate) use source_analysis::EditorSourceAnalysis;
pub(crate) use worker::start_worker;
