use async_trait::async_trait;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use uuid::Uuid;

use super::{AuthToken, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult, SettlementResult};
use crate::core::error::Result;
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// AP2 (Agent Payments Protocol) — Google
///
/// Verifiable Digital Credentials (VDCs) with Intent/Cart Mandates.
/// Cryptographic proof of authorization. Multi-rail (cards, crypto, bank transfers).
/// Strongest trust model — non-repudiable authorization chain.
/// Higher latency due to VDC signing ceremony.
pub struct Ap2Adapter {
    txn_count: AtomicU64,
    success_count: AtomicU64,
    fail_count: AtomicU64,
    volume: AtomicU64,
    fees: AtomicU64,
}

impl Ap2Adapter {
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
impl ProtocolAdapter for Ap2Adapter {
    fn name(&self) -> &str {
        "ap2"
    }

    async fn authorize(
        &self,
        _wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        let mandate_type = if constraints.requires_confirmation {
            "cart_mandate"
        } else {
            "intent_mandate"
        };

        let token_id = format!("ap2_{}", Uuid::new_v4().simple());
        Ok(AuthToken {
            token_id,
            protocol: "ap2".into(),
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "mandate_type": mandate_type,
                "vdc_signed": true,
                "merchants": constraints.merchants,
                "categories": constraints.categories,
                "user_cart_confirmation_required": constraints.requires_confirmation,
                // Simulated SD-JWT-VC
                "authorization_jwt": format!("eyJ0eXAiOiJ2YytzZC1qd3QiLCJhbGciOiJFUzI1NksifQ.{}", Uuid::new_v4().simple()),
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
                "amount exceeds mandate allowance".into(),
            ));
        }

        let fee = self.fee_for(amount);
        self.success_count.fetch_add(1, Ordering::Relaxed);
        self.volume.fetch_add(amount, Ordering::Relaxed);
        self.fees.fetch_add(fee, Ordering::Relaxed);

        Ok(PaymentResult {
            payment_id: format!("ap2_pi_{}", Uuid::new_v4().simple()),
            protocol: "ap2".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Pending,
            settlement_time: self.settlement_latency(),
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "mandate_id": token.token_id,
                "vdc_verified": true,
                "payment_method": "tokenized_card",
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
            refund_id: format!("ap2_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            processing_time: Duration::from_millis(3000),
        })
    }

    fn metrics(&self) -> ProtocolMetrics {
        ProtocolMetrics {
            protocol: "ap2".into(),
            total_transactions: self.txn_count.load(Ordering::Relaxed),
            successful_transactions: self.success_count.load(Ordering::Relaxed),
            failed_transactions: self.fail_count.load(Ordering::Relaxed),
            total_volume_cents: self.volume.load(Ordering::Relaxed),
            total_fees_cents: self.fees.load(Ordering::Relaxed),
            avg_settlement_ms: 3000.0,        // VDC verification + card settlement
            avg_authorization_ms: 500.0,       // VDC signing ceremony
            micropayment_count: 0,
            refund_count: 0,
        }
    }

    /// AP2 fee: 2.5% (slightly lower than ACP — multi-rail flexibility)
    fn fee_for(&self, amount: Cents) -> Cents {
        (amount * 25 / 1000) + 20
    }

    /// VDC verification + payment network: ~3 seconds
    fn settlement_latency(&self) -> Duration {
        Duration::from_millis(3000)
    }

    fn supports_micropayments(&self) -> bool {
        false // designed for e-commerce transactions, not API calls
    }

    fn autonomy_level(&self) -> f64 {
        0.5 // Intent Mandate = 0.7, Cart Mandate = 0.3, average ~0.5
    }
}
