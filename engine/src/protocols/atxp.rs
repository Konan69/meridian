//! ATXP — Agent-to-Agent Transfer Protocol with mandate constraint engine.
//!
//! ## Real Integration Status
//!
//! **Constraint Engine**: REAL - the mandate validation logic is genuinely implemented.
//! **Network Settlement**: TODO - no public testnet found for ATXP.
//!
//! To implement real settlement:
//! 1. Contact Circuit & Chisel for testnet access
//! 2. Implement their settlement API when available
//! 3. Set ATXP_COORDINATOR_URL environment variable
//!
//! For now, mandate constraint enforcement is real (amount, merchant allowlist, expiry, etc.)
//! but settlement is recorded locally without on-chain confirmation.

use async_trait::async_trait;
use k256::ecdsa::{SigningKey, signature::Signer};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::Mutex;
use uuid::Uuid;

use super::{
    AuthToken, MetricsTracker, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult,
    SettlementResult,
};
use crate::config::Config;
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

pub struct AtxpAdapter {
    metrics: MetricsTracker,
    config: crate::config::AtxpConfig,
    mandates: Mutex<HashMap<String, MandateRecord>>,
    signing_key: SigningKey,
    http_client: reqwest::Client,
}

struct MandateRecord {
    _max_amount: Cents,
    remaining: Cents,
    _currency: String,
    allowed_merchants: Option<Vec<String>>,
    _allowed_categories: Option<Vec<String>>,
    expires_at: chrono::DateTime<chrono::Utc>,
    payment_count: u32,
    _max_nesting_depth: u32,
    _constraint_hash: String,
    revoked: bool,
}

#[derive(Debug, Serialize)]
struct CoordinatorSettleRequest {
    mandate_id: String,
    amount: i64,
    merchant: String,
    tx_hash: String,
    signature: String,
}

#[derive(Debug, Deserialize)]
struct CoordinatorSettleResponse {
    settled: bool,
    coordinator_tx_id: String,
}

impl AtxpAdapter {
    pub fn new(config: Config) -> Self {
        Self {
            metrics: MetricsTracker::new(),
            config: config.atxp,
            mandates: Mutex::new(HashMap::new()),
            signing_key: SigningKey::random(&mut rand::thread_rng()),
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default(),
        }
    }

    fn wallet_address(&self) -> String {
        let verifying_key = self.signing_key.verifying_key();
        let pub_key = verifying_key.to_encoded_point(false);
        let hash = Sha256::digest(&pub_key.as_bytes()[1..]);
        let last_20 = &hash[hash.len() - 20..];
        format!("0x{}", hex::encode(last_20))
    }

    fn validate_mandate(
        mandate: &MandateRecord,
        amount: Cents,
        merchant: &str,
    ) -> std::result::Result<(), String> {
        if mandate.revoked {
            return Err("mandate revoked".into());
        }
        if amount > mandate.remaining {
            return Err(format!(
                "amount {} exceeds mandate remaining {}",
                amount, mandate.remaining
            ));
        }
        if chrono::Utc::now() > mandate.expires_at {
            return Err("mandate expired".into());
        }
        if let Some(merchants) = &mandate.allowed_merchants {
            if !merchants.is_empty() && !merchants.iter().any(|m| m == merchant || m == "*") {
                return Err(format!("merchant {} not in mandate allowlist", merchant));
            }
        }
        Ok(())
    }

    async fn settle_on_coordinator(
        &self,
        mandate_id: &str,
        amount: Cents,
        merchant: &str,
        tx_hash: &str,
    ) -> Result<String> {
        // TODO: Real ATXP coordinator settlement
        // When Circuit & Chisel provide testnet access, implement:
        // 1. Sign the settlement request
        // 2. POST to self.config.coordinator_url
        // 3. Return coordinator's transaction ID

        if self.config.coordinator_url == "https://circuit.cloud/atxp" {
            tracing::warn!("ATXP: Using simulated settlement (no coordinator testnet)");
            return Ok(format!("atxp_sim_{}", Uuid::new_v4().simple()));
        }

        let payload = CoordinatorSettleRequest {
            mandate_id: mandate_id.to_string(),
            amount: amount as i64,
            merchant: merchant.to_string(),
            tx_hash: tx_hash.to_string(),
            signature: "".to_string(), // TODO: add real signature
        };

        let resp = self
            .http_client
            .post(&self.config.coordinator_url)
            .json(&payload)
            .send()
            .await
            .map_err(|e| {
                EngineError::ExternalService(format!("ATXP coordinator request failed: {}", e))
            })?;

        if !resp.status().is_success() {
            return Err(EngineError::ExternalService(format!(
                "ATXP coordinator error: {}",
                resp.status()
            )));
        }

        let settle_resp: CoordinatorSettleResponse = resp.json().await.map_err(|e| {
            EngineError::ExternalService(format!("failed to parse coordinator response: {}", e))
        })?;

        Ok(settle_resp.coordinator_tx_id)
    }
}

