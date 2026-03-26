use async_trait::async_trait;
use k256::ecdsa::SigningKey;
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

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CheckoutItem {
    id: String,
    quantity: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BuyerInfo {
    email: String,
    #[serde(rename = "phone_number")]
    phone_number: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Address {
    name: String,
    address1: String,
    address2: Option<String>,
    city: String,
    state: Option<String>,
    #[serde(rename = "postal_code")]
    postal_code: Option<String>,
    country: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct FulfillmentMethod {
    #[serde(rename = "type")]
    method_type: String,
    #[serde(rename = "fulfillment_estimate")]
    fulfillment_estimate: Option<String>,
}

#[derive(Debug, Serialize)]
struct CheckoutSessionCreateRequest {
    items: Vec<CheckoutItem>,
    buyer: Option<BuyerInfo>,
    #[serde(rename = "fulfillment_address")]
    fulfillment_address: Option<Address>,
    #[serde(rename = "fulfillment_method")]
    fulfillment_method: Option<FulfillmentMethod>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CheckoutSessionResponse {
    id: String,
    status: String,
    #[serde(rename = "client_secret")]
    client_secret: Option<String>,
    #[serde(rename = "total_amount")]
    total_amount: Option<i64>,
    currency: Option<String>,
    #[serde(rename = "order_id")]
    order_id: Option<String>,
}

#[derive(Debug, Serialize)]
struct StripePaymentIntentRequest {
    amount: i64,
    currency: String,
    #[serde(rename = "payment_method_types")]
    payment_method_types: Vec<String>,
    #[serde(rename = "capture_method")]
    capture_method: String,
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

#[derive(Debug, Deserialize)]
struct ACPErrorResponse {
    code: String,
    message: String,
}

pub struct AcpAdapter {
    metrics: MetricsTracker,
    stripe_secret_key: String,
    checkout_sessions: Mutex<HashMap<String, CheckoutSessionRecord>>,
    payment_intents: Mutex<HashMap<String, PaymentIntentRecord>>,
    idempotency: Mutex<HashMap<String, String>>,
    http_client: reqwest::Client,
    signing_key: SigningKey,
    merchant_base_url: String,
}

#[derive(Debug, Clone)]
struct CheckoutSessionRecord {
    session_id: String,
    status: String,
    items: Vec<CheckoutItem>,
    total_amount: Cents,
    currency: String,
    stripe_pi_id: Option<String>,
}

#[derive(Debug, Clone)]
struct PaymentIntentRecord {
    amount: Cents,
    status: String,
    stripe_pi_id: String,
}

impl AcpAdapter {
    pub fn new(config: Config) -> Self {
        let signing_key = SigningKey::random(&mut rand::thread_rng());
        let merchant_base_url = std::env::var("ACP_MERCHANT_URL")
            .unwrap_or_else(|_| "https://merchant.example/agentic-commerce".to_string());

        Self {
            metrics: MetricsTracker::new(),
            stripe_secret_key: config.stripe.secret_key,
            checkout_sessions: Mutex::new(HashMap::new()),
            payment_intents: Mutex::new(HashMap::new()),
            idempotency: Mutex::new(HashMap::new()),
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default(),
            signing_key,
            merchant_base_url,
        }
    }

    fn wallet_address(&self) -> String {
        let verifying_key = self.signing_key.verifying_key();
        let pub_key = verifying_key.to_encoded_point(false);
        let hash = Sha256::digest(&pub_key.as_bytes()[1..]);
        let last_20 = &hash[hash.len() - 20..];
        format!("0x{}", hex::encode(last_20))
    }

    fn hash_scope(constraints: &SpendingConstraints) -> String {
        let mut hasher = Sha256::new();
        hasher.update(constraints.max_amount.to_le_bytes());
        hasher.update(constraints.currency.as_bytes());
        hasher.update(constraints.expires_at.to_rfc3339().as_bytes());
        if let Some(merchants) = &constraints.merchants {
            for m in merchants {
                hasher.update(m.as_bytes());
            }
        }
        format!("{:x}", hasher.finalize())
    }

    fn check_idempotency(&self, key: &str, body_hash: &str) -> std::result::Result<(), String> {
        let store = self.idempotency.lock().unwrap();
        if let Some(existing) = store.get(key) {
            if existing != body_hash {
                return Err("idempotency conflict".into());
            }
        }
        Ok(())
    }

    async fn create_checkout_session(
        &self,
        items: Vec<CheckoutItem>,
    ) -> Result<CheckoutSessionResponse> {
        let idempotency_key = format!("acp_cs_{}", Uuid::new_v4().simple());
        let body = CheckoutSessionCreateRequest {
            items,
            buyer: Some(BuyerInfo {
                email: format!("agent_{}@meridian.ai", Uuid::new_v4().simple()),
                phone_number: None,
            }),
            fulfillment_address: Some(Address {
                name: "Meridian Agent".to_string(),
                address1: "123 Agent St".to_string(),
                address2: None,
                city: "San Francisco".to_string(),
                state: Some("CA".to_string()),
                postal_code: Some("94102".to_string()),
                country: "US".to_string(),
            }),
            fulfillment_method: Some(FulfillmentMethod {
                method_type: "digital".to_string(),
                fulfillment_estimate: Some("2024-12-25T00:00:00Z".to_string()),
            }),
        };

        let url = format!("{}/checkout_sessions", self.merchant_base_url);

        let resp = self
            .http_client
            .post(&url)
            .header("Idempotency-Key", &idempotency_key)
            .header("Request-Id", format!("req_{}", Uuid::new_v4().simple()))
            .json(&body)
            .send()
            .await
            .map_err(|e| {
                EngineError::ExternalService(format!("ACP checkout session request failed: {}", e))
            })?;

        let status = resp.status();
        let error_body = resp.text().await.unwrap_or_default();

        if !status.is_success() {
            if let Ok(acp_err) = serde_json::from_str::<ACPErrorResponse>(&error_body) {
                return Err(EngineError::ExternalService(format!(
                    "ACP error: {} - {}",
                    acp_err.code, acp_err.message
                )));
            }
            return Err(EngineError::ExternalService(format!(
                "ACP checkout session returned: {} - {}",
                status, error_body
            )));
        }

        let session: CheckoutSessionResponse = serde_json::from_str(&error_body).map_err(|e| {
            EngineError::ExternalService(format!(
                "failed to parse checkout session response: {}",
                e
            ))
        })?;

        Ok(session)
    }

    async fn create_stripe_payment_intent(
        &self,
        amount: Cents,
        currency: &str,
        session_id: &str,
        merchant: &str,
    ) -> Result<String> {
        let idempotency_key = format!("acp_pi_{}_{}", session_id, Uuid::new_v4().simple());
        let mut metadata = HashMap::new();
        metadata.insert("session_id".to_string(), session_id.to_string());
        metadata.insert("merchant".to_string(), merchant.to_string());

        let request = StripePaymentIntentRequest {
            amount: amount as i64,
            currency: currency.to_string(),
            payment_method_types: vec!["card".to_string()],
            capture_method: "automatic".to_string(),
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
                "Stripe returned status: {} - {}",
                status, error_body
            )));
        }

        let pi: StripePaymentIntentResponse = serde_json::from_str(&error_body).map_err(|e| {
            EngineError::ExternalService(format!("failed to parse Stripe response: {}", e))
        })?;

        if pi.status == "requires_payment_method" || pi.status == "requires_confirmation" {
            return Err(EngineError::ExternalService(format!(
                "PaymentIntent not processable: {}",
                pi.status
            )));
        }

        Ok(pi.id)
    }

    async fn refund_stripe_payment_intent(&self, pi_id: &str, amount: Cents) -> Result<String> {
        let idempotency_key = format!("acp_refund_{}_{}", pi_id, Uuid::new_v4().simple());
        let params = [("payment_intent", pi_id), ("amount", &amount.to_string())];

        let resp = self
            .http_client
            .post("https://api.stripe.com/v1/refunds")
            .basic_auth(&self.stripe_secret_key, Option::<&str>::None)
            .header("Idempotency-Key", &idempotency_key)
            .form(&params)
            .send()
            .await
            .map_err(|e| EngineError::ExternalService(format!("Stripe refund failed: {}", e)))?;

        let status = resp.status();
        let error_body = resp.text().await.unwrap_or_default();

        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "Stripe refund error: {}",
                error_body
            )));
        }

        #[derive(Deserialize)]
        struct RefundResponse {
            id: String,
        }

        let refund: RefundResponse = serde_json::from_str(&error_body).map_err(|e| {
            EngineError::ExternalService(format!("failed to parse refund response: {}", e))
        })?;

        Ok(refund.id)
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
        let start = std::time::Instant::now();

        let scope_hash = Self::hash_scope(constraints);
        let session_id = format!("acp_cs_{}", Uuid::new_v4().simple());

        let wallet_addr = self.wallet_address();

        let token = AuthToken {
            token_id: session_id.clone(),
            protocol: "acp".into(),
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "type": "checkout_session",
                "scope_hash": scope_hash,
                "wallet_address": wallet_addr,
            }),
        };

        let auth_us = start.elapsed().as_micros() as u64;
        self.metrics.record_auth(auth_us);
        Ok(token)
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let start = std::time::Instant::now();

        let body_hash = {
            let mut h = Sha256::new();
            h.update(token.token_id.as_bytes());
            h.update(amount.to_le_bytes());
            h.update(merchant.as_bytes());
            format!("{:x}", h.finalize())
        };
        let idem_key = format!("pay_{}_{}", token.token_id, merchant);
        if let Err(e) = self.check_idempotency(&idem_key, &body_hash) {
            self.metrics
                .record_failure(start.elapsed().as_micros() as u64);
            return Err(EngineError::PaymentDeclined(e));
        }

        let items = vec![CheckoutItem {
            id: format!(
                "prod_{}",
                Uuid::new_v4().simple().to_string()[..8].to_string()
            ),
            quantity: 1,
        }];

        let session = self.create_checkout_session(items.clone()).await?;
        let checkout_session_id = session.id;

        let pi_id = self
            .create_stripe_payment_intent(amount, &token.currency, &checkout_session_id, merchant)
            .await?;

        {
            let mut sessions = self.checkout_sessions.lock().unwrap();
            sessions.insert(
                checkout_session_id.clone(),
                CheckoutSessionRecord {
                    session_id: checkout_session_id.clone(),
                    status: "processing".to_string(),
                    items,
                    total_amount: amount,
                    currency: token.currency.clone(),
                    stripe_pi_id: Some(pi_id.clone()),
                },
            );
        }

        let mut intents = self.payment_intents.lock().unwrap();
        intents.insert(
            pi_id.clone(),
            PaymentIntentRecord {
                amount,
                status: "completed".into(),
                stripe_pi_id: pi_id.clone(),
            },
        );

        self.idempotency.lock().unwrap().insert(idem_key, body_hash);

        let fee = self.fee_for(amount);
        let exec_us = start.elapsed().as_micros() as u64;

        let payment = PaymentResult {
            payment_id: pi_id,
            protocol: "acp".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Settled,
            execution_us: exec_us,
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "checkout_session_id": checkout_session_id,
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

        let refund_id = self
            .refund_stripe_payment_intent(&payment.payment_id, payment.amount)
            .await?;

        if let Some(pi) = self
            .payment_intents
            .lock()
            .unwrap()
            .get_mut(&payment.payment_id)
        {
            pi.status = "refunded".into();
        }

        Ok(RefundResult {
            refund_id,
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            execution_us: start.elapsed().as_micros() as u64,
        })
    }

    fn metrics(&self) -> ProtocolMetrics {
        self.metrics.to_metrics("acp")
    }
    fn fee_for(&self, amount: Cents) -> Cents {
        (amount * 29 / 1000) + 30
    }
    fn supports_micropayments(&self) -> bool {
        false
    }
    fn autonomy_level(&self) -> f64 {
        0.6
    }
}
