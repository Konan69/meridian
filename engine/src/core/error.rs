use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use serde::Serialize;

#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error("not found: {0}")]
    NotFound(String),

    #[error("invalid request: {0}")]
    InvalidRequest(String),

    #[error("session not modifiable: {0}")]
    SessionTerminal(String),

    #[error("payment declined: {0}")]
    PaymentDeclined(String),

    #[error("vault token invalid: {0}")]
    VaultTokenInvalid(String),

    #[error("idempotency conflict")]
    IdempotencyConflict,

    #[error("protocol error: {0}")]
    ProtocolError(String),

    #[error("external service error: {0}")]
    ExternalService(String),

    #[error("invalid address: {0}")]
    InvalidAddress(String),

    #[error("internal: {0}")]
    Internal(String),

    #[error("database: {0}")]
    Database(#[from] rusqlite::Error),
}

#[derive(Serialize)]
struct ErrorBody {
    #[serde(rename = "type")]
    error_type: String,
    code: String,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    param: Option<String>,
}

impl IntoResponse for EngineError {
    fn into_response(self) -> Response {
        let (status, error_type, code) = match &self {
            EngineError::NotFound(_) => (StatusCode::NOT_FOUND, "not_found", "not_found"),
            EngineError::InvalidRequest(_) => (
                StatusCode::BAD_REQUEST,
                "invalid_request",
                "invalid_request",
            ),
            EngineError::SessionTerminal(_) => (
                StatusCode::METHOD_NOT_ALLOWED,
                "invalid_request",
                "session_not_modifiable",
            ),
            EngineError::PaymentDeclined(_) => (
                StatusCode::BAD_REQUEST,
                "invalid_request",
                "payment_declined",
            ),
            EngineError::VaultTokenInvalid(_) => (
                StatusCode::BAD_REQUEST,
                "invalid_request",
                "invalid_vault_token",
            ),
            EngineError::IdempotencyConflict => (
                StatusCode::CONFLICT,
                "idempotency_conflict",
                "idempotency_conflict",
            ),
            EngineError::ProtocolError(_) => {
                (StatusCode::BAD_REQUEST, "protocol_error", "protocol_error")
            }
            EngineError::Internal(_) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "processing_error",
                "internal_error",
            ),
            EngineError::Database(_) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                "processing_error",
                "database_error",
            ),
            EngineError::ExternalService(_) => (
                StatusCode::BAD_GATEWAY,
                "external_service_error",
                "external_service_error",
            ),
            EngineError::InvalidAddress(_) => (
                StatusCode::BAD_REQUEST,
                "invalid_address",
                "invalid_address",
            ),
        };

        let body = ErrorBody {
            error_type: error_type.into(),
            code: code.into(),
            message: self.to_string(),
            param: None,
        };

        (status, axum::Json(body)).into_response()
    }
}

pub type Result<T> = std::result::Result<T, EngineError>;
