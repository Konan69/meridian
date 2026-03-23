use async_trait::async_trait;
use uuid::Uuid;

use super::{
    jittered_ms, should_fail, AuthToken, MetricsTracker, PaymentResult, PaymentStatus,
    ProtocolAdapter, RefundResult, SettlementResult,
};
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// ACP (Agentic Commerce Protocol) — OpenAI + Stripe
///
/// SPTs scoped to merchant/amount/time. Card network settlement.
/// 2.9% + 30¢ fees. No micropayments (30¢ floor makes them impractical).
/// ~3% failure rate (3DS challenges, card declines, network timeouts).
pub struct AcpAdapter {
    metrics: MetricsTracker,
}

impl AcpAdapter {
    pub fn new() -> Self {
        Self {
            metrics: MetricsTracker::new(),
        }
    }
}

#[async_trait]
impl ProtocolAdapter for AcpAdapter {
    fn name(&self) -> &str { "acp" }

    async fn authorize(&self, _wallet: &AgentWallet, constraints: &SpendingConstraints) -> Result<AuthToken> {
        Ok(AuthToken {
            token_id: format!("spt_{}", Uuid::new_v4().simple()),
            protocol: "acp".into(),
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "type": "shared_payment_token",
                "requires_confirmation": constraints.requires_confirmation,
                "merchants": constraints.merchants,
            }),
        })
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        if amount > token.max_amount {
            self.metrics.record_failure();
            return Err(EngineError::PaymentDeclined("amount exceeds SPT allowance".into()));
        }

        // ACP failure: 3DS challenge, card decline, network timeout
        if should_fail(self.failure_rate()) {
            self.metrics.record_failure();
            return Err(EngineError::PaymentDeclined("card declined (3DS challenge failed)".into()));
        }

        let fee = self.fee_for(amount);
        let settlement_ms = self.settlement_latency_ms();
        self.metrics.record_success(amount, fee, settlement_ms, amount < 100);

        Ok(PaymentResult {
            payment_id: format!("pi_{}", Uuid::new_v4().simple()),
            protocol: "acp".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Pending, // card networks settle async
            settlement_time_ms: settlement_ms,
            fee,
            protocol_data: serde_json::json!({ "merchant": merchant, "spt_id": token.token_id }),
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
            refund_id: format!("rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            processing_time: std::time::Duration::from_millis(jittered_ms(2000, 0.3)),
        })
    }

    fn metrics(&self) -> ProtocolMetrics { self.metrics.to_metrics("acp", 150.0) }
    fn fee_for(&self, amount: Cents) -> Cents { (amount * 29 / 1000) + 30 }
    fn settlement_latency_ms(&self) -> u64 { jittered_ms(2000, 0.4) } // 1200-2800ms
    fn supports_micropayments(&self) -> bool { false }
    fn autonomy_level(&self) -> f64 { 0.6 }
    fn failure_rate(&self) -> f64 { 0.03 } // 3% — 3DS, card declines
}
