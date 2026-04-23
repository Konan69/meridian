use axum::{Json, extract::State};
use serde::Serialize;
use std::sync::Arc;

use crate::AppState;
use crate::core::types::ProtocolCapability;
use crate::protocols::{ap2, atxp, mpp};

#[derive(Serialize)]
pub struct CapabilitiesResponse {
    pub supported_protocols: Vec<String>,
    pub protocol_statuses: Vec<ProtocolCapability>,
}

fn refreshed_integration(state: &AppState, cached: &ProtocolCapability) -> String {
    if state.protocols.contains_key(&cached.protocol) {
        "in_engine".into()
    } else {
        cached.integration.clone()
    }
}

pub async fn get_capabilities(State(state): State<Arc<AppState>>) -> Json<CapabilitiesResponse> {
    let (atxp_health, mpp_health, ap2_health) = tokio::join!(
        atxp::AtxpAdapter::health_status(&state.config),
        mpp::MppAdapter::health_status(&state.config),
        ap2::Ap2Adapter::health_status(&state.config),
    );

    let mut protocol_statuses = state
        .protocol_capabilities
        .iter()
        .map(|cached| match cached.protocol.as_str() {
            "atxp" => ProtocolCapability {
                protocol: cached.protocol.clone(),
                runtime_ready: atxp_health.runtime_ready,
                integration: refreshed_integration(&state, cached),
                reason: atxp_health.reason.clone(),
            },
            "mpp" => ProtocolCapability {
                protocol: cached.protocol.clone(),
                runtime_ready: mpp_health.runtime_ready,
                integration: refreshed_integration(&state, cached),
                reason: mpp_health.reason.clone(),
            },
            "ap2" => ProtocolCapability {
                protocol: cached.protocol.clone(),
                runtime_ready: ap2_health.runtime_ready,
                integration: refreshed_integration(&state, cached),
                reason: ap2_health.reason.clone(),
            },
            _ => cached.clone(),
        })
        .collect::<Vec<_>>();

    protocol_statuses.sort_by(|a, b| a.protocol.cmp(&b.protocol));

    let mut supported_protocols = protocol_statuses
        .iter()
        .filter(|status| status.runtime_ready && status.integration == "in_engine")
        .map(|status| status.protocol.clone())
        .collect::<Vec<_>>();
    supported_protocols.sort();

    Json(CapabilitiesResponse {
        supported_protocols,
        protocol_statuses,
    })
}
