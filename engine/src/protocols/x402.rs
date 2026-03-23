use async_trait::async_trait;
use k256::ecdsa::{signature::Signer, signature::Verifier, Signature, SigningKey, VerifyingKey};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use super::{timed_us, AuthToken, MetricsTracker, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult, SettlementResult};
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

/// x402 — real ECDSA signing and verification.
///
/// authorize() generates a secp256k1 keypair, signs a payment authorization.
/// pay() constructs the payment payload, signs it with ECDSA, then the "facilitator"
///   verifies the signature, validates the amount, and "settles" (marks complete).
/// All crypto is REAL — actual secp256k1 ECDSA sign + verify operations.
/// No mocked latency. Execution time is what the CPU actually takes.
pub struct X402Adapter {
    metrics: MetricsTracker,
    /// Signing key (simulates the agent's wallet key)
    signing_key: SigningKey,
    verifying_key: VerifyingKey,
}

impl X402Adapter {
    pub fn new() -> Self {
        let signing_key = SigningKey::random(&mut rand::thread_rng());
        let verifying_key = *signing_key.verifying_key();
        Self {
            metrics: MetricsTracker::new(),
            signing_key,
            verifying_key,
        }
    }

    /// Build the payment payload that gets signed (mirrors x402 spec)
    fn build_payment_payload(amount: Cents, merchant: &str, token_id: &str) -> Vec<u8> {
        let mut payload = Vec::new();
        payload.extend_from_slice(b"x402:exact:1:");
        payload.extend_from_slice(&amount.to_le_bytes());
        payload.extend_from_slice(b":");
        payload.extend_from_slice(merchant.as_bytes());
        payload.extend_from_slice(b":");
        payload.extend_from_slice(token_id.as_bytes());
        payload
    }

    /// Sign a payment payload with ECDSA secp256k1
    fn sign_payload(&self, payload: &[u8]) -> Signature {
        let digest = Sha256::digest(payload);
        self.signing_key.sign(&digest)
    }

    /// Verify a signed payment (facilitator role)
    fn verify_payment(&self, payload: &[u8], signature: &Signature) -> bool {
        let digest = Sha256::digest(payload);
        self.verifying_key.verify(&digest, signature).is_ok()
    }
}

#[async_trait]
impl ProtocolAdapter for X402Adapter {
    fn name(&self) -> &str { "x402" }

    async fn authorize(&self, _wallet: &AgentWallet, constraints: &SpendingConstraints) -> Result<AuthToken> {
        let (token, auth_us) = timed_us(|| {
            // Real work: generate authorization token with public key commitment
            let token_id = format!("x402_{}", Uuid::new_v4().simple());
            let pub_key_bytes = self.verifying_key.to_sec1_bytes();

            AuthToken {
                token_id,
                protocol: "x402".into(),
                max_amount: constraints.max_amount,
                currency: "usdc".into(),
                expires_at: constraints.expires_at,
                protocol_data: serde_json::json!({
                    "scheme": "exact",
                    "network": "base",
                    "asset": "USDC",
                    "public_key": base64::Engine::encode(&base64::engine::general_purpose::STANDARD, &pub_key_bytes),
                }),
            }
        });
        self.metrics.record_auth(auth_us);
        Ok(token)
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let (result, exec_us) = timed_us(|| -> Result<PaymentResult> {
            // 1. Check amount against pre-authorized max
            if amount > token.max_amount {
                return Err(EngineError::PaymentDeclined("amount exceeds authorization".into()));
            }

            // 2. Build payment payload (real x402 format)
            let payload = Self::build_payment_payload(amount, merchant, &token.token_id);

            // 3. REAL ECDSA sign (agent signs the payment)
            let signature = self.sign_payload(&payload);

            // 4. REAL ECDSA verify (facilitator verifies the signature)
            if !self.verify_payment(&payload, &signature) {
                return Err(EngineError::PaymentDeclined("signature verification failed".into()));
            }

            // 5. Facilitator "settles" on-chain (we record it as settled)
            let fee = self.fee_for(amount);
            let sig_bytes = signature.to_bytes();

            Ok(PaymentResult {
                payment_id: format!("x402_pi_{}", Uuid::new_v4().simple()),
                protocol: "x402".into(),
                amount,
                currency: "usdc".into(),
                status: PaymentStatus::Settled,
                execution_us: 0,
                fee,
                protocol_data: serde_json::json!({
                    "merchant": merchant,
                    "signature": base64::Engine::encode(&base64::engine::general_purpose::STANDARD, sig_bytes.as_slice()),
                    "payload_hash": format!("{:x}", Sha256::digest(&payload)),
                    "network": "base",
                    "verified": true,
                }),
            })
        });

        match result {
            Ok(mut payment) => {
                payment.execution_us = exec_us;
                self.metrics.record_success(payment.amount, payment.fee, exec_us, amount < 100);
                Ok(payment)
            }
            Err(e) => {
                self.metrics.record_failure(exec_us);
                Err(e)
            }
        }
    }

    async fn settle(&self, payment: &PaymentResult) -> Result<SettlementResult> {
        Ok(SettlementResult {
            payment_id: payment.payment_id.clone(), settled: true,
            execution_us: payment.execution_us, final_amount: payment.amount, fee: payment.fee,
        })
    }

    async fn refund(&self, payment: &PaymentResult, _reason: &str) -> Result<RefundResult> {
        let (mut r, exec_us) = timed_us(|| {
            self.metrics.refund_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            // Refund requires a new signed tx in reverse
            let payload = Self::build_payment_payload(payment.amount, "refund", &payment.payment_id);
            let _sig = self.sign_payload(&payload);
            RefundResult {
                refund_id: format!("x402_rf_{}", Uuid::new_v4().simple()),
                original_payment_id: payment.payment_id.clone(),
                amount: payment.amount, success: true, execution_us: 0,
            }
        });
        r.execution_us = exec_us;
        Ok(r)
    }

    fn metrics(&self) -> ProtocolMetrics { self.metrics.to_metrics("x402") }
    fn fee_for(&self, amount: Cents) -> Cents { std::cmp::max(amount / 1000, 1) }
    fn supports_micropayments(&self) -> bool { true }
    fn autonomy_level(&self) -> f64 { 1.0 }
}
