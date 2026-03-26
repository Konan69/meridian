use async_trait::async_trait;
use k256::ecdsa::{Signature, SigningKey, signature::Signer};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::Mutex;
use uuid::Uuid;

use super::{
    AuthToken, MetricsTracker, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult,
    SettlementResult,
};
use crate::config::Config;
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

#[derive(Debug, Serialize)]
struct StripePaymentIntentCreateRequest {
    amount: i64,
    currency: String,
    #[serde(rename = "capture_method")]
    capture_method: String,
    #[serde(rename = "payment_method_types")]
    payment_method_types: Vec<String>,
    confirmation: String,
    metadata: HashMap<String, String>,
}

#[derive(Debug, Serialize)]
struct StripePaymentIntentCaptureRequest {
    amount_to_capture: i64,
    metadata: HashMap<String, String>,
}

#[derive(Debug, Deserialize)]
struct StripePaymentIntentResponse {
    id: String,
    status: String,
}

#[derive(Debug, Deserialize)]
struct StripeErrorResponse {
    error: StripeErrorDetail,
}

#[derive(Debug, Deserialize)]
struct StripeErrorDetail {
    message: String,
}

pub struct MppAdapter {
    metrics: MetricsTracker,
    stripe_secret_key: String,
    signing_key: SigningKey,
    sessions: Mutex<HashMap<String, SessionRecord>>,
    http_client: reqwest::Client,
}

struct SessionRecord {
    budget: Cents,
    remaining_budget: Cents,
    total_spent: Cents,
    payment_count: u32,
    stripe_pi_id: String,
    stripe_pi_status: String,
    captured_amount: Cents,
    challenge: String,
}

impl MppAdapter {
    pub fn new(config: Config) -> Self {
        Self {
            metrics: MetricsTracker::new(),
            stripe_secret_key: config.stripe.secret_key,
            signing_key: SigningKey::random(&mut rand::thread_rng()),
            sessions: Mutex::new(HashMap::new()),
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default(),
        }
    }

    fn wallet_address(&self) -> String {
        let verifying_key = self.signing_key.verifying_key();
        let pub_key = verifying_key.to_encoded_point(false);
        let hash = Sha256::digest(&pub_key.as_bytes()[1..]);
        let last_20 = &hash[hash.len() - 20..];
        format!("0x{}", hex::encode(last_20))
    }

    async fn create_stripe_payment_intent(
        &self,
        amount: Cents,
        currency: &str,
        session_id: &str,
        merchant: &str,
    ) -> Result<String> {
        let idempotency_key = format!("mpp_pi_{}_{}", session_id, Uuid::new_v4().simple());
        let mut metadata = HashMap::new();
        metadata.insert("session_id".to_string(), session_id.to_string());
        metadata.insert("merchant".to_string(), merchant.to_string());
        metadata.insert("rail".to_string(), "tempo_usdc".to_string());

        let request = StripePaymentIntentCreateRequest {
            amount: amount as i64,
            currency: currency.to_string(),
            capture_method: "manual".to_string(),
            payment_method_types: vec!["card".to_string()],
            confirmation: "automatic".to_string(),
            metadata,
        };

        let resp = self
            .http_client
            .post("https://api.stripe.com/v1/payment_intents")
            .basic_auth(&self.stripe_secret_key, Option::<&str>::None)
            .header("Idempotency-Key", &idempotency_key)
            .form(&request)
            .send()
            .await
            .map_err(|e| EngineError::ExternalService(format!("Stripe request failed: {}", e)))?;

        let status = resp.status();
        let error_body = resp.text().await.unwrap_or_default();

        if !status.is_success() {
            if let Ok(stripe_err) = serde_json::from_str::<StripeErrorResponse>(&error_body) {
                return Err(EngineError::ExternalService(format!(
                    "Stripe error: {}",
                    stripe_err.error.message
                )));
            }
            return Err(EngineError::ExternalService(format!(
                "Stripe error: {}",
                status
            )));
        }

        let pi: StripePaymentIntentResponse = serde_json::from_str(&error_body).map_err(|e| {
            EngineError::ExternalService(format!("failed to parse response: {}", e))
        })?;

        Ok(pi.id)
    }

    async fn capture_stripe_payment(
        &self,
        pi_id: &str,
        amount: Cents,
        session_id: &str,
        merchant: &str,
    ) -> Result<()> {
        let idempotency_key = format!(
            "mpp_capture_{}_{}_{}",
            pi_id,
            amount,
            Uuid::new_v4().simple()
        );
        let mut metadata = HashMap::new();
        metadata.insert("session_id".to_string(), session_id.to_string());
        metadata.insert("merchant".to_string(), merchant.to_string());
        metadata.insert("captured_amount".to_string(), amount.to_string());

        let request = StripePaymentIntentCaptureRequest {
            amount_to_capture: amount as i64,
            metadata,
        };

        let resp = self
            .http_client
            .post(format!(
                "https://api.stripe.com/v1/payment_intents/{}/capture",
                pi_id
            ))
            .basic_auth(&self.stripe_secret_key, Option::<&str>::None)
            .header("Idempotency-Key", &idempotency_key)
            .form(&request)
            .send()
            .await
            .map_err(|e| EngineError::ExternalService(format!("Stripe capture failed: {}", e)))?;

        let status = resp.status();
        let error_body = resp.text().await.unwrap_or_default();

        if !status.is_success() {
            if let Ok(stripe_err) = serde_json::from_str::<StripeErrorResponse>(&error_body) {
                return Err(EngineError::ExternalService(format!(
                    "Stripe capture error: {}",
                    stripe_err.error.message
                )));
            }
            return Err(EngineError::ExternalService(format!(
                "Stripe capture error: {}",
                status
            )));
        }

        Ok(())
    }
}

