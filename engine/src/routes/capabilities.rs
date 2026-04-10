use axum::{Json, extract::State};
use serde::Serialize;
use std::sync::Arc;

use crate::AppState;
use crate::core::types::ProtocolCapability;

#[derive(Serialize)]
pub struct CapabilitiesResponse {
    pub supported_protocols: Vec<String>,
    pub protocol_statuses: Vec<ProtocolCapability>,
}

pub async fn get_capabilities(State(state): State<Arc<AppState>>) -> Json<CapabilitiesResponse> {
    let mut supported_protocols: Vec<String> = state.protocols.keys().cloned().collect();
    supported_protocols.sort();
    let mut protocol_statuses = state.protocol_capabilities.clone();
    protocol_statuses.sort_by(|a, b| a.protocol.cmp(&b.protocol));
    Json(CapabilitiesResponse {
        supported_protocols,
        protocol_statuses,
    })
}
