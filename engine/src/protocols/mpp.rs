use async_trait::async_trait;
use uuid::Uuid;

use super::{
    jittered_ms, should_fail, AuthToken, MetricsTracker, PaymentResult, PaymentStatus,
    ProtocolAdapter, RefundResult, SettlementResult,
};
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// MPP (Machine Payments Protocol) — Stripe + Tempo
///
/// HTTP 402 + sessions. Streaming micropayments within a budget.
/// 1.5% + 5¢ fee. Multi-rail (stablecoins + fiat).
/// ~2% failure rate (session budget exhausted, Tempo network congestion).
/// 500ms settlement with session batching.
pub struct MppAdapter {
    metrics: MetricsTracker,
}

impl MppAdapter {
    pub fn new() -> Self {
        Self { metrics: MetricsTracker::new() }
    }
}

#[async_trait]
impl ProtocolAdapter for MppAdapter {
    fn name(&self) -> &str { "mpp" }

    async fn authorize(&self, _wallet: &AgentWallet, constraints: &SpendingConstraints) -> Result<AuthToken> {
        Ok(AuthToken {
            token_id: format!("mpp_session_{}", Uuid::new_v4().simple()),
            protocol: "mpp".into(),
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "session_type": "streaming",
                "rail": "tempo_usdc",
                "remaining_budget": constraints.max_amount,
            }),
        })
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        if amount > token.max_amount {
            self.metrics.record_failure();
            return Err(EngineError::PaymentDeclined("amount exceeds session budget".into()));
        }

        if should_fail(self.failure_rate()) {
            self.metrics.record_failure();
            return Err(EngineError::PaymentDeclined("session budget exhausted or Tempo congestion".into()));
        }

        let fee = self.fee_for(amount);
        let settlement_ms = self.settlement_latency_ms();
        self.metrics.record_success(amount, fee, settlement_ms, amount < 100);

        Ok(PaymentResult {
            payment_id: format!("mpp_pi_{}", Uuid::new_v4().simple()),
            protocol: "mpp".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Settled,
            settlement_time_ms: settlement_ms,
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "session_id": token.token_id,
                "rail": "tempo_usdc",
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
            refund_id: format!("mpp_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            processing_time: std::time::Duration::from_millis(jittered_ms(500, 0.4)),
        })
    }

    fn metrics(&self) -> ProtocolMetrics { self.metrics.to_metrics("mpp", 100.0) }
    fn fee_for(&self, amount: Cents) -> Cents { std::cmp::max((amount * 15 / 1000) + 5, 1) }
    fn settlement_latency_ms(&self) -> u64 { jittered_ms(500, 0.4) } // 300-700ms
    fn supports_micropayments(&self) -> bool { true }
    fn autonomy_level(&self) -> f64 { 0.8 }
    fn failure_rate(&self) -> f64 { 0.02 } // 2% — session budget, network
}
