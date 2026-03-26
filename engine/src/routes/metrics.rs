use axum::{Json, extract::State};
use serde::Serialize;
use std::sync::Arc;

use crate::AppState;
use crate::core::types::ProtocolMetrics;

#[derive(Serialize)]
pub struct MetricsResponse {
    pub protocols: Vec<ProtocolMetrics>,
}

/// GET /metrics — return per-protocol metrics for comparison
pub async fn get_metrics(State(state): State<Arc<AppState>>) -> Json<MetricsResponse> {
    let protocols: Vec<ProtocolMetrics> = state
        .protocols
        .iter()
        .map(|(_, adapter)| adapter.metrics())
        .collect();

    Json(MetricsResponse { protocols })
}
