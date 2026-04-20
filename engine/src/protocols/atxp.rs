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
pub struct AtxpAdapter {
    metrics: MetricsTracker,
    http_client: reqwest::Client,
    service_url: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AtxpAuthorizeRequest {
    actor_id: String,
    merchant: String,
    amount_usd: f64,
    memo: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AtxpAuthorizeResponse {
    ok: bool,
    protocol: String,
    credential: String,
    actor_id: String,
    merchant: String,
    amount_usd: f64,
    destination: String,
    shared_account: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AtxpHealthResponse {
    status: String,
    service: String,
    payer_mode: Option<String>,
    runtime_ready: Option<bool>,
    runtime_mode: Option<String>,
    supports_direct_settle: Option<bool>,
    runtime_ready_reason: Option<String>,
}

#[derive(Debug, Clone)]
pub struct AtxpHealthStatus {
    pub runtime_ready: bool,
    pub runtime_mode: String,
    pub reason: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AtxpExecuteRequest {
    actor_id: String,
    merchant: String,
    amount_usd: f64,
    memo: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AtxpExecuteResponse {
    ok: bool,
    protocol: String,
    payer_mode: String,
    merchant: String,
    amount_usd: f64,
    payment_events: Vec<serde_json::Value>,
    result: serde_json::Value,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AtxpDirectTransferRequest {
    merchant: String,
    amount_usd: f64,
    memo: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AtxpDirectTransferResponse {
    ok: bool,
    merchant: String,
    amount_usd: f64,
    tx_hash: String,
    settled_amount: serde_json::Value,
}

impl AtxpAdapter {
    pub fn new(config: Config) -> Self {
        Self {
            metrics: MetricsTracker::new(),
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(45))
                .build()
                .unwrap_or_default(),
            service_url: config.atxp_service_url,
        }
    }

    pub async fn health_status(config: &Config) -> AtxpHealthStatus {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(5))
            .build()
            .unwrap_or_default();
        let response = match client
            .get(format!("{}/health", config.atxp_service_url.trim_end_matches('/')))
            .send()
            .await
        {
            Ok(response) => response,
            Err(error) => {
                return AtxpHealthStatus {
                    runtime_ready: false,
                    runtime_mode: "unsupported".into(),
                    reason: format!("ATXP service unreachable: {}", error),
                }
            }
        };

        if !response.status().is_success() {
            return AtxpHealthStatus {
                runtime_ready: false,
                runtime_mode: "unsupported".into(),
                reason: format!("ATXP service health returned {}", response.status()),
            };
        }

        let body: AtxpHealthResponse = match response.json().await {
            Ok(body) => body,
            Err(error) => {
                return AtxpHealthStatus {
                    runtime_ready: false,
                    runtime_mode: "unsupported".into(),
                    reason: format!("ATXP service health parse failed: {}", error),
                }
            }
        };

        let runtime_ready = body.status == "ok"
            && body.service == "meridian-atxp"
            && body
                .runtime_ready
                .unwrap_or(body.supports_direct_settle.unwrap_or(false));
        let payer_mode = body.payer_mode.unwrap_or_else(|| "unknown".into());
        let runtime_mode = body.runtime_mode.unwrap_or_else(|| {
            if body.supports_direct_settle.unwrap_or(false) {
                "direct_settle".into()
            } else {
                "unsupported".into()
            }
        });
        let reason = body.runtime_ready_reason.unwrap_or_else(|| {
            if runtime_ready {
                format!(
                    "ATXP runtime mode '{}' ready via payer mode '{}'",
                    runtime_mode, payer_mode
                )
            } else {
                format!(
                    "ATXP service healthy but payer mode '{}' is not runtime-ready",
                    payer_mode
                )
            }
        });

        AtxpHealthStatus {
            runtime_ready,
            runtime_mode,
            reason,
        }
    }

    fn cents_to_usd(amount: Cents) -> f64 {
        amount as f64 / 100.0
    }

    async fn authorize_request(&self, body: &AtxpAuthorizeRequest) -> Result<AtxpAuthorizeResponse> {
        let response = self
            .http_client
            .post(format!(
                "{}/atxp/authorize",
                self.service_url.trim_end_matches('/')
            ))
            .json(body)
            .send()
            .await
            .map_err(|e| EngineError::ExternalService(format!("atxp authorize request failed: {}", e)))?;

        let status = response.status();
        let bytes = response.bytes().await.unwrap_or_default();
        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "atxp authorize returned {}: {}",
                status,
                String::from_utf8_lossy(&bytes)
            )));
        }

        serde_json::from_slice(&bytes).map_err(|e| {
            EngineError::ExternalService(format!("atxp authorize parse failed: {}", e))
        })
    }
}

#[async_trait]
impl ProtocolAdapter for AtxpAdapter {
    fn name(&self) -> &str {
        "atxp"
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
            .unwrap_or_else(|| "meridian-atxp-merchant".to_string());
        let memo = format!("meridian-atxp:{}:{}", wallet.owner_id, merchant);
        let health = Self::health_status(&Config {
            atxp_service_url: self.service_url.clone(),
            ..Config::default()
        })
        .await;

        if !health.runtime_ready {
            return Err(EngineError::ProtocolError(format!(
                "atxp runtime is not ready: {}",
                health.reason
            )));
        }

        if health.runtime_mode == "mcp_execute" {
            return Ok(AuthToken {
                token_id: format!("atxp_auth_{}", Uuid::new_v4().simple()),
                protocol: "atxp".into(),
                max_amount: constraints.max_amount,
                currency: constraints.currency.clone(),
                expires_at: constraints.expires_at,
                protocol_data: serde_json::json!({
                    "actor_id": wallet.owner_id,
                    "merchant": merchant,
                    "amount_usd": Self::cents_to_usd(constraints.max_amount),
                    "memo": memo,
                    "runtime_mode": "mcp_execute",
                }),
            });
        }

        let started = Instant::now();
        let response = self
            .authorize_request(&AtxpAuthorizeRequest {
                actor_id: wallet.owner_id.clone(),
                merchant: merchant.clone(),
                amount_usd: Self::cents_to_usd(constraints.max_amount),
                memo: memo.clone(),
            })
            .await?;
        self.metrics
            .record_auth(started.elapsed().as_micros().min(u64::MAX as u128) as u64);

        if !response.ok {
            return Err(EngineError::ProtocolError(
                "atxp authorize returned ok=false".into(),
            ));
        }

        Ok(AuthToken {
            token_id: format!("atxp_auth_{}", Uuid::new_v4().simple()),
            protocol: response.protocol,
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "actor_id": response.actor_id,
                "merchant": response.merchant,
                "amount_usd": response.amount_usd,
                "memo": memo,
                "credential": response.credential,
                "destination": response.destination,
                "shared_account": response.shared_account,
                "runtime_mode": "direct_settle",
            }),
        })
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let runtime_mode = token
            .protocol_data
            .get("runtime_mode")
            .and_then(|value| value.as_str())
            .unwrap_or("direct_settle");

