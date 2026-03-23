use async_trait::async_trait;
use uuid::Uuid;

use super::{
    jittered_ms, should_fail, AuthToken, MetricsTracker, PaymentResult, PaymentStatus,
    ProtocolAdapter, RefundResult, SettlementResult,
};
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// AP2 (Agent Payments Protocol) — Google
///
/// VDCs with Intent/Cart Mandates. Strongest trust model.
/// 2.5% + 20¢ fee. Multi-rail but primarily card-based.
/// ~4% failure rate (VDC verification failures, mandate expiry, 3DS on underlying card).
/// Slowest settlement due to VDC signing ceremony + card network.
pub struct Ap2Adapter {
    metrics: MetricsTracker,
}

impl Ap2Adapter {
    pub fn new() -> Self {
        Self { metrics: MetricsTracker::new() }
    }
}

#[async_trait]
impl ProtocolAdapter for Ap2Adapter {
    fn name(&self) -> &str { "ap2" }

    async fn authorize(&self, _wallet: &AgentWallet, constraints: &SpendingConstraints) -> Result<AuthToken> {
        let mandate_type = if constraints.requires_confirmation { "cart_mandate" } else { "intent_mandate" };
        Ok(AuthToken {
            token_id: format!("ap2_{}", Uuid::new_v4().simple()),
            protocol: "ap2".into(),
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "mandate_type": mandate_type,
                "vdc_signed": true,
                "merchants": constraints.merchants,
                "categories": constraints.categories,
                "authorization_jwt": format!("eyJ0eXAiOiJ2YytzZC1qd3QifQ.{}", Uuid::new_v4().simple()),
            }),
        })
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        if amount > token.max_amount {
            self.metrics.record_failure();
            return Err(EngineError::PaymentDeclined("amount exceeds mandate allowance".into()));
        }

        // AP2: VDC verification can fail, mandate can expire, underlying card can decline
        if should_fail(self.failure_rate()) {
            self.metrics.record_failure();
            return Err(EngineError::PaymentDeclined("VDC verification failed or mandate expired".into()));
        }

        let fee = self.fee_for(amount);
        let settlement_ms = self.settlement_latency_ms();
        self.metrics.record_success(amount, fee, settlement_ms, amount < 100);

        Ok(PaymentResult {
            payment_id: format!("ap2_pi_{}", Uuid::new_v4().simple()),
            protocol: "ap2".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Pending,
            settlement_time_ms: settlement_ms,
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "mandate_id": token.token_id,
                "vdc_verified": true,
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
            refund_id: format!("ap2_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            processing_time: std::time::Duration::from_millis(jittered_ms(3000, 0.3)),
        })
    }

    fn metrics(&self) -> ProtocolMetrics { self.metrics.to_metrics("ap2", 500.0) }
    fn fee_for(&self, amount: Cents) -> Cents { (amount * 25 / 1000) + 20 }
    fn settlement_latency_ms(&self) -> u64 { jittered_ms(3000, 0.35) } // 1950-4050ms
    fn supports_micropayments(&self) -> bool { false }
    fn autonomy_level(&self) -> f64 { 0.5 }
    fn failure_rate(&self) -> f64 { 0.04 } // 4% — VDC failures, mandate expiry
}
