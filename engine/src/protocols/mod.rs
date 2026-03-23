pub mod acp;
pub mod ap2;
pub mod atxp;
pub mod mpp;
pub mod x402;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
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
    /// Protocol-specific data (SPT details, mandate JWT, x402 signed payload, etc.)
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
    pub settlement_time: Duration,
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
// Settlement result
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SettlementResult {
    pub payment_id: String,
    pub settled: bool,
    pub settlement_time: Duration,
    pub final_amount: Cents,
    pub fee: Cents,
}

// ---------------------------------------------------------------------------
// Refund result
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RefundResult {
    pub refund_id: String,
    pub original_payment_id: String,
    pub amount: Cents,
    pub success: bool,
    pub processing_time: Duration,
}

// ---------------------------------------------------------------------------
// The trait — every protocol implements this
// ---------------------------------------------------------------------------

#[async_trait]
pub trait ProtocolAdapter: Send + Sync {
    /// Human-readable protocol name (e.g., "acp", "x402", "ap2", "mpp", "atxp")
    fn name(&self) -> &str;

    /// Authorize an agent to spend up to a constrained amount.
    /// ACP: creates an SPT. AP2: creates an IntentMandate + VDC.
    /// x402: pre-signs a payment payload. MPP: opens a session.
    /// ATXP: creates a mandate with constraints.
    async fn authorize(
        &self,
        wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken>;

    /// Execute a payment against a previously authorized token.
    async fn pay(
        &self,
        token: &AuthToken,
        amount: Cents,
        merchant: &str,
    ) -> Result<PaymentResult>;

    /// Settle a pending payment (may be instant for x402, delayed for ACP).
    async fn settle(&self, payment: &PaymentResult) -> Result<SettlementResult>;

    /// Refund a completed payment.
    async fn refund(&self, payment: &PaymentResult, reason: &str) -> Result<RefundResult>;

    /// Get cumulative metrics for this protocol.
    fn metrics(&self) -> ProtocolMetrics;

    /// Simulated fee for a transaction of this amount (in cents).
    fn fee_for(&self, amount: Cents) -> Cents;

    /// Simulated settlement latency.
    fn settlement_latency(&self) -> Duration;

    /// Whether this protocol supports micropayments (< $1).
    fn supports_micropayments(&self) -> bool;

    /// Maximum agent autonomy level (0.0 = fully manual, 1.0 = fully autonomous).
    fn autonomy_level(&self) -> f64;
}