        if runtime_mode == "mcp_execute" {
            let actor_id = token
                .protocol_data
                .get("actor_id")
                .and_then(|value| value.as_str())
                .ok_or_else(|| EngineError::ProtocolError("atxp auth token missing actor_id".into()))?;
            let memo = token
                .protocol_data
                .get("memo")
                .and_then(|value| value.as_str())
                .unwrap_or("meridian-atxp");

            let started = Instant::now();
            let response = self
                .http_client
                .post(format!(
                    "{}/atxp/execute",
                    self.service_url.trim_end_matches('/')
                ))
                .json(&AtxpExecuteRequest {
                    actor_id: actor_id.to_string(),
                    merchant: merchant.to_string(),
                    amount_usd: Self::cents_to_usd(amount),
                    memo: memo.to_string(),
                })
                .send()
                .await
                .map_err(|e| EngineError::ExternalService(format!("atxp execute request failed: {}", e)))?;

            let status = response.status();
            let bytes = response.bytes().await.unwrap_or_default();
            if !status.is_success() {
                let exec_us = started.elapsed().as_micros().min(u64::MAX as u128) as u64;
                self.metrics.record_failure(exec_us);
                return Err(EngineError::ExternalService(format!(
                    "atxp execute returned {}: {}",
                    status,
                    String::from_utf8_lossy(&bytes)
                )));
            }

            let body: AtxpExecuteResponse = serde_json::from_slice(&bytes)
                .map_err(|e| EngineError::ExternalService(format!("atxp execute parse failed: {}", e)))?;
            let exec_us = started.elapsed().as_micros().min(u64::MAX as u128) as u64;

            if !body.ok {
                self.metrics.record_failure(exec_us);
                return Err(EngineError::ProtocolError(
                    "atxp execute returned ok=false".into(),
                ));
            }

            let fee = self.fee_for(amount);
            self.metrics
                .record_success(amount, fee, exec_us, self.supports_micropayments() && amount < 100);

            let payment_id = body
                .payment_events
                .first()
                .and_then(|value| value.get("transactionHash"))
                .and_then(|value| value.as_str())
                .unwrap_or("atxp_mcp_execute");

            return Ok(PaymentResult {
                payment_id: payment_id.to_string(),
                protocol: body.protocol,
                amount,
                currency: token.currency.clone(),
                status: PaymentStatus::Settled,
                execution_us: exec_us,
                fee,
                protocol_data: serde_json::json!({
                    "merchant": body.merchant,
                    "amount_usd": body.amount_usd,
                    "payer_mode": body.payer_mode,
                    "payment_events": body.payment_events,
                    "result": body.result,
                    "runtime_mode": "mcp_execute",
                }),
            });
        }

