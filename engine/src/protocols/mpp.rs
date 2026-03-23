use async_trait::async_trait;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use uuid::Uuid;

use super::{AuthToken, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult, SettlementResult};
use crate::core::error::Result;
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// MPP (Machine Payments Protocol) — Stripe + Tempo
///
/// HTTP 402 + sessions primitive. Agent authorizes spending limit upfront,
/// then streams micropayments without per-tx settlement.
/// Bridges crypto (Tempo/USDC) and fiat (Stripe cards/BNPL).
/// Best for streaming/metered access patterns.
pub struct MppAdapter {
    txn_count: AtomicU64,
    success_count: AtomicU64,
    fail_count: AtomicU64,
    volume: AtomicU64,
    fees: AtomicU64,
    micropay_count: AtomicU64,
}

impl MppAdapter {
    pub fn new() -> Self {
        Self {
            txn_count: AtomicU64::new(0),
            success_count: AtomicU64::new(0),
            fail_count: AtomicU64::new(0),
            volume: AtomicU64::new(0),
            fees: AtomicU64::new(0),
            micropay_count: AtomicU64::new(0),
        }
    }
}

#[async_trait]
impl ProtocolAdapter for MppAdapter {
    fn name(&self) -> &str {
        "mpp"
    }

    async fn authorize(
        &self,
        _wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        // MPP: open a session with a spending limit
        let token_id = format!("mpp_session_{}", Uuid::new_v4().simple());
        Ok(AuthToken {
            token_id,
            protocol: "mpp".into(),
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "session_type": "streaming",
                "challenge_id": Uuid::new_v4().to_string(),
                "rail": "tempo_usdc",  // or "stripe_card"
                "remaining_budget": constraints.max_amount,
            }),
        })
    }

    async fn pay(
        &self,
        token: &AuthToken,
        amount: Cents,
        merchant: &str,
    ) -> Result<PaymentResult> {
        self.txn_count.fetch_add(1, Ordering::Relaxed);

        if amount > token.max_amount {
            self.fail_count.fetch_add(1, Ordering::Relaxed);
            return Err(crate::core::error::EngineError::PaymentDeclined(
                "amount exceeds session budget".into(),
            ));
        }

        if amount < 100 {
            self.micropay_count.fetch_add(1, Ordering::Relaxed);
        }

        let fee = self.fee_for(amount);
        self.success_count.fetch_add(1, Ordering::Relaxed);
        self.volume.fetch_add(amount, Ordering::Relaxed);
        self.fees.fetch_add(fee, Ordering::Relaxed);

        // MPP: within a session, payments are batched and settled periodically
        Ok(PaymentResult {
            payment_id: format!("mpp_pi_{}", Uuid::new_v4().simple()),
            protocol: "mpp".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Settled,
            settlement_time: self.settlement_latency(),
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "session_id": token.token_id,
                "rail": "tempo_usdc",
                "batch_settled": true,
            }),
        })
    }

    async fn settle(&self, payment: &PaymentResult) -> Result<SettlementResult> {
        Ok(SettlementResult {
            payment_id: payment.payment_id.clone(),
            settled: true,
            settlement_time: self.settlement_latency(),
            final_amount: payment.amount,
            fee: payment.fee,
        })
    }

    async fn refund(&self, payment: &PaymentResult, _reason: &str) -> Result<RefundResult> {
        Ok(RefundResult {
            refund_id: format!("mpp_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            processing_time: Duration::from_millis(500),
        })
    }

    fn metrics(&self) -> ProtocolMetrics {
        ProtocolMetrics {
            protocol: "mpp".into(),
            total_transactions: self.txn_count.load(Ordering::Relaxed),
            successful_transactions: self.success_count.load(Ordering::Relaxed),
            failed_transactions: self.fail_count.load(Ordering::Relaxed),
            total_volume_cents: self.volume.load(Ordering::Relaxed),
            total_fees_cents: self.fees.load(Ordering::Relaxed),
            avg_settlement_ms: 500.0,          // batched settlement within session
            avg_authorization_ms: 100.0,        // session creation
            micropayment_count: self.micropay_count.load(Ordering::Relaxed),
            refund_count: 0,
        }
    }

    /// MPP fee: 1.5% (lower than ACP — session amortization)
    fn fee_for(&self, amount: Cents) -> Cents {
        std::cmp::max((amount * 15 / 1000) + 5, 1)
    }

    /// Batched settlement within session: ~500ms
    fn settlement_latency(&self) -> Duration {
        Duration::from_millis(500)
    }

    fn supports_micropayments(&self) -> bool {
        true // session-based streaming enables micropayments
    }

    fn autonomy_level(&self) -> f64 {
        0.8 // session-bounded autonomy — human sets budget, agent streams within
    }
}
