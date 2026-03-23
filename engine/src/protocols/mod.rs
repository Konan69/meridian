pub mod acp;
pub mod ap2;
pub mod atxp;
pub mod mpp;
pub mod x402;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

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
    /// REAL measured execution time in microseconds
    pub execution_us: u64,
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SettlementResult {
    pub payment_id: String,
    pub settled: bool,
    pub execution_us: u64,
    pub final_amount: Cents,
    pub fee: Cents,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RefundResult {
    pub refund_id: String,
    pub original_payment_id: String,
    pub amount: Cents,
    pub success: bool,
    pub execution_us: u64,
}

// ---------------------------------------------------------------------------
// Metrics tracker — records REAL measured timings
// ---------------------------------------------------------------------------

pub struct MetricsTracker {
    pub txn_count: AtomicU64,
    pub success_count: AtomicU64,
    pub fail_count: AtomicU64,
    pub volume: AtomicU64,
    pub fees: AtomicU64,
    pub micropay_count: AtomicU64,
    pub refund_count: AtomicU64,
    /// Sum of REAL execution times in microseconds
    pub total_exec_us: AtomicU64,
    pub total_auth_us: AtomicU64,
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
            total_exec_us: AtomicU64::new(0),
            total_auth_us: AtomicU64::new(0),
        }
    }

    pub fn record_success(&self, amount: Cents, fee: Cents, exec_us: u64, is_micro: bool) {
        self.txn_count.fetch_add(1, Ordering::Relaxed);
        self.success_count.fetch_add(1, Ordering::Relaxed);
        self.volume.fetch_add(amount, Ordering::Relaxed);
        self.fees.fetch_add(fee, Ordering::Relaxed);
        self.total_exec_us.fetch_add(exec_us, Ordering::Relaxed);
        if is_micro { self.micropay_count.fetch_add(1, Ordering::Relaxed); }
    }

    pub fn record_failure(&self, exec_us: u64) {
        self.txn_count.fetch_add(1, Ordering::Relaxed);
        self.fail_count.fetch_add(1, Ordering::Relaxed);
        self.total_exec_us.fetch_add(exec_us, Ordering::Relaxed);
    }

    pub fn record_auth(&self, auth_us: u64) {
        self.total_auth_us.fetch_add(auth_us, Ordering::Relaxed);
    }

    pub fn to_metrics(&self, protocol: &str) -> ProtocolMetrics {
        let success = self.success_count.load(Ordering::Relaxed);
        let total = self.txn_count.load(Ordering::Relaxed);
        let avg_exec = if total > 0 {
            self.total_exec_us.load(Ordering::Relaxed) as f64 / total as f64 / 1000.0
        } else { 0.0 };
        let avg_auth = if success > 0 {
            self.total_auth_us.load(Ordering::Relaxed) as f64 / success as f64 / 1000.0
        } else { 0.0 };

        ProtocolMetrics {
            protocol: protocol.into(),
            total_transactions: total,
            successful_transactions: success,
            failed_transactions: self.fail_count.load(Ordering::Relaxed),
            total_volume_cents: self.volume.load(Ordering::Relaxed),
            total_fees_cents: self.fees.load(Ordering::Relaxed),
            avg_settlement_ms: avg_exec,
            avg_authorization_ms: avg_auth,
            micropayment_count: self.micropay_count.load(Ordering::Relaxed),
            refund_count: self.refund_count.load(Ordering::Relaxed),
        }
    }
}

/// Measure execution time of a closure in microseconds
pub fn timed_us<F, R>(f: F) -> (R, u64)
where F: FnOnce() -> R {
    let start = Instant::now();
    let result = f();
    let elapsed = start.elapsed().as_micros() as u64;
    (result, elapsed)
}

// ---------------------------------------------------------------------------
// The trait
// ---------------------------------------------------------------------------

#[async_trait]
pub trait ProtocolAdapter: Send + Sync {
    fn name(&self) -> &str;
    async fn authorize(&self, wallet: &AgentWallet, constraints: &SpendingConstraints) -> Result<AuthToken>;
    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult>;
    async fn settle(&self, payment: &PaymentResult) -> Result<SettlementResult>;
    async fn refund(&self, payment: &PaymentResult, reason: &str) -> Result<RefundResult>;
    fn metrics(&self) -> ProtocolMetrics;
    fn fee_for(&self, amount: Cents) -> Cents;
    fn supports_micropayments(&self) -> bool;
    fn autonomy_level(&self) -> f64;
}
