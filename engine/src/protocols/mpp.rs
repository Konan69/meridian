use async_trait::async_trait;
use k256::ecdsa::{signature::Signer, Signature, SigningKey};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::Mutex;
use uuid::Uuid;

use super::{timed_us, AuthToken, MetricsTracker, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult, SettlementResult};
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// MPP — real session lifecycle with budget tracking.
///
/// authorize() creates a spending session with a budget cap + ECDSA challenge.
/// pay() validates the session budget, debits the amount, signs a receipt,
///   batches the payment within the session.
/// Multiple payments can stream through a single session (the differentiator).
/// Session budget tracking is REAL — concurrent payments debit atomically.
pub struct MppAdapter {
    metrics: MetricsTracker,
    signing_key: SigningKey,
    /// Active sessions with remaining budgets
    sessions: Mutex<HashMap<String, SessionRecord>>,
}

struct SessionRecord {
    remaining_budget: Cents,
    total_spent: Cents,
    payment_count: u32,
    _challenge_hash: String,
}

impl MppAdapter {
    pub fn new() -> Self {
        Self {
            metrics: MetricsTracker::new(),
            signing_key: SigningKey::random(&mut rand::thread_rng()),
            sessions: Mutex::new(HashMap::new()),
        }
    }
}

#[async_trait]
impl ProtocolAdapter for MppAdapter {
    fn name(&self) -> &str { "mpp" }

    async fn authorize(&self, _wallet: &AgentWallet, constraints: &SpendingConstraints) -> Result<AuthToken> {
        let (token, auth_us) = timed_us(|| {
            let session_id = format!("mpp_session_{}", Uuid::new_v4().simple());

            // Create challenge hash for the session
            let mut hasher = Sha256::new();
            hasher.update(session_id.as_bytes());
            hasher.update(constraints.max_amount.to_le_bytes());
            hasher.update(chrono::Utc::now().to_rfc3339().as_bytes());
            let challenge = format!("{:x}", hasher.finalize());

            // Sign the challenge (session authentication)
            let challenge_sig: Signature = self.signing_key.sign(challenge.as_bytes());
            let _ = challenge_sig; // used for real crypto cost

            self.sessions.lock().unwrap().insert(session_id.clone(), SessionRecord {
                remaining_budget: constraints.max_amount,
                total_spent: 0,
                payment_count: 0,
                challenge_hash: challenge.clone(),
            });

            AuthToken {
                token_id: session_id,
                protocol: "mpp".into(),
                max_amount: constraints.max_amount,
                currency: constraints.currency.clone(),
                expires_at: constraints.expires_at,
                protocol_data: serde_json::json!({
                    "session_type": "streaming",
                    "challenge": challenge,
                    "rail": "tempo_usdc",
                }),
            }
        });
        self.metrics.record_auth(auth_us);
        Ok(token)
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let (result, exec_us) = timed_us(|| -> Result<PaymentResult> {
            // 1. Validate session and debit atomically
            {
                let mut sessions = self.sessions.lock().unwrap();
                let session = sessions.get_mut(&token.token_id)
                    .ok_or_else(|| EngineError::PaymentDeclined("session not found".into()))?;

                if amount > session.remaining_budget {
                    return Err(EngineError::PaymentDeclined(format!(
                        "amount {} exceeds session remaining budget {}",
                        amount, session.remaining_budget
                    )));
                }

                // Atomic debit
                session.remaining_budget -= amount;
                session.total_spent += amount;
                session.payment_count += 1;
            }

            // 2. Sign payment receipt
            let mut receipt = Vec::new();
            receipt.extend_from_slice(b"mpp:receipt:");
            receipt.extend_from_slice(&amount.to_le_bytes());
            receipt.extend_from_slice(merchant.as_bytes());
            receipt.extend_from_slice(token.token_id.as_bytes());
            let receipt_hash = Sha256::digest(&receipt);
            let _receipt_sig: Signature = self.signing_key.sign(&receipt_hash);

            let fee = self.fee_for(amount);

            Ok(PaymentResult {
                payment_id: format!("mpp_pi_{}", Uuid::new_v4().simple()),
                protocol: "mpp".into(),
                amount,
                currency: token.currency.clone(),
                status: PaymentStatus::Settled,
                execution_us: 0,
                fee,
                protocol_data: serde_json::json!({
                    "merchant": merchant,
                    "session_id": token.token_id,
                    "receipt_hash": format!("{:x}", receipt_hash),
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
        let (mut r, exec_us) = timed_us(|| {
            self.metrics.refund_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            // Credit back to session
            if let Some(session) = self.sessions.lock().unwrap().values_mut().next() {
                session.remaining_budget += payment.amount;
            }
            RefundResult {
                refund_id: format!("mpp_rf_{}", Uuid::new_v4().simple()),
                original_payment_id: payment.payment_id.clone(),
                amount: payment.amount, success: true, execution_us: 0,
            }
        });
        r.execution_us = exec_us;
        Ok(r)
    }

    fn metrics(&self) -> ProtocolMetrics { self.metrics.to_metrics("mpp") }
    fn fee_for(&self, amount: Cents) -> Cents { std::cmp::max((amount * 15 / 1000) + 5, 1) }
    fn supports_micropayments(&self) -> bool { true }
    fn autonomy_level(&self) -> f64 { 0.8 }
}
