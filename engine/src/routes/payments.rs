use axum::{Json, extract::State};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::AppState;
use crate::core::error::{EngineError, Result};
use crate::core::types::{SpendingConstraints, TransactionRecord};

#[derive(Debug, Deserialize)]
pub struct ExecutePaymentRequest {
    pub actor_id: String,
    pub protocol: String,
    pub amount_cents: u64,
    pub merchant: String,
    pub currency: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ExecutePaymentResponse {
    pub payment_id: String,
    pub protocol: String,
    pub amount_cents: u64,
    pub fee_cents: u64,
    pub execution_us: u64,
    pub status: String,
    pub merchant: String,
}

pub async fn execute_payment(
    State(state): State<Arc<AppState>>,
    Json(req): Json<ExecutePaymentRequest>,
) -> Result<Json<ExecutePaymentResponse>> {
    let adapter = state
        .protocols
        .get(&req.protocol)
        .ok_or_else(|| EngineError::ProtocolError(format!("unknown protocol: {}", req.protocol)))?;

    let wallet = state
        .wallet_service
        .to_actor_wallet("agent", &req.actor_id, &req.protocol)
        .map_err(|e| EngineError::PaymentDeclined(format!("wallet error: {}", e)))?;

    let constraints = SpendingConstraints {
        max_amount: req.amount_cents,
        currency: req.currency.clone().unwrap_or_else(|| "usd".to_string()),
        merchants: Some(vec![req.merchant.clone()]),
        categories: None,
        expires_at: chrono::Utc::now() + chrono::Duration::hours(1),
        requires_confirmation: false,
    };

    let auth_token = adapter.authorize(&wallet, &constraints).await?;
    let settlement_target = auth_token
        .protocol_data
        .get("pay_to")
        .and_then(|value| value.as_str())
        .unwrap_or(&req.merchant)
        .to_string();

    let payment = adapter
        .pay(&auth_token, req.amount_cents, &settlement_target)
        .await?;

    {
        let store = state.store.lock().unwrap();
        let tx_record = TransactionRecord {
            id: payment.payment_id.clone(),
            session_id: format!("direct_{}", uuid::Uuid::new_v4().simple()),
            protocol: payment.protocol.clone(),
            agent_id: req.actor_id.clone(),
            amount: payment.amount,
            fee: payment.fee,
            execution_us: payment.execution_us,
            status: format!("{:?}", payment.status),
            created_at: chrono::Utc::now(),
        };
        let _ = store.save_transaction(&tx_record);
    }

    Ok(Json(ExecutePaymentResponse {
        payment_id: payment.payment_id,
        protocol: payment.protocol,
        amount_cents: payment.amount,
        fee_cents: payment.fee,
        execution_us: payment.execution_us,
        status: format!("{:?}", payment.status),
        merchant: req.merchant,
    }))
}
