//! Product events intentionally exclude API keys, prompts, and signed URLs.

use crate::domain::JobKind;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum ClientEvent {
    GenerationSubmitted {
        kind: JobKind,
        correlation_id: String,
    },
    GenerationTerminal {
        kind: JobKind,
        correlation_id: String,
        succeeded: bool,
    },
    ClientFailure {
        operation: String,
        correlation_id: String,
    },
}
