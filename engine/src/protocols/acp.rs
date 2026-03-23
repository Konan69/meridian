use async_trait::async_trait;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use uuid::Uuid;

use super::{AuthToken, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult, SettlementResult};
use crate::core::error::Result;
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// ACP (Agentic Commerce Protocol) — OpenAI + Stripe
///
/// Uses Shared Payment Tokens (SPTs) scoped to merchant/amount/time.
/// Settlement via card networks. BNPL supported.
/// Highest merchant adoption. No micropayments.
pub struct AcpAdapter {
    txn_count: AtomicU64,
    success_count: AtomicU64,
    fail_count: AtomicU64,
    volume: AtomicU64,
    fees: AtomicU64,
}

impl AcpAdapter {
    pub fn new() -> Self {
        Self {
            txn_count: AtomicU64::new(0),
            success_count: AtomicU64::new(0),
            fail_count: AtomicU64::new(0),
            volume: AtomicU64::new(0),
            fees: AtomicU64::new(0),
        }
    }
}

#[async_trait]
impl ProtocolAdapter for AcpAdapter {
    fn name(&self) -> &str {
        "acp"
    }

    async fn authorize(
        &self,
        _wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        // ACP authorization: mint an SPT scoped to constraints
        let token_id = format!("spt_{}", Uuid::new_v4().simple());
        Ok(AuthToken {
            token_id,
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
                "amount exceeds SPT allowance".into(),
            ));
        }

        let fee = self.fee_for(amount);
        self.success_count.fetch_add(1, Ordering::Relaxed);
        self.volume.fetch_add(amount, Ordering::Relaxed);
        self.fees.fetch_add(fee, Ordering::Relaxed);

        Ok(PaymentResult {
            payment_id: format!("pi_{}", Uuid::new_v4().simple()),
            protocol: "acp".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Pending,
            settlement_time: self.settlement_latency(),
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "spt_id": token.token_id,
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
            refund_id: format!("rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            processing_time: Duration::from_millis(2000),
        })
    }

    fn metrics(&self) -> ProtocolMetrics {
        ProtocolMetrics {
            protocol: "acp".into(),
            total_transactions: self.txn_count.load(Ordering::Relaxed),
            successful_transactions: self.success_count.load(Ordering::Relaxed),
            failed_transactions: self.fail_count.load(Ordering::Relaxed),
            total_volume_cents: self.volume.load(Ordering::Relaxed),
            total_fees_cents: self.fees.load(Ordering::Relaxed),
            avg_settlement_ms: 2000.0,        // card network batch settlement
            avg_authorization_ms: 150.0,       // SPT creation
            micropayment_count: 0,
            refund_count: 0,
        }
    }

    /// ACP fee: 2.9% + 30¢ (Stripe's standard rate)
    fn fee_for(&self, amount: Cents) -> Cents {
        (amount * 29 / 1000) + 30
    }

    /// Card network settlement: ~2 seconds simulated (real: 1-2 business days)
    fn settlement_latency(&self) -> Duration {
        Duration::from_millis(2000)
    }

    fn supports_micropayments(&self) -> bool {
        false // 30¢ minimum fee makes micropayments impractical
    }

    fn autonomy_level(&self) -> f64 {
        0.6 // SPT-bounded, human sets constraints, agent executes within
    }
}