#[async_trait]
impl ProtocolAdapter for MppAdapter {
    fn name(&self) -> &str {
        "mpp"
    }

    async fn authorize(
        &self,
        _wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        let start = std::time::Instant::now();
        let session_id = format!("mpp_session_{}", Uuid::new_v4().simple());

        let mut hasher = Sha256::new();
        hasher.update(session_id.as_bytes());
        hasher.update(constraints.max_amount.to_le_bytes());
        hasher.update(chrono::Utc::now().to_rfc3339().as_bytes());
        let challenge = format!("{:x}", hasher.finalize());

        let _challenge_sig: Signature = self.signing_key.sign(challenge.as_bytes());

        let merchant = constraints
            .merchants
            .as_ref()
            .and_then(|m| m.first().map(|s| s.as_str()))
            .unwrap_or("merchant");

        let pi_id = self
            .create_stripe_payment_intent(
                constraints.max_amount,
                &constraints.currency,
                &session_id,
                merchant,
            )
            .await?;

        {
            let mut sessions = self.sessions.lock().unwrap();
            sessions.insert(
                session_id.clone(),
                SessionRecord {
                    budget: constraints.max_amount,
                    remaining_budget: constraints.max_amount,
                    total_spent: 0,
                    payment_count: 0,
                    stripe_pi_id: pi_id.clone(),
                    stripe_pi_status: "requires_capture".to_string(),
                    captured_amount: 0,
                    challenge: challenge.clone(),
                },
            );
        }

        let token = AuthToken {
            token_id: session_id,
            protocol: "mpp".into(),
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "session_type": "streaming",
                "capture_method": "manual",
                "challenge": challenge,
                "rail": "tempo_usdc",
                "wallet_address": self.wallet_address(),
                "stripe_pi_id": pi_id,
            }),
        };

        let auth_us = start.elapsed().as_micros() as u64;
        self.metrics.record_auth(auth_us);
        Ok(token)
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let start = std::time::Instant::now();

        let stripe_pi_id = {
            let mut sessions = self.sessions.lock().unwrap();
            let session = sessions
                .get_mut(&token.token_id)
                .ok_or_else(|| EngineError::PaymentDeclined("session not found".into()))?;

            if amount > session.remaining_budget {
                return Err(EngineError::PaymentDeclined(format!(
                    "amount {} exceeds session remaining budget {}",
                    amount, session.remaining_budget
                )));
            }

            session.remaining_budget -= amount;
            session.total_spent += amount;
            session.payment_count += 1;
            session.captured_amount += amount;

            session.stripe_pi_id.clone()
        };

        self.capture_stripe_payment(&stripe_pi_id, amount, &token.token_id, merchant)
            .await?;

        {
            let mut sessions = self.sessions.lock().unwrap();
            if let Some(session) = sessions.get_mut(&token.token_id) {
                session.stripe_pi_status = "partially_captured".to_string();
            }
        }

        let mut receipt = Vec::new();
        receipt.extend_from_slice(b"mpp:receipt:");
        receipt.extend_from_slice(&amount.to_le_bytes());
        receipt.extend_from_slice(merchant.as_bytes());
        receipt.extend_from_slice(token.token_id.as_bytes());
        receipt.extend_from_slice(stripe_pi_id.as_bytes());
        let receipt_hash = Sha256::digest(&receipt);
        let _receipt_sig: Signature = self.signing_key.sign(&receipt_hash);

        let fee = self.fee_for(amount);
        let exec_us = start.elapsed().as_micros() as u64;

        let payment = PaymentResult {
            payment_id: format!("mpp_pay_{}", Uuid::new_v4().simple()),
            protocol: "mpp".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Settled,
            execution_us: exec_us,
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "session_id": token.token_id,
                "stripe_pi_id": stripe_pi_id,
                "receipt_hash": format!("{:x}", receipt_hash),
                "wallet_address": self.wallet_address(),
            }),
        };

        self.metrics
            .record_success(payment.amount, payment.fee, exec_us, amount < 100);
        Ok(payment)
    }

    async fn settle(&self, payment: &PaymentResult) -> Result<SettlementResult> {
        Ok(SettlementResult {
            payment_id: payment.payment_id.clone(),
            settled: payment.status == PaymentStatus::Settled,
            execution_us: payment.execution_us,
            final_amount: payment.amount,
            fee: payment.fee,
        })
    }

    async fn refund(&self, payment: &PaymentResult, _reason: &str) -> Result<RefundResult> {
        let start = std::time::Instant::now();
        self.metrics
            .refund_count
            .fetch_add(1, std::sync::atomic::Ordering::Relaxed);

        let session_id = payment
            .protocol_data
            .get("session_id")
            .and_then(|v| v.as_str())
            .map(String::from);

        let refunded = if let Some(ref sid) = session_id {
            let mut sessions = self.sessions.lock().unwrap();
            if let Some(session) = sessions.get_mut(sid) {
                session.remaining_budget += payment.amount;
                session.total_spent = session.total_spent.saturating_sub(payment.amount);
                session.payment_count = session.payment_count.saturating_sub(1);
                session.captured_amount = session.captured_amount.saturating_sub(payment.amount);
                true
            } else {
                false
            }
        } else {
            false
        };

        Ok(RefundResult {
            refund_id: format!("mpp_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: refunded,
            execution_us: start.elapsed().as_micros() as u64,
        })
    }

    fn metrics(&self) -> ProtocolMetrics {
        self.metrics.to_metrics("mpp")
    }
    fn fee_for(&self, amount: Cents) -> Cents {
        std::cmp::max((amount * 15 / 1000) + 5, 1)
    }
    fn supports_micropayments(&self) -> bool {
        true
    }
    fn autonomy_level(&self) -> f64 {
        0.8
    }
}