#[async_trait]
impl ProtocolAdapter for AtxpAdapter {
    fn name(&self) -> &str {
        "atxp"
    }

    async fn authorize(
        &self,
        _wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        let start = std::time::Instant::now();
        let mandate_id = format!("mandate_{}", Uuid::new_v4().simple());

        let mut hasher = Sha256::new();
        hasher.update(b"atxp:mandate:v1:");
        hasher.update(constraints.max_amount.to_le_bytes());
        hasher.update(constraints.currency.as_bytes());
        hasher.update(constraints.expires_at.to_rfc3339().as_bytes());
        if let Some(merchants) = &constraints.merchants {
            for m in merchants {
                hasher.update(m.as_bytes());
            }
        }
        if let Some(cats) = &constraints.categories {
            for c in cats {
                hasher.update(c.as_bytes());
            }
        }
        let constraint_hash = format!("{:x}", hasher.finalize());

        self.mandates.lock().unwrap().insert(
            mandate_id.clone(),
            MandateRecord {
                _max_amount: constraints.max_amount,
                remaining: constraints.max_amount,
                _currency: constraints.currency.clone(),
                allowed_merchants: constraints.merchants.clone(),
                _allowed_categories: constraints.categories.clone(),
                expires_at: constraints.expires_at,
                payment_count: 0,
                _max_nesting_depth: 3,
                _constraint_hash: constraint_hash.clone(),
                revoked: false,
            },
        );

        let token = AuthToken {
            token_id: mandate_id,
            protocol: "atxp".into(),
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "mandate_type": "delegated",
                "constraint_hash": constraint_hash,
                "allow_nested": true,
                "max_nesting_depth": 3,
                "revocable": true,
                "wallet_address": self.wallet_address(),
                "coordinator_url": self.config.coordinator_url,
            }),
        };

        let auth_us = start.elapsed().as_micros() as u64;
        self.metrics.record_auth(auth_us);
        Ok(token)
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let start = std::time::Instant::now();

        {
            let mandates = self.mandates.lock().unwrap();
            let mandate = mandates
                .get(&token.token_id)
                .ok_or_else(|| EngineError::PaymentDeclined("mandate not found".into()))?;

            if let Err(e) = Self::validate_mandate(mandate, amount, merchant) {
                return Err(EngineError::PaymentDeclined(e));
            }
        }

        {
            let mut mandates = self.mandates.lock().unwrap();
            let mandate = mandates.get_mut(&token.token_id).unwrap();
            mandate.remaining -= amount;
            mandate.payment_count += 1;
        }

        let mut tx_hasher = Sha256::new();
        tx_hasher.update(token.token_id.as_bytes());
        tx_hasher.update(amount.to_le_bytes());
        tx_hasher.update(merchant.as_bytes());
        tx_hasher.update(chrono::Utc::now().to_rfc3339().as_bytes());
        let tx_hash = format!("{:x}", tx_hasher.finalize());

        let fee = self.fee_for(amount);
        let coordinator_tx_id = self
            .settle_on_coordinator(&token.token_id, amount, merchant, &tx_hash)
            .await?;

        let exec_us = start.elapsed().as_micros() as u64;

        let payment = PaymentResult {
            payment_id: coordinator_tx_id,
            protocol: "atxp".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Settled,
            execution_us: exec_us,
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "mandate_id": token.token_id,
                "tx_hash": tx_hash,
                "mandate_remaining": self.mandates.lock().unwrap()
                    .get(&token.token_id).map(|m| m.remaining).unwrap_or(0),
                "wallet_address": self.wallet_address(),
            }),
        };

        self.metrics
            .record_success(payment.amount, payment.fee, exec_us, amount < 100);
        Ok(payment)
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

    async fn refund(&self, payment: &PaymentResult, _reason: &str) -> Result<RefundResult> {
        let start = std::time::Instant::now();
        self.metrics
            .refund_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);

        let mandate_id = payment.protocol_data["mandate_id"]
            .as_str()
            .unwrap_or("")
            .to_string();
        if let Some(mandate) = self.mandates.lock().unwrap().get_mut(&mandate_id) {
            mandate.remaining += payment.amount;
        }

        Ok(RefundResult {
            refund_id: format!("atxp_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            execution_us: start.elapsed().as_micros() as u64,
        })
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
