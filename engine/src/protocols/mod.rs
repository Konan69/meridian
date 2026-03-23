pub mod acp;
pub mod ap2;
pub mod atxp;
pub mod mpp;
pub mod x402;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use crate::core::error::Result;
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

// ---------------------------------------------------------------------------
// Auth token — returned by authorize(), consumed by pay()
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthToken {
    pub token_id: String,
    pub protocol: String,
    pub max_amount: Cents,
    pub currency: String,
    pub expires_at: chrono::DateTime<chrono::Utc>,
    pub protocol_data: serde_json::Value,
}

// ---------------------------------------------------------------------------
// Payment result — returned by pay()
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PaymentResult {
    pub payment_id: String,
    pub protocol: String,
    pub amount: Cents,
    pub currency: String,
    pub status: PaymentStatus,
    pub settlement_time_ms: u64,
    pub fee: Cents,
    pub protocol_data: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PaymentStatus {
    Pending,
    Settled,
    Failed,
    Refunded,
}

// ---------------------------------------------------------------------------
// Settlement / Refund results
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SettlementResult {
    pub payment_id: String,
    pub settled: bool,
    pub settlement_time_ms: u64,
    pub final_amount: Cents,
    pub fee: Cents,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RefundResult {
    pub refund_id: String,
    pub original_payment_id: String,
    pub amount: Cents,
    pub success: bool,
    pub processing_time: Duration,
}

// ---------------------------------------------------------------------------
// Shared metrics tracker with running averages
// ---------------------------------------------------------------------------

pub struct MetricsTracker {
    pub txn_count: AtomicU64,
    pub success_count: AtomicU64,
    pub fail_count: AtomicU64,
    pub volume: AtomicU64,
    pub fees: AtomicU64,
    pub micropay_count: AtomicU64,
    pub refund_count: AtomicU64,
    /// Sum of all settlement times in ms (divide by success_count for average)
    pub total_settlement_ms: AtomicU64,
    /// Sum of all auth times in ms
    pub total_auth_ms: AtomicU64,
}

impl MetricsTracker {
    pub fn new() -> Self {
        Self {
            txn_count: AtomicU64::new(0),
            success_count: AtomicU64::new(0),
            fail_count: AtomicU64::new(0),
            volume: AtomicU64::new(0),
            fees: AtomicU64::new(0),
            micropay_count: AtomicU64::new(0),
            refund_count: AtomicU64::new(0),
            total_settlement_ms: AtomicU64::new(0),
            total_auth_ms: AtomicU64::new(0),
        }
    }

    pub fn record_success(&self, amount: Cents, fee: Cents, settlement_ms: u64, is_micropayment: bool) {
        self.txn_count.fetch_add(1, Ordering::Relaxed);
        self.success_count.fetch_add(1, Ordering::Relaxed);
        self.volume.fetch_add(amount, Ordering::Relaxed);
        self.fees.fetch_add(fee, Ordering::Relaxed);
        self.total_settlement_ms.fetch_add(settlement_ms, Ordering::Relaxed);
        if is_micropayment {
            self.micropay_count.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn record_failure(&self) {
        self.txn_count.fetch_add(1, Ordering::Relaxed);
        self.fail_count.fetch_add(1, Ordering::Relaxed);
    }

    pub fn avg_settlement_ms(&self) -> f64 {
        let success = self.success_count.load(Ordering::Relaxed);
        if success == 0 {
            return 0.0;
        }
        self.total_settlement_ms.load(Ordering::Relaxed) as f64 / success as f64
    }

    pub fn to_metrics(&self, protocol: &str, base_auth_ms: f64) -> ProtocolMetrics {
        ProtocolMetrics {
            protocol: protocol.into(),
            total_transactions: self.txn_count.load(Ordering::Relaxed),
            successful_transactions: self.success_count.load(Ordering::Relaxed),
            failed_transactions: self.fail_count.load(Ordering::Relaxed),
            total_volume_cents: self.volume.load(Ordering::Relaxed),
            total_fees_cents: self.fees.load(Ordering::Relaxed),
            avg_settlement_ms: self.avg_settlement_ms(),
            avg_authorization_ms: base_auth_ms,
            micropayment_count: self.micropay_count.load(Ordering::Relaxed),
            refund_count: self.refund_count.load(Ordering::Relaxed),
        }
    }
}

// ---------------------------------------------------------------------------
// Jittered latency — adds realistic variance
// ---------------------------------------------------------------------------

/// Add gaussian-like jitter to a base latency. Returns ms.
/// Uses a simple triangle distribution (sum of 2 uniform randoms) for speed.
pub fn jittered_ms(base_ms: u64, jitter_pct: f64) -> u64 {
    let jitter_range = (base_ms as f64 * jitter_pct) as i64;
    if jitter_range == 0 {
        return base_ms;
    }
    // Triangle distribution: sum of two uniform randoms, centered on base
    let r1 = rand_u64() % (jitter_range as u64 * 2);
    let r2 = rand_u64() % (jitter_range as u64 * 2);
    let offset = (r1 as i64 + r2 as i64) / 2 - jitter_range;
    (base_ms as i64 + offset).max(1) as u64
}

/// Simple fast pseudo-random using thread-local state
fn rand_u64() -> u64 {
    use std::cell::Cell;
    thread_local! {
        static STATE: Cell<u64> = Cell::new(0x12345678_9abcdef0);
    }
    STATE.with(|s| {
        let mut x = s.get();
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        s.set(x);
        x
    })
}

/// Simulate a failure based on a failure rate (0.0 to 1.0)
pub fn should_fail(failure_rate: f64) -> bool {
    if failure_rate <= 0.0 {
        return false;
    }
    (rand_u64() % 10000) < (failure_rate * 10000.0) as u64
}

// ---------------------------------------------------------------------------
// The trait — every protocol implements this
// ---------------------------------------------------------------------------

#[async_trait]
pub trait ProtocolAdapter: Send + Sync {
    fn name(&self) -> &str;

    async fn authorize(
        &self,
        wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken>;

    async fn pay(
        &self,
        token: &AuthToken,
        amount: Cents,
        merchant: &str,
    ) -> Result<PaymentResult>;

    async fn settle(&self, payment: &PaymentResult) -> Result<SettlementResult>;

    async fn refund(&self, payment: &PaymentResult, reason: &str) -> Result<RefundResult>;

    fn metrics(&self) -> ProtocolMetrics;

    fn fee_for(&self, amount: Cents) -> Cents;

    fn settlement_latency_ms(&self) -> u64;

    fn supports_micropayments(&self) -> bool;

    fn autonomy_level(&self) -> f64;

    /// Protocol-specific failure rate (0.0 to 1.0)
    fn failure_rate(&self) -> f64;
}
