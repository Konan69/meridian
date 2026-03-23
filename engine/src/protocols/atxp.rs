use async_trait::async_trait;
use uuid::Uuid;

use super::{
    jittered_ms, should_fail, AuthToken, MetricsTracker, PaymentResult, PaymentStatus,
    ProtocolAdapter, RefundResult, SettlementResult,
};
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// ATXP (Agent Transaction Protocol) — Circuit & Chisel
///
/// Mandate model with nested agent-to-agent transactions.
/// 0.5% fee (protocol-native). Micropayments supported.
/// ~1.5% failure rate (mandate constraint violations, nested tx depth exceeded).
/// Fastest settlement (~150ms protocol-native).
///
/// NOTE: No public spec. Modeled from press descriptions.
pub struct AtxpAdapter {
    metrics: MetricsTracker,
}

impl AtxpAdapter {
    pub fn new() -> Self {
        Self { metrics: MetricsTracker::new() }
    }
}

#[async_trait]
impl ProtocolAdapter for AtxpAdapter {
    fn name(&self) -> &str { "atxp" }

    async fn authorize(&self, _wallet: &AgentWallet, constraints: &SpendingConstraints) -> Result<AuthToken> {
        Ok(AuthToken {
            token_id: format!("mandate_{}", Uuid::new_v4().simple()),
            protocol: "atxp".into(),
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "mandate_type": "delegated",
                "constraints": {
                    "merchants": constraints.merchants,
                    "categories": constraints.categories,
                    "max_amount": constraints.max_amount,
                },
                "allow_nested": true,
                "revocable": true,
            }),
        })
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        if amount > token.max_amount {
            self.metrics.record_failure();
            return Err(EngineError::PaymentDeclined("amount exceeds mandate constraints".into()));
        }

        if should_fail(self.failure_rate()) {
            self.metrics.record_failure();
            return Err(EngineError::PaymentDeclined("mandate constraint violation or nested depth exceeded".into()));
        }

        let fee = self.fee_for(amount);
        let settlement_ms = self.settlement_latency_ms();
        self.metrics.record_success(amount, fee, settlement_ms, amount < 100);

        Ok(PaymentResult {
            payment_id: format!("atxp_pi_{}", Uuid::new_v4().simple()),
            protocol: "atxp".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Settled,
            settlement_time_ms: settlement_ms,
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "mandate_id": token.token_id,
                "nested_depth": 0,
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
            refund_id: format!("atxp_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            processing_time: std::time::Duration::from_millis(jittered_ms(150, 0.5)),
        })
    }

    fn metrics(&self) -> ProtocolMetrics { self.metrics.to_metrics("atxp", 200.0) }
    fn fee_for(&self, amount: Cents) -> Cents { std::cmp::max(amount * 5 / 1000, 1) }
    fn settlement_latency_ms(&self) -> u64 { jittered_ms(150, 0.5) } // 75-225ms
    fn supports_micropayments(&self) -> bool { true }
    fn autonomy_level(&self) -> f64 { 0.9 }
    fn failure_rate(&self) -> f64 { 0.015 } // 1.5% — mandate violations
}
