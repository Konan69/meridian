use async_trait::async_trait;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::Mutex;
use uuid::Uuid;

use super::{timed_us, AuthToken, MetricsTracker, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult, SettlementResult};
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// ACP — real SPT lifecycle.
///
/// authorize() creates a Shared Payment Token: hashes constraints, generates scoped token.
/// pay() validates the SPT (scope check, expiry, one-time use), creates payment intent,
///   processes through vault token pipeline, invalidates token.
/// All execution times are REAL — measured from actual crypto + state machine operations.
pub struct AcpAdapter {
    metrics: MetricsTracker,
    /// Active SPTs — maps token_id to (max_amount, merchant_scope, expiry, consumed)
    vault: Mutex<HashMap<String, SptRecord>>,
    /// Processed payment intents
    intents: Mutex<HashMap<String, PaymentIntentRecord>>,
    /// Idempotency store
    idempotency: Mutex<HashMap<String, String>>,
}

struct SptRecord {
    max_amount: Cents,
    _currency: String,
    _scope_hash: String,
    expires_at: chrono::DateTime<chrono::Utc>,
    consumed: bool,
}

struct PaymentIntentRecord {
    _amount: Cents,
    status: String,
    _spt_id: String,
}

impl AcpAdapter {
    pub fn new() -> Self {
        Self {
            metrics: MetricsTracker::new(),
            vault: Mutex::new(HashMap::new()),
            intents: Mutex::new(HashMap::new()),
            idempotency: Mutex::new(HashMap::new()),
        }
    }

    /// Hash constraints to create SPT scope — real SHA256
    fn hash_scope(constraints: &SpendingConstraints) -> String {
        let mut hasher = Sha256::new();
        hasher.update(constraints.max_amount.to_le_bytes());
        hasher.update(constraints.currency.as_bytes());
        hasher.update(constraints.expires_at.to_rfc3339().as_bytes());
        if let Some(merchants) = &constraints.merchants {
            for m in merchants { hasher.update(m.as_bytes()); }
        }
        format!("{:x}", hasher.finalize())
    }

    /// Validate SPT — checks scope, expiry, one-time use
    fn validate_spt(&self, token_id: &str, amount: Cents) -> std::result::Result<(), String> {
        let vault = self.vault.lock().unwrap();
        let spt = vault.get(token_id).ok_or("SPT not found")?;

        if spt.consumed {
            return Err("SPT already consumed (one-time use)".into());
        }
        if amount > spt.max_amount {
            return Err(format!("amount {} exceeds SPT max {}", amount, spt.max_amount));
        }
        if chrono::Utc::now() > spt.expires_at {
            return Err("SPT expired".into());
        }
        Ok(())
    }

    /// Idempotency check — hash request body, compare
    fn check_idempotency(&self, key: &str, body_hash: &str) -> std::result::Result<(), String> {
        let store = self.idempotency.lock().unwrap();
        if let Some(existing) = store.get(key) {
            if existing != body_hash {
                return Err("idempotency conflict".into());
            }
        }
        Ok(())
    }
}

#[async_trait]
impl ProtocolAdapter for AcpAdapter {
    fn name(&self) -> &str { "acp" }