        let credential = token
            .protocol_data
            .get("credential")
            .and_then(|value| value.as_str())
            .ok_or_else(|| EngineError::ProtocolError("atxp auth token missing credential".into()))?;
        let memo = token
            .protocol_data
            .get("memo")
            .and_then(|value| value.as_str())
            .unwrap_or("meridian-atxp");

        let started = Instant::now();
        let response = self
            .http_client
            .post(format!(
                "{}/atxp/direct-transfer",
                self.service_url.trim_end_matches('/')
            ))
            .header("x-atxp-payment", credential)
            .json(&AtxpDirectTransferRequest {
                merchant: merchant.to_string(),
                amount_usd: Self::cents_to_usd(amount),
                memo: memo.to_string(),
            })
            .send()
            .await
            .map_err(|e| EngineError::ExternalService(format!("atxp direct-transfer request failed: {}", e)))?;

        let status = response.status();
        let bytes = response.bytes().await.unwrap_or_default();
        if !status.is_success() {
            let exec_us = started.elapsed().as_micros().min(u64::MAX as u128) as u64;
            self.metrics.record_failure(exec_us);
            return Err(EngineError::ExternalService(format!(
                "atxp direct-transfer returned {}: {}",
                status,
                String::from_utf8_lossy(&bytes)
            )));
        }

        let body: AtxpDirectTransferResponse = serde_json::from_slice(&bytes).map_err(|e| {
            EngineError::ExternalService(format!("atxp direct-transfer parse failed: {}", e))
        })?;
        let exec_us = started.elapsed().as_micros().min(u64::MAX as u128) as u64;

        if !body.ok {
            self.metrics.record_failure(exec_us);
            return Err(EngineError::ProtocolError(
                "atxp direct-transfer returned ok=false".into(),
            ));
        }

        let fee = self.fee_for(amount);
        self.metrics
            .record_success(amount, fee, exec_us, self.supports_micropayments() && amount < 100);

        Ok(PaymentResult {
            payment_id: body.tx_hash.clone(),
            protocol: "atxp".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Settled,
            execution_us: exec_us,
            fee,
            protocol_data: serde_json::json!({
                "merchant": body.merchant,
                "amount_usd": body.amount_usd,
                "tx_hash": body.tx_hash,
                "settled_amount": body.settled_amount,
                "destination": token.protocol_data.get("destination").cloned().unwrap_or(serde_json::Value::Null),
                "shared_account": token.protocol_data.get("shared_account").cloned().unwrap_or(serde_json::Value::Bool(false)),
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
            "atxp refunds are not implemented in Meridian yet".into(),
        ))
    }

    fn metrics(&self) -> ProtocolMetrics {
        self.metrics.to_metrics("atxp")
    }

    fn fee_for(&self, amount: Cents) -> Cents {
        std::cmp::max(amount * 5 / 1000, 1)
    }

    fn supports_micropayments(&self) -> bool {
        true
    }

    fn autonomy_level(&self) -> f64 {
        0.9
    }
}
