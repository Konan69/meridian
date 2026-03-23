use async_trait::async_trait;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use uuid::Uuid;

use super::{AuthToken, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult, SettlementResult};
use crate::core::error::Result;
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// ATXP (Agent Transaction Protocol) — Circuit & Chisel
///
/// Mandate model: user encodes constraints (amount, merchant, category, time, approval rules).
/// Agent presents mandate to request charges.
/// Supports nested transactions between agents and autonomous tool discovery.
/// Designed for agent-to-agent commerce, not just agent-to-merchant.
///
/// NOTE: No public spec. Modeled from press descriptions. Lowest fidelity adapter.
pub struct AtxpAdapter {
    txn_count: AtomicU64,
    success_count: AtomicU64,
    fail_count: AtomicU64,
    volume: AtomicU64,
    fees: AtomicU64,
    micropay_count: AtomicU64,
}

impl AtxpAdapter {
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
impl ProtocolAdapter for AtxpAdapter {
    fn name(&self) -> &str {
        "atxp"
    }

    async fn authorize(
        &self,
        _wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        // ATXP: create a mandate encoding all constraints
        let token_id = format!("mandate_{}", Uuid::new_v4().simple());
        Ok(AuthToken {
            token_id,
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
                    "time_window_expires": constraints.expires_at.to_rfc3339(),
                },
                "approval_rules": {
                    "requires_confirmation": constraints.requires_confirmation,
                    "allow_nested": true,  // ATXP supports nested agent-to-agent
                },
                "dispute_handling": "automatic",
                "revocable": true,
                "pausable": true,
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
                "amount exceeds mandate constraints".into(),
            ));
        }

        if amount < 100 {
            self.micropay_count.fetch_add(1, Ordering::Relaxed);
        }

        let fee = self.fee_for(amount);
        self.success_count.fetch_add(1, Ordering::Relaxed);
        self.volume.fetch_add(amount, Ordering::Relaxed);
        self.fees.fetch_add(fee, Ordering::Relaxed);

        Ok(PaymentResult {
            payment_id: format!("atxp_pi_{}", Uuid::new_v4().simple()),
            protocol: "atxp".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Settled, // instant protocol-native settlement
            settlement_time: self.settlement_latency(),
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "mandate_id": token.token_id,
                "nested_depth": 0,
                "tool_discovered": false,
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
            refund_id: format!("atxp_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            processing_time: self.settlement_latency(),
        })
    }

    fn metrics(&self) -> ProtocolMetrics {
        ProtocolMetrics {
            protocol: "atxp".into(),
            total_transactions: self.txn_count.load(Ordering::Relaxed),
            successful_transactions: self.success_count.load(Ordering::Relaxed),
            failed_transactions: self.fail_count.load(Ordering::Relaxed),
            total_volume_cents: self.volume.load(Ordering::Relaxed),
            total_fees_cents: self.fees.load(Ordering::Relaxed),
            avg_settlement_ms: 150.0,          // protocol-native, very fast
            avg_authorization_ms: 200.0,        // mandate creation + validation
            micropayment_count: self.micropay_count.load(Ordering::Relaxed),
            refund_count: 0,
        }
    }

    /// ATXP fee: 0.5% (protocol-native, minimal intermediaries)
    fn fee_for(&self, amount: Cents) -> Cents {
        std::cmp::max(amount * 5 / 1000, 1) // 0.5%, minimum 1 cent
    }

    /// Protocol-native settlement: ~150ms
    fn settlement_latency(&self) -> Duration {
        Duration::from_millis(150)
    }

    fn supports_micropayments(&self) -> bool {
        true // designed for micropayments between agents
    }

    fn autonomy_level(&self) -> f64 {
        0.9 // mandate-bounded but supports nested agent-to-agent autonomy
    }
}
