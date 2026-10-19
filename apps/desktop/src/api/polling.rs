//! Poll timing shared by the background generation worker.

use std::time::Duration;

pub(crate) const POLL_INTERVAL: Duration = Duration::from_secs(3);
