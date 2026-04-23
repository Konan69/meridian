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
pub struct MppAdapter {
    metrics: MetricsTracker,
    http_client: reqwest::Client,
    service_url: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MppHealthResponse {
    status: String,
    service: String,
    supports_engine_runtime: bool,
    runtime_ready_reason: String,
}

#[derive(Debug, Clone)]
pub struct MppHealthStatus {
    pub runtime_ready: bool,
    pub reason: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct MppAuthorizeRequest {
    actor_id: String,
    merchant: String,
    amount_usd: f64,
    memo: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MppAuthorizeResponse {
    _ok: bool,
    actor_id: String,
    merchant: String,
    amount_usd: f64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct MppExecuteRequest {
    actor_id: String,
    merchant: String,
    amount_usd: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct MppExecuteResponse {
    _ok: bool,
    actor_id: String,
    merchant: String,
    amount_usd: f64,
    payment_id: String,
    receipt: serde_json::Value,
}

impl MppAdapter {
    pub fn new(config: Config) -> Self {
        Self {
            metrics: MetricsTracker::new(),
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(45))
                .build()
                .unwrap_or_default(),
            service_url: config.stripe_service_url,
        }
    }

    pub async fn health_status(config: &Config) -> MppHealthStatus {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(5))
            .build()
            .unwrap_or_default();
        let response = match client
            .get(format!(
                "{}/health",
                config.stripe_service_url.trim_end_matches('/')
            ))
            .send()
            .await
        {
            Ok(response) => response,
            Err(error) => {
                return MppHealthStatus {
                    runtime_ready: false,
                    reason: format!("MPP service unreachable: {}", error),
                };
            }
        };

        if !response.status().is_success() {
            return MppHealthStatus {
                runtime_ready: false,
                reason: format!("MPP service health returned {}", response.status()),
            };
        }

        let body: MppHealthResponse = match response.json().await {
            Ok(body) => body,
            Err(error) => {
                return MppHealthStatus {
                    runtime_ready: false,
                    reason: format!("MPP service health parse failed: {}", error),
                };
            }
        };

        MppHealthStatus {
            runtime_ready: body.status == "ok"
                && body.service == "meridian-stripe"
                && body.supports_engine_runtime,
            reason: body.runtime_ready_reason,
        }
    }

    fn cents_to_usd(amount: Cents) -> f64 {
        amount as f64 / 100.0
    }
}

#[async_trait]
impl ProtocolAdapter for MppAdapter {
    fn name(&self) -> &str {
        "mpp"
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
            .unwrap_or_else(|| "meridian-mpp-merchant".to_string());
        let memo = format!("meridian-mpp:{}:{}", wallet.owner_id, merchant);

        let started = Instant::now();
        let response = self
            .http_client
            .post(format!(
                "{}/mpp/authorize",
                self.service_url.trim_end_matches('/')
            ))
            .json(&MppAuthorizeRequest {
                actor_id: wallet.owner_id.clone(),
                merchant: merchant.clone(),
                amount_usd: Self::cents_to_usd(constraints.max_amount),
                memo: memo.clone(),
            })
            .send()
            .await
            .map_err(|e| {
                EngineError::ExternalService(format!("mpp authorize request failed: {}", e))
            })?;

        let status = response.status();
        let bytes = response.bytes().await.unwrap_or_default();
        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "mpp authorize returned {}: {}",
                status,
                String::from_utf8_lossy(&bytes)
            )));
        }

        let body: MppAuthorizeResponse = serde_json::from_slice(&bytes).map_err(|e| {
            EngineError::ExternalService(format!("mpp authorize parse failed: {}", e))
        })?;
        self.metrics
            .record_auth(started.elapsed().as_micros() as u64);

        Ok(AuthToken {
            token_id: format!("mpp_auth_{}", Uuid::new_v4().simple()),
            protocol: "mpp".into(),
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "actor_id": body.actor_id,
                "merchant": body.merchant,
                "amount_usd": body.amount_usd,
                "memo": memo,
            }),
        })
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let actor_id = token
            .protocol_data
            .get("actor_id")
            .and_then(|value| value.as_str())
            .ok_or_else(|| EngineError::ProtocolError("mpp auth token missing actor_id".into()))?;

        let started = Instant::now();
        let response = self
            .http_client
            .post(format!(
                "{}/mpp/execute",
                self.service_url.trim_end_matches('/')
            ))
            .json(&MppExecuteRequest {
                actor_id: actor_id.to_string(),
                merchant: merchant.to_string(),
                amount_usd: Self::cents_to_usd(amount),
            })
            .send()
            .await
            .map_err(|e| {
                EngineError::ExternalService(format!("mpp execute request failed: {}", e))
            })?;

        let status = response.status();
        let bytes = response.bytes().await.unwrap_or_default();
        if !status.is_success() {
            let exec_us = started.elapsed().as_micros() as u64;
            self.metrics.record_failure(exec_us);
            return Err(EngineError::ExternalService(format!(
                "mpp execute returned {}: {}",
                status,
                String::from_utf8_lossy(&bytes)
            )));
        }

        let body: MppExecuteResponse = serde_json::from_slice(&bytes).map_err(|e| {
            EngineError::ExternalService(format!("mpp execute parse failed: {}", e))
        })?;
        let exec_us = started.elapsed().as_micros() as u64;
        let fee = self.fee_for(amount);
        self.metrics
            .record_success(amount, fee, exec_us, amount < 100);

        Ok(PaymentResult {
            payment_id: body.payment_id.clone(),
            protocol: "mpp".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Settled,
            execution_us: exec_us,
            fee,
            protocol_data: serde_json::json!({
                "merchant": body.merchant,
                "amount_usd": body.amount_usd,
                "receipt": body.receipt,
                "actor_id": body.actor_id,
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
            "mpp refunds are not implemented yet".into(),
        ))
    }

    fn metrics(&self) -> ProtocolMetrics {
        self.metrics.to_metrics("mpp")
    }

    fn fee_for(&self, amount: Cents) -> Cents {
        std::cmp::max((amount * 15 / 1000) + 5, 1)
    }

    fn supports_micropayments(&self) -> bool {
        true
    }

    fn autonomy_level(&self) -> f64 {
        0.8
    }
}
