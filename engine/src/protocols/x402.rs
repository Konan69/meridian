use async_trait::async_trait;
use uuid::Uuid;

use super::{
    jittered_ms, should_fail, AuthToken, MetricsTracker, PaymentResult, PaymentStatus,
    ProtocolAdapter, RefundResult, SettlementResult,
};
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// x402 — Coinbase
///
/// Stateless HTTP 402. USDC on-chain via facilitator.
/// 0.1% fee (L2 gas). Micropayments to $0.001.
/// ~1% failure rate (insufficient USDC balance, facilitator timeout, nonce collision).
/// Instant settlement on Base L2 (~200ms with jitter).
pub struct X402Adapter {
    metrics: MetricsTracker,
}

impl X402Adapter {
    pub fn new() -> Self {
        Self { metrics: MetricsTracker::new() }
    }
}

#[async_trait]
impl ProtocolAdapter for X402Adapter {
    fn name(&self) -> &str { "x402" }

    async fn authorize(&self, _wallet: &AgentWallet, constraints: &SpendingConstraints) -> Result<AuthToken> {
        Ok(AuthToken {
            token_id: format!("x402_{}", Uuid::new_v4().simple()),
            protocol: "x402".into(),
            max_amount: constraints.max_amount,
            currency: "usdc".into(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({ "scheme": "exact", "network": "base", "asset": "USDC" }),
        })
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        if amount > token.max_amount {
            self.metrics.record_failure();
            return Err(EngineError::PaymentDeclined("amount exceeds pre-signed payload".into()));
        }

        if should_fail(self.failure_rate()) {
            self.metrics.record_failure();
            return Err(EngineError::PaymentDeclined("insufficient USDC balance or facilitator timeout".into()));
        }

        let fee = self.fee_for(amount);
        let settlement_ms = self.settlement_latency_ms();
        self.metrics.record_success(amount, fee, settlement_ms, amount < 100);

        Ok(PaymentResult {
            payment_id: format!("x402_pi_{}", Uuid::new_v4().simple()),
            protocol: "x402".into(),
            amount,
            currency: "usdc".into(),
            status: PaymentStatus::Settled, // on-chain = instant finality
            settlement_time_ms: settlement_ms,
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "tx_hash": format!("0x{}", Uuid::new_v4().simple()),
                "network": "base",
                "facilitator": "coinbase",
            }),
        })
    }

    async fn settle(&self, payment: &PaymentResult) -> Result<SettlementResult> {
        Ok(SettlementResult {
            payment_id: payment.payment_id.clone(),
            settled: true,
            settlement_time_ms: payment.settlement_time_ms,
            final_amount: payment.amount,
            fee: payment.fee,
        })
    }

    async fn refund(&self, payment: &PaymentResult, _reason: &str) -> Result<RefundResult> {
        self.metrics.refund_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Ok(RefundResult {
            refund_id: format!("x402_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            processing_time: std::time::Duration::from_millis(jittered_ms(200, 0.5)),
        })
    }

    fn metrics(&self) -> ProtocolMetrics { self.metrics.to_metrics("x402", 50.0) }
    fn fee_for(&self, amount: Cents) -> Cents { std::cmp::max(amount / 1000, 1) }
    fn settlement_latency_ms(&self) -> u64 { jittered_ms(200, 0.5) } // 100-300ms
    fn supports_micropayments(&self) -> bool { true }
    fn autonomy_level(&self) -> f64 { 1.0 }
    fn failure_rate(&self) -> f64 { 0.01 } // 1% — balance issues, nonce collisions
}
