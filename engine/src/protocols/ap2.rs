use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::time::Instant;
use uuid::Uuid;

use super::{
    AuthToken, MetricsTracker, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult,
    SettlementResult,
};
use crate::config::Config;
use crate::core::error::{EngineError, Result};
use crate::core::types::{ActorWallet, Cents, ProtocolMetrics, SpendingConstraints};

#[derive(Debug, Clone)]
pub struct Ap2Adapter {
    metrics: MetricsTracker,
    http_client: reqwest::Client,
    service_url: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct Ap2AuthorizeRequest {
    actor_id: String,
    merchant: String,
    amount_usd: f64,
    memo: String,
    requires_confirmation: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Ap2AuthorizeResponse {
    _ok: bool,
    protocol: String,
    credential: String,
    actor_id: String,
    merchant: String,
    amount_usd: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Ap2HealthResponse {
    status: String,
    service: String,
    runtime_ready: bool,
    runtime_ready_reason: String,
}

#[derive(Debug, Clone)]
pub struct Ap2HealthStatus {
    pub runtime_ready: bool,
    pub reason: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct Ap2SettleRequest {
    merchant: String,
    amount_usd: f64,
    memo: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Ap2SettleResponse {
    _ok: bool,
    merchant: String,
    amount_usd: f64,
    payment_id: String,
    receipt: serde_json::Value,
}

impl Ap2Adapter {
    pub fn new(config: Config) -> Self {
        Self {
            metrics: MetricsTracker::new(),
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default(),
            service_url: config.ap2_service_url,
        }
    }

    pub async fn health_status(config: &Config) -> Ap2HealthStatus {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(5))
            .build()
            .unwrap_or_default();
        let response = match client
            .get(format!(
                "{}/health",
                config.ap2_service_url.trim_end_matches('/')
            ))
            .send()
            .await
        {
            Ok(response) => response,
            Err(error) => {
                return Ap2HealthStatus {
                    runtime_ready: false,
                    reason: format!("AP2 service unreachable: {}", error),
                };
            }
        };

        if !response.status().is_success() {
            return Ap2HealthStatus {
                runtime_ready: false,
                reason: format!("AP2 service health returned {}", response.status()),
            };
        }

        let body: Ap2HealthResponse = match response.json().await {
            Ok(body) => body,
            Err(error) => {
                return Ap2HealthStatus {
                    runtime_ready: false,
                    reason: format!("AP2 service health parse failed: {}", error),
                };
            }
        };

        let runtime_ready =
            body.status == "ok" && body.service == "meridian-ap2" && body.runtime_ready;
        Ap2HealthStatus {
            runtime_ready,
            reason: body.runtime_ready_reason,
        }
    }

    fn cents_to_usd(amount: Cents) -> f64 {
        amount as f64 / 100.0
    }
}

#[async_trait]
impl ProtocolAdapter for Ap2Adapter {
    fn name(&self) -> &str {
        "ap2"
    }

    async fn authorize(
        &self,
        wallet: &ActorWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        let merchant = constraints
            .merchants
            .as_ref()
            .and_then(|merchants| merchants.first())
            .cloned()
            .unwrap_or_else(|| "meridian-ap2-merchant".to_string());
        let memo = format!("meridian-ap2:{}:{}", wallet.owner_id, merchant);

        let started = Instant::now();
        let response = self
            .http_client
            .post(format!(
                "{}/ap2/authorize",
                self.service_url.trim_end_matches('/')
            ))
            .json(&Ap2AuthorizeRequest {
                actor_id: wallet.owner_id.clone(),
                merchant: merchant.clone(),
                amount_usd: Self::cents_to_usd(constraints.max_amount),
                memo: memo.clone(),
                requires_confirmation: constraints.requires_confirmation,
            })
            .send()
            .await
            .map_err(|e| {
                EngineError::ExternalService(format!("ap2 authorize request failed: {}", e))
            })?;

        let status = response.status();
        let bytes = response.bytes().await.unwrap_or_default();
        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "ap2 authorize returned {}: {}",
                status,
                String::from_utf8_lossy(&bytes)
            )));
        }

        let body: Ap2AuthorizeResponse = serde_json::from_slice(&bytes).map_err(|e| {
            EngineError::ExternalService(format!("ap2 authorize parse failed: {}", e))
        })?;
        self.metrics
            .record_auth(started.elapsed().as_micros().min(u64::MAX as u128) as u64);

        Ok(AuthToken {
            token_id: format!("ap2_auth_{}", Uuid::new_v4().simple()),
            protocol: body.protocol,
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "actor_id": body.actor_id,
                "merchant": body.merchant,
                "amount_usd": body.amount_usd,
                "memo": memo,
                "credential": body.credential,
            }),
        })
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let credential = token
            .protocol_data
            .get("credential")
            .and_then(|value| value.as_str())
            .ok_or_else(|| {
                EngineError::ProtocolError("ap2 auth token missing credential".into())
            })?;
        let memo = token
            .protocol_data
            .get("memo")
            .and_then(|value| value.as_str())
            .unwrap_or("meridian-ap2");

        let started = Instant::now();
        let response = self
            .http_client
            .post(format!(
                "{}/ap2/settle",
                self.service_url.trim_end_matches('/')
            ))
            .header("x-ap2-credential", credential)
            .json(&Ap2SettleRequest {
                merchant: merchant.to_string(),
                amount_usd: Self::cents_to_usd(amount),
                memo: memo.to_string(),
            })
            .send()
            .await
            .map_err(|e| {
                EngineError::ExternalService(format!("ap2 settle request failed: {}", e))
            })?;

        let status = response.status();
        let bytes = response.bytes().await.unwrap_or_default();
        if !status.is_success() {
            let exec_us = started.elapsed().as_micros().min(u64::MAX as u128) as u64;
            self.metrics.record_failure(exec_us);
            return Err(EngineError::ExternalService(format!(
                "ap2 settle returned {}: {}",
                status,
                String::from_utf8_lossy(&bytes)
            )));
        }

        let body: Ap2SettleResponse = serde_json::from_slice(&bytes)
            .map_err(|e| EngineError::ExternalService(format!("ap2 settle parse failed: {}", e)))?;

        let exec_us = started.elapsed().as_micros().min(u64::MAX as u128) as u64;
        let fee = self.fee_for(amount);
        self.metrics.record_success(amount, fee, exec_us, false);

        Ok(PaymentResult {
            payment_id: body.payment_id.clone(),
            protocol: "ap2".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Settled,
            execution_us: exec_us,
            fee,
            protocol_data: serde_json::json!({
                "merchant": body.merchant,
                "amount_usd": body.amount_usd,
                "receipt": body.receipt,
                "payment_id": body.payment_id,
            }),
        })
    }

    async fn settle(&self, payment: &PaymentResult) -> Result<SettlementResult> {
        Ok(SettlementResult {
            payment_id: payment.payment_id.clone(),
            settled: payment.status == PaymentStatus::Settled,
            execution_us: payment.execution_us,
            final_amount: payment.amount,
            fee: payment.fee,
        })
    }

    async fn refund(&self, _payment: &PaymentResult, _reason: &str) -> Result<RefundResult> {
        Err(EngineError::ProtocolError(
            "ap2 refunds are not implemented yet".into(),
        ))
    }

    fn metrics(&self) -> ProtocolMetrics {
        self.metrics.to_metrics("ap2")
    }

    fn fee_for(&self, amount: Cents) -> Cents {
        (amount * 25 / 1000) + 20
    }

    fn supports_micropayments(&self) -> bool {
        false
    }

    fn autonomy_level(&self) -> f64 {
        0.5
    }
}
