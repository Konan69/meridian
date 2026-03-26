use async_trait::async_trait;
use serde::{Deserialize, Serialize};

use super::{
    AuthToken, MetricsTracker, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult,
    SettlementResult,
};
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

#[derive(Debug)]
pub struct RemoteAdapter {
    metrics: MetricsTracker,
    protocol: String,
    base_url: String,
    http_client: reqwest::Client,
    fee_bps: u64,
    supports_micropayments: bool,
    autonomy_level: f64,
}

#[derive(Debug, Serialize)]
struct AuthorizeRequest<'a> {
    wallet: &'a AgentWallet,
    constraints: &'a SpendingConstraints,
}

#[derive(Debug, Serialize)]
struct PayRequest<'a> {
    token: &'a AuthToken,
    amount: Cents,
    merchant: &'a str,
}

#[derive(Debug, Serialize)]
struct SettleRequest<'a> {
    payment: &'a PaymentResult,
}

#[derive(Debug, Serialize)]
struct RefundRequest<'a> {
    payment: &'a PaymentResult,
    reason: &'a str,
}

#[derive(Debug, Deserialize)]
struct CapabilityResponse {
    #[serde(default)]
    fee_bps: u64,
    #[serde(default)]
    supports_micropayments: bool,
    #[serde(default = "default_autonomy")]
    autonomy_level: f64,
}

fn default_autonomy() -> f64 {
    1.0
}

impl RemoteAdapter {
    pub async fn new(protocol: &str, base_url: &str) -> Result<Self> {
        let http_client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .build()
            .unwrap_or_default();

        let capabilities_url = format!("{}/capabilities", base_url.trim_end_matches('/'));
        let resp = http_client
            .get(&capabilities_url)
            .send()
            .await
            .map_err(|e| {
                EngineError::ExternalService(format!(
                    "{} adapter capability probe failed: {}",
                    protocol, e
                ))
            })?;

        if !resp.status().is_success() {
            return Err(EngineError::ExternalService(format!(
                "{} adapter capability probe returned {}",
                protocol,
                resp.status()
            )));
        }

        let capabilities: CapabilityResponse = resp.json().await.map_err(|e| {
            EngineError::ExternalService(format!(
                "{} adapter capability parse failed: {}",
                protocol, e
            ))
        })?;

        Ok(Self {
            metrics: MetricsTracker::new(),
            protocol: protocol.to_string(),
            base_url: base_url.trim_end_matches('/').to_string(),
            http_client,
            fee_bps: capabilities.fee_bps,
            supports_micropayments: capabilities.supports_micropayments,
            autonomy_level: capabilities.autonomy_level,
        })
    }

    async fn post_json<Req: Serialize, Resp: for<'de> Deserialize<'de>>(
        &self,
        path: &str,
        body: &Req,
    ) -> Result<Resp> {
        let url = format!("{}/{}", self.base_url, path.trim_start_matches('/'));
        let resp = self
            .http_client
            .post(&url)
            .json(body)
            .send()
            .await
            .map_err(|e| {
                EngineError::ExternalService(format!(
                    "{} adapter request failed at {}: {}",
                    self.protocol, path, e
                ))
            })?;

        let status = resp.status();
        let bytes = resp.bytes().await.map_err(|e| {
            EngineError::ExternalService(format!(
                "{} adapter response read failed at {}: {}",
                self.protocol, path, e
            ))
        })?;

        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "{} adapter returned {} at {}: {}",
                self.protocol,
                status,
                path,
                String::from_utf8_lossy(&bytes)
            )));
        }

        serde_json::from_slice(&bytes).map_err(|e| {
            EngineError::ExternalService(format!(
                "{} adapter response parse failed at {}: {}",
                self.protocol, path, e
            ))
        })
    }
}

#[async_trait]
impl ProtocolAdapter for RemoteAdapter {
    fn name(&self) -> &str {
        &self.protocol
    }

    async fn authorize(
        &self,
        wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        let start = std::time::Instant::now();
        let token = self
            .post_json(
                "/authorize",
                &AuthorizeRequest {
                    wallet,
                    constraints,
                },
            )
            .await?;
        self.metrics.record_auth(start.elapsed().as_micros() as u64);
        Ok(token)
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let start = std::time::Instant::now();
        let payment: PaymentResult = self
            .post_json(
                "/pay",
                &PayRequest {
                    token,
                    amount,
                    merchant,
                },
            )
            .await?;

        let exec_us = start.elapsed().as_micros() as u64;
        match payment.status {
            PaymentStatus::Settled | PaymentStatus::Pending => {
                self.metrics
                    .record_success(payment.amount, payment.fee, exec_us, amount < 100);
            }
            PaymentStatus::Failed | PaymentStatus::Refunded => {
                self.metrics.record_failure(exec_us);
            }
        }

        Ok(payment)
    }

    async fn settle(&self, payment: &PaymentResult) -> Result<SettlementResult> {
        self.post_json("/settle", &SettleRequest { payment }).await
    }

    async fn refund(&self, payment: &PaymentResult, reason: &str) -> Result<RefundResult> {
        self.post_json("/refund", &RefundRequest { payment, reason })
            .await
    }

    fn metrics(&self) -> ProtocolMetrics {
        self.metrics.to_metrics(&self.protocol)
    }

    fn fee_for(&self, amount: Cents) -> Cents {
        std::cmp::max(amount.saturating_mul(self.fee_bps) / 10_000, 1)
    }

    fn supports_micropayments(&self) -> bool {
        self.supports_micropayments
    }

    fn autonomy_level(&self) -> f64 {
        self.autonomy_level
    }
}