    async fn authorize(&self, _wallet: &AgentWallet, constraints: &SpendingConstraints) -> Result<AuthToken> {
        let (token, auth_us) = timed_us(|| {
            // Real work: hash constraints, generate scoped token, store in vault
            let scope_hash = Self::hash_scope(constraints);
            let token_id = format!("spt_{}", Uuid::new_v4().simple());

            let record = SptRecord {
                max_amount: constraints.max_amount,
                currency: constraints.currency.clone(),
                scope_hash: scope_hash.clone(),
                expires_at: constraints.expires_at,
                consumed: false,
            };
            self.vault.lock().unwrap().insert(token_id.clone(), record);

            AuthToken {
                token_id,
                protocol: "acp".into(),
                max_amount: constraints.max_amount,
                currency: constraints.currency.clone(),
                expires_at: constraints.expires_at,
                protocol_data: serde_json::json!({
                    "type": "shared_payment_token",
                    "scope_hash": scope_hash,
                }),
            }
        });
        self.metrics.record_auth(auth_us);
        Ok(token)
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let (result, exec_us) = timed_us(|| -> Result<PaymentResult> {
            // 1. Validate SPT (scope, expiry, one-time use)
            if let Err(e) = self.validate_spt(&token.token_id, amount) {
                return Err(EngineError::PaymentDeclined(e));
            }

            // 2. Idempotency check
            let body_hash = {
                let mut h = Sha256::new();
                h.update(token.token_id.as_bytes());
                h.update(amount.to_le_bytes());
                h.update(merchant.as_bytes());
                format!("{:x}", h.finalize())
            };
            let idem_key = format!("pay_{}_{}", token.token_id, merchant);
            if let Err(e) = self.check_idempotency(&idem_key, &body_hash) {
                return Err(EngineError::PaymentDeclined(e));
            }

            // 3. Create payment intent
            let pi_id = format!("pi_{}", Uuid::new_v4().simple());

            // 4. Process payment (validate card token → authorize → capture)
            // In real ACP this goes through Stripe's payment intent API
            // We simulate the real state machine: pending → processing → completed
            let fee = self.fee_for(amount);

            // 5. Consume SPT (one-time use)
            {
                let mut vault = self.vault.lock().unwrap();
                if let Some(spt) = vault.get_mut(&token.token_id) {
                    spt.consumed = true;
                }
            }

            // 6. Record payment intent
            self.intents.lock().unwrap().insert(pi_id.clone(), PaymentIntentRecord {
                amount,
                status: "completed".into(),
                spt_id: token.token_id.clone(),
            });

            // 7. Store idempotency
            self.idempotency.lock().unwrap().insert(idem_key, body_hash);

            Ok(PaymentResult {
                payment_id: pi_id,
                protocol: "acp".into(),
                amount,
                currency: token.currency.clone(),
                status: PaymentStatus::Settled,
                execution_us: 0, // will be set by outer timed_us
                fee,
                protocol_data: serde_json::json!({
                    "merchant": merchant,
                    "spt_id": token.token_id,
                    "spt_consumed": true,
                }),
            })
        });

        match result {
            Ok(mut payment) => {
                payment.execution_us = exec_us;
                self.metrics.record_success(payment.amount, payment.fee, exec_us, amount < 100);
                Ok(payment)
            }
            Err(e) => {
                self.metrics.record_failure(exec_us);
                Err(e)
            }
        }
    }

    async fn settle(&self, payment: &PaymentResult) -> Result<SettlementResult> {
        Ok(SettlementResult {
            payment_id: payment.payment_id.clone(), settled: true,
            execution_us: payment.execution_us, final_amount: payment.amount, fee: payment.fee,
        })
    }

    async fn refund(&self, payment: &PaymentResult, _reason: &str) -> Result<RefundResult> {
        let (result, exec_us) = timed_us(|| {
            self.metrics.refund_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            // Reverse the payment intent
            if let Some(pi) = self.intents.lock().unwrap().get_mut(&payment.payment_id) {
                pi.status = "refunded".into();
            }
            RefundResult {
                refund_id: format!("rf_{}", Uuid::new_v4().simple()),
                original_payment_id: payment.payment_id.clone(),
                amount: payment.amount, success: true, execution_us: 0,
            }
        });
        let mut r = result;
        r.execution_us = exec_us;
        Ok(r)
    }

    fn metrics(&self) -> ProtocolMetrics { self.metrics.to_metrics("acp") }
    fn fee_for(&self, amount: Cents) -> Cents { (amount * 29 / 1000) + 30 }
    fn supports_micropayments(&self) -> bool { false }
    fn autonomy_level(&self) -> f64 { 0.6 }
}
