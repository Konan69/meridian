use async_trait::async_trait;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use uuid::Uuid;

use super::{AuthToken, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult, SettlementResult};
use crate::core::error::Result;
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// x402 — Coinbase
///
/// Stateless HTTP 402 payments. USDC on-chain.
/// Per-request: server returns 402, client signs, facilitator settles.
/// Micropayments down to $0.001. Near-instant settlement.
/// Highest agent autonomy — no sessions, no human approval per tx.
pub struct X402Adapter {
    txn_count: AtomicU64,
    success_count: AtomicU64,
    fail_count: AtomicU64,
    volume: AtomicU64,
    fees: AtomicU64,
    micropay_count: AtomicU64,
}

impl X402Adapter {
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
impl ProtocolAdapter for X402Adapter {
    fn name(&self) -> &str {
        "x402"
    }

    async fn authorize(
        &self,
        _wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        // x402: pre-sign a payment payload. Stateless — no server-side session.
        let token_id = format!("x402_{}", Uuid::new_v4().simple());
        Ok(AuthToken {
            token_id,
            protocol: "x402".into(),
            max_amount: constraints.max_amount,
            currency: "usdc".into(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "scheme": "exact",
                "network": "base",
                "asset": "USDC",
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
                "amount exceeds pre-signed payload".into(),
            ));
        }

        if amount < 100 {
            // < $1.00 = micropayment
            self.micropay_count.fetch_add(1, Ordering::Relaxed);
        }

        let fee = self.fee_for(amount);
        self.success_count.fetch_add(1, Ordering::Relaxed);
        self.volume.fetch_add(amount, Ordering::Relaxed);
        self.fees.fetch_add(fee, Ordering::Relaxed);

        // x402 settles on-chain immediately via facilitator
        Ok(PaymentResult {
            payment_id: format!("x402_pi_{}", Uuid::new_v4().simple()),
            protocol: "x402".into(),
            amount,
            currency: "usdc".into(),
            status: PaymentStatus::Settled, // instant settlement
            settlement_time: self.settlement_latency(),
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
        // Already settled on-chain at pay() time
        Ok(SettlementResult {
            payment_id: payment.payment_id.clone(),
            settled: true,
            settlement_time: self.settlement_latency(),
            final_amount: payment.amount,
            fee: payment.fee,
        })
    }

    async fn refund(&self, payment: &PaymentResult, _reason: &str) -> Result<RefundResult> {
        // On-chain refund: new tx in reverse direction
        Ok(RefundResult {
            refund_id: format!("x402_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            processing_time: self.settlement_latency(),
        })
    }

    fn metrics(&self) -> ProtocolMetrics {
        let total = self.txn_count.load(Ordering::Relaxed);
        let success = self.success_count.load(Ordering::Relaxed);
        ProtocolMetrics {
            protocol: "x402".into(),
            total_transactions: total,
            successful_transactions: success,
            failed_transactions: self.fail_count.load(Ordering::Relaxed),
            total_volume_cents: self.volume.load(Ordering::Relaxed),
            total_fees_cents: self.fees.load(Ordering::Relaxed),
            avg_settlement_ms: 200.0,         // on-chain finality ~200ms on Base
            avg_authorization_ms: 50.0,        // just signing, no server round-trip
            micropayment_count: self.micropay_count.load(Ordering::Relaxed),
            refund_count: 0,
        }
    }

    /// x402 fee: ~0.1% (Base L2 gas, negligible)
    fn fee_for(&self, amount: Cents) -> Cents {
        std::cmp::max(amount / 1000, 1) // 0.1%, minimum 1 cent
    }

    /// Base L2 finality: ~200ms
    fn settlement_latency(&self) -> Duration {
        Duration::from_millis(200)
    }

    fn supports_micropayments(&self) -> bool {
        true // down to $0.001
    }

    fn autonomy_level(&self) -> f64 {
        1.0 // fully autonomous — agent signs, chain settles, no human in loop
    }
}
