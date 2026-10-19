//! On-device MCP protocol (`rf-devproto`, the `devd` daemon wire format). A tiny
//! JSON-RPC-style request/response envelope an AI agent uses to drive the desktop
//! app locally (start a render, list projects, run a clipfarm batch). Serde types
//! + a pure dispatch-name validator; the handler wiring lives in the runtime.

use serde::{Deserialize, Serialize};

pub const PROTOCOL_VERSION: &str = "devd/1";

/// Methods the on-device agent may invoke (allowlist — anything else is rejected).
pub const ALLOWED_METHODS: &[&str] = &[
    "render.start",
    "render.status",
    "project.list",
    "project.open",
    "clipfarm.run",
    "capture.start",
    "capture.stop",
];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Request {
    pub id: u64,
    pub method: String,
    #[serde(default)]
    pub params: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Response {
    pub id: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<ProtoError>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProtoError {
    pub code: i32,
    pub message: String,
}

// Standard JSON-RPC 2.0 error codes, plus one app-specific code for the version
// handshake. Standard wire codes let generic JSON-RPC clients map them.
pub const ERR_PARSE: i32 = -32700;
pub const ERR_INVALID_REQUEST: i32 = -32600;
pub const ERR_UNKNOWN_METHOD: i32 = -32601;
pub const ERR_UNSUPPORTED_VERSION: i32 = -32001;

impl Response {
    pub fn ok(id: u64, result: serde_json::Value) -> Self {
        Response {
            id,
            result: Some(result),
            error: None,
        }
    }
    pub fn err(id: u64, code: i32, message: impl Into<String>) -> Self {
        Response {
            id,
            result: None,
            error: Some(ProtoError {
                code,
                message: message.into(),
            }),
        }
    }
}

/// True when `method` is on the allowlist (the dispatcher's gate).
pub fn is_allowed(method: &str) -> bool {
    ALLOWED_METHODS.contains(&method)
}

/// Parse a raw JSON frame into a [`Request`], returning a ready-to-serialize
/// error [`Response`] on failure (never a panic). Distinguishes a JSON syntax
/// error (`ERR_PARSE`, id 0 — the id can't be recovered) from well-formed JSON
/// that isn't a valid request shape (`ERR_INVALID_REQUEST`, with the id recovered
/// when present so the error correlates to the caller's frame).
pub fn parse_request(raw: &str) -> Result<Request, Response> {
    let value: serde_json::Value = serde_json::from_str(raw)
        .map_err(|e| Response::err(0, ERR_PARSE, format!("parse error: {e}")))?;
    let id = value.get("id").and_then(|v| v.as_u64()).unwrap_or(0);
    serde_json::from_value::<Request>(value)
        .map_err(|e| Response::err(id, ERR_INVALID_REQUEST, format!("invalid request: {e}")))
}

/// Handshake gate: reject a client whose advertised protocol version doesn't
/// match this daemon's [`PROTOCOL_VERSION`], before any method dispatch.
pub fn check_version(client_version: &str, request_id: u64) -> Result<(), Response> {
    if client_version == PROTOCOL_VERSION {
        Ok(())
    } else {
        Err(Response::err(
            request_id,
            ERR_UNSUPPORTED_VERSION,
            format!(
                "unsupported protocol {client_version:?}; this daemon speaks {PROTOCOL_VERSION:?}"
            ),
        ))
    }
}

/// Parse a request and reject a method not on the allowlist (returns an error
/// response ready to serialize). The actual handler dispatch is the runtime's job.
pub fn validate(req: &Request) -> Result<(), Response> {
    if is_allowed(&req.method) {
        Ok(())
    } else {
        Err(Response::err(
            req.id,
            ERR_UNKNOWN_METHOD,
            format!("unknown method: {}", req.method),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_roundtrips() {
        let req = Request {
            id: 1,
            method: "render.start".into(),
            params: serde_json::json!({"prompt": "x"}),
        };
        let json = serde_json::to_string(&req).unwrap();
        let back: Request = serde_json::from_str(&json).unwrap();
        assert_eq!(req, back);
    }

    #[test]
    fn allowlist_gates_methods() {
        assert!(is_allowed("render.start"));
        assert!(!is_allowed("system.exec")); // not allowed
    }

    #[test]
    fn validate_rejects_unknown_method() {
        let req = Request {
            id: 7,
            method: "danger.do".into(),
            params: serde_json::Value::Null,
        };
        let err = validate(&req).unwrap_err();
        assert_eq!(err.id, 7);
        assert_eq!(err.error.unwrap().code, ERR_UNKNOWN_METHOD);
    }

    #[test]
    fn ok_response_serializes_without_error_field() {
        let resp = Response::ok(1, serde_json::json!({"state": "IN_QUEUE"}));
        let json = serde_json::to_string(&resp).unwrap();
        assert!(!json.contains("error"));
        assert!(json.contains("result"));
    }

    #[test]
    fn parse_request_accepts_a_valid_frame() {
        let req = parse_request(r#"{"id": 9, "method": "project.list"}"#).unwrap();
        assert_eq!(req.id, 9);
        assert_eq!(req.method, "project.list");
    }

    #[test]
    fn parse_request_reports_syntax_errors_as_parse_error() {
        // Malformed JSON — id can't be recovered, so it defaults to 0.
        let resp = parse_request("{not json").unwrap_err();
        assert_eq!(resp.id, 0);
        assert_eq!(resp.error.unwrap().code, ERR_PARSE);
    }

    #[test]
    fn parse_request_reports_bad_shape_as_invalid_request_and_recovers_id() {
        // Valid JSON, but `method` is missing -> invalid request, id recovered.
        let resp = parse_request(r#"{"id": 42, "params": {}}"#).unwrap_err();
        assert_eq!(resp.id, 42);
        assert_eq!(resp.error.unwrap().code, ERR_INVALID_REQUEST);
    }

    #[test]
    fn check_version_gates_the_handshake() {
        assert!(check_version(PROTOCOL_VERSION, 1).is_ok());
        let resp = check_version("devd/0", 3).unwrap_err();
        assert_eq!(resp.id, 3);
        assert_eq!(resp.error.unwrap().code, ERR_UNSUPPORTED_VERSION);
    }
}
