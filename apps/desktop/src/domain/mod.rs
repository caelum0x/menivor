//! API-independent ReelForge desktop domain values.

mod broll;
mod job;
mod library;
mod reel;
pub(crate) mod sidecar;

pub(crate) use broll::{BrollDraft, BrollMode};
pub(crate) use job::{JobKind, JobState};
pub(crate) use library::JobSnapshot;
pub(crate) use reel::ReelDraft;
pub(crate) use sidecar::{LocalSidecar, SidecarStatus};
