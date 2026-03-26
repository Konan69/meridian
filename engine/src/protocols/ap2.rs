use async_trait::async_trait;
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use hmac::{Hmac, Mac};
use k256::ecdsa::{Signature, SigningKey, VerifyingKey, signature::Signer, signature::Verifier};
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

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct IntentMandate {
    #[serde(rename = "userCartConfirmationRequired")]
    user_cart_confirmation_required: bool,
    #[serde(rename = "naturalLanguageDescription")]
    natural_language_description: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    merchants: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    skus: Option<Vec<String>>,
    #[serde(rename = "requiresRefundability")]
    requires_refundability: bool,
    #[serde(rename = "intentExpiry")]
    intent_expiry: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CartContents {
    id: String,
    #[serde(rename = "userCartConfirmationRequired")]
    user_cart_confirmation_required: bool,
    #[serde(rename = "paymentRequest")]
    payment_request: PaymentRequest,
    #[serde(rename = "cartExpiry")]
    cart_expiry: String,
    #[serde(rename = "merchantName")]
    merchant_name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PaymentRequest {
    total: PaymentItem,
    items: Vec<PaymentItem>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PaymentItem {
    id: String,
    label: String,
    amount: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CartMandate {
    contents: CartContents,
    #[serde(rename = "merchantAuthorization")]
    merchant_authorization: Option<String>,
}

pub struct Ap2Adapter {
    metrics: MetricsTracker,
    http_client: reqwest::Client,
    rpc_url: String,
    master_seed: String,
    mandates: Mutex<HashMap<String, MandateRecord>>,
}

#[derive(Debug, Clone)]
struct MandateRecord {
    mandate_type: String,
    max_amount: Cents,
    constraint_hash: String,
    issuer_sig: Vec<u8>,
    user_sig: Vec<u8>,
    consumed: bool,
}

impl Ap2Adapter {
    pub fn new(config: Config) -> Self {
        Self {
            metrics: MetricsTracker::new(),
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default(),
            rpc_url: config.ap2.rpc_url.clone(),
            master_seed: config.ap2.master_seed.clone(),
            mandates: Mutex::new(HashMap::new()),
        }
    }

    fn derive_issuer_key(&self, agent_id: &str) -> SigningKey {
        let mut mac = HmacSha256::new_from_slice(self.master_seed.as_bytes())
            .expect("HMAC can take key of any size");
        mac.update(format!("ap2:issuer:{}", agent_id).as_bytes());
        let result = mac.finalize();
        let bytes = result.into_bytes();
        SigningKey::from_slice(&bytes[..32])
            .unwrap_or_else(|_| SigningKey::random(&mut rand::thread_rng()))
    }

    fn derive_user_key(&self, agent_id: &str) -> SigningKey {
        let mut mac = HmacSha256::new_from_slice(self.master_seed.as_bytes())
            .expect("HMAC can take key of any size");
        mac.update(format!("ap2:user:{}", agent_id).as_bytes());
        let result = mac.finalize();
        let bytes = result.into_bytes();
        SigningKey::from_slice(&bytes[..32])
            .unwrap_or_else(|_| SigningKey::random(&mut rand::thread_rng()))
    }

    fn wallet_address(&self, agent_id: &str) -> String {
        let user_key = self.derive_user_key(agent_id);
        let verifying_key = user_key.verifying_key();
        let pub_key = verifying_key.to_encoded_point(false);
        let hash = Sha256::digest(&pub_key.as_bytes()[1..]);
        let last_20 = &hash[hash.len() - 20..];
        format!("0x{}", hex::encode(last_20))
    }

    fn create_intent_mandate(
        constraints: &SpendingConstraints,
        merchant: Option<&str>,
    ) -> IntentMandate {
        let merchants = merchant.map(|m| vec![m.to_string()]);
        IntentMandate {
            user_cart_confirmation_required: constraints.requires_confirmation,
            natural_language_description: format!(
                "Agent purchasing up to {} {}",
                constraints.max_amount, constraints.currency
            ),
            merchants,
            skus: None,
            requires_refundability: false,
            intent_expiry: constraints.expires_at.to_rfc3339(),
        }
    }

    fn sign_jwt_merchant_auth(&self, agent_id: &str, payload: &[u8]) -> String {
        let issuer_key = self.derive_issuer_key(agent_id);
        let header = serde_json::json!({
            "alg": "ES256K",
            "typ": "JWT",
            "kid": format!("ap2-key-{}", &agent_id[..8])
        });

        let header_b64 = URL_SAFE_NO_PAD.encode(serde_json::to_vec(&header).unwrap());
        let payload_b64 = URL_SAFE_NO_PAD.encode(payload);

        let mut signing_input = String::new();
        signing_input.push_str(&header_b64);
        signing_input.push('.');
        signing_input.push_str(&payload_b64);

        let digest = Sha256::digest(signing_input.as_bytes());
        let sig: Signature = issuer_key.sign(&digest);
        let sig_b64 = URL_SAFE_NO_PAD.encode(sig.to_bytes());

        format!("{}.{}.{}", header_b64, payload_b64, sig_b64)
    }

    fn create_cart_mandate(
        &self,
        agent_id: &str,
        constraints: &SpendingConstraints,
        merchant: &str,
        items: Vec<PaymentItem>,
    ) -> CartMandate {
        let total = items.iter().map(|i| i.amount).sum();
        let contents = CartContents {
            id: format!("cart_{}", Uuid::new_v4().simple()),
            user_cart_confirmation_required: constraints.requires_confirmation,
            payment_request: PaymentRequest {
                total: PaymentItem {
                    id: "total".to_string(),
                    label: "Total".to_string(),
                    amount: total,
                },
                items,
            },
            cart_expiry: constraints.expires_at.to_rfc3339(),
            merchant_name: merchant.to_string(),
        };
        let cart_json = serde_json::to_vec(&contents).unwrap();
        let merchant_auth = Some(self.sign_jwt_merchant_auth(agent_id, &cart_json));
        CartMandate {
            contents,
            merchant_authorization: merchant_auth,
        }
    }

    fn hash_mandate_json<T: Serialize>(data: &T) -> String {
        let json = serde_json::to_vec(data).unwrap();
        format!("{:x}", Sha256::digest(&json))
    }

    fn double_sign_mandate(&self, agent_id: &str, mandate_hash: &[u8]) -> (Vec<u8>, Vec<u8>) {
        let issuer_key = self.derive_issuer_key(agent_id);
        let user_key = self.derive_user_key(agent_id);

        let issuer_sig: Signature = issuer_key.sign(mandate_hash);

        let mut kb_payload = Vec::new();
        kb_payload.extend_from_slice(mandate_hash);
        kb_payload.extend_from_slice(issuer_sig.to_bytes().as_slice());
        let user_sig: Signature = user_key.sign(&Sha256::digest(&kb_payload));

        (issuer_sig.to_bytes().to_vec(), user_sig.to_bytes().to_vec())
    }

    async fn settle_on_chain(&self, agent_id: &str, to: &str, amount_wei: u64) -> Result<String> {
        let user_key = self.derive_user_key(agent_id);
        let from_addr = self.wallet_address(agent_id);

        let request = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "eth_sendTransaction",
            "params": [{
                "from": from_addr,
                "to": to,
                "value": format!("0x{:x}", amount_wei),
                "data": "0x"
            }],
            "id": 1
        });

        let resp = self
            .http_client
            .post(&self.rpc_url)
            .header("Content-Type", "application/json")
            .json(&request)
            .send()
            .await
            .map_err(|e| EngineError::ExternalService(format!("ETH transfer failed: {}", e)))?;

        let status = resp.status();
        let error_body = resp.text().await.unwrap_or_default();

        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "ETH RPC returned status: {} - {}",
                status, error_body
            )));
        }

        #[derive(Deserialize)]
        struct RpcResponse {
            result: String,
        }

        let rpc_resp: RpcResponse = serde_json::from_str(&error_body).map_err(|e| {
            EngineError::ExternalService(format!("failed to parse RPC response: {}", e))
        })?;

        Ok(rpc_resp.result)
    }
}

#[async_trait]
impl ProtocolAdapter for Ap2Adapter {
    fn name(&self) -> &str {
        "ap2"
    }

    async fn authorize(
        &self,
        wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        let start = std::time::Instant::now();
        let agent_id = &wallet.agent_id;
        let merchant = constraints
            .merchants
            .as_ref()
            .and_then(|m| m.first().map(|s| s.as_str()));
        let mandate_type = if constraints.requires_confirmation {
            "cart"
        } else {
            "intent"
        };

        let token_id = format!("ap2_{}", Uuid::new_v4().simple());

        let mandate_hash = if mandate_type == "intent" {
            let intent = Self::create_intent_mandate(constraints, merchant);
            Self::hash_mandate_json(&intent).into_bytes()
        } else {
            let items = vec![PaymentItem {
                id: format!(
                    "item_{}",
                    Uuid::new_v4().simple().to_string()[..8].to_string()
                ),
                label: "Agent Purchase".to_string(),
                amount: constraints.max_amount as i64,
            }];
            let cart = self.create_cart_mandate(
                agent_id,
                constraints,
                merchant.unwrap_or("merchant"),
                items,
            );
            let cart_json = serde_json::to_vec(&cart).unwrap();
            let merchant_auth = Some(self.sign_jwt_merchant_auth(agent_id, &cart_json));
            let cart_with_auth = CartMandate {
                contents: cart.contents,
                merchant_authorization: merchant_auth,
            };
            Self::hash_mandate_json(&cart_with_auth).into_bytes()
        };

        let (issuer_sig, user_sig) = self.double_sign_mandate(agent_id, &mandate_hash);

        {
            let mut mandates = self.mandates.lock().unwrap();
            mandates.insert(
                token_id.clone(),
                MandateRecord {
                    mandate_type: mandate_type.to_string(),
                    max_amount: constraints.max_amount,
                    constraint_hash: format!("{:x}", Sha256::digest(&mandate_hash)),
                    issuer_sig,
                    user_sig,
                    consumed: false,
                },
            );
        }

        let token = AuthToken {
            token_id,
            protocol: "ap2".into(),
            max_amount: constraints.max_amount,
            currency: constraints.currency.clone(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "agent_id": agent_id,
                "mandate_type": mandate_type,
                "vdc_signed": true,
                "double_signed": true,
                "wallet_address": self.wallet_address(agent_id),
            }),
        };

        let auth_us = start.elapsed().as_micros() as u64;
        self.metrics.record_auth(auth_us);
        Ok(token)
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let start = std::time::Instant::now();

        let agent_id = token
            .protocol_data
            .get("agent_id")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");

        let mandate_data = {
            let mandates = self.mandates.lock().unwrap();
            let mandate = mandates
                .get(&token.token_id)
                .ok_or_else(|| EngineError::PaymentDeclined("mandate not found".into()))?;

            if mandate.consumed {
                return Err(EngineError::PaymentDeclined(
                    "mandate already consumed".into(),
                ));
            }
            if amount > mandate.max_amount {
                return Err(EngineError::PaymentDeclined(
                    "amount exceeds mandate".into(),
                ));
            }

            let mandate_hash = hex::decode(&mandate.constraint_hash)
                .map_err(|_| EngineError::PaymentDeclined("invalid constraint hash".into()))?;

            let issuer_key = self.derive_issuer_key(agent_id);
            let issuer_verify = *issuer_key.verifying_key();
            let issuer_sig = Signature::from_bytes(mandate.issuer_sig.as_slice().into())
                .map_err(|_| EngineError::PaymentDeclined("invalid issuer signature".into()))?;
            issuer_verify
                .verify(&mandate_hash, &issuer_sig)
                .map_err(|_| {
                    EngineError::PaymentDeclined("issuer signature verification failed".into())
                })?;

            let user_key = self.derive_user_key(agent_id);
            let user_verify = *user_key.verifying_key();
            let user_sig = Signature::from_bytes(mandate.user_sig.as_slice().into())
                .map_err(|_| EngineError::PaymentDeclined("invalid user signature".into()))?;
            let mut kb_payload = mandate_hash.clone();
            kb_payload.extend_from_slice(&mandate.issuer_sig);
            let kb_hash = Sha256::digest(&kb_payload);
            user_verify.verify(&kb_hash, &user_sig).map_err(|_| {
                EngineError::PaymentDeclined(
                    "user key-binding signature verification failed".into(),
                )
            })?;

            mandate.clone()
        };

        let tx_hash = {
            let amount_wei = (amount as u64) * 10u64.pow(14);
            self.settle_on_chain(agent_id, merchant, amount_wei).await?
        };

        {
            let mut mandates = self.mandates.lock().unwrap();
            if let Some(m) = mandates.get_mut(&token.token_id) {
                m.consumed = true;
            }
        }

        let exec_us = start.elapsed().as_micros() as u64;
        let fee = self.fee_for(amount);

        let payment = PaymentResult {
            payment_id: tx_hash,
            protocol: "ap2".into(),
            amount,
            currency: token.currency.clone(),
            status: PaymentStatus::Settled,
            execution_us: exec_us,
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "agent_id": agent_id,
                "mandate_id": token.token_id,
                "mandate_type": mandate_data.mandate_type,
                "issuer_verified": true,
                "user_kb_verified": true,
                "vdc_chain_valid": true,
                "wallet_address": self.wallet_address(agent_id),
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

        Ok(RefundResult {
            refund_id: format!("ap2_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            execution_us: start.elapsed().as_micros() as u64,
        })
    }

    fn metrics(&self) -> ProtocolMetrics {
        self.metrics.to_metrics("ap2")
    }
    fn fee_for(&self, amount: Cents) -> Cents {
        (amount * 25 / 1000) + 20
    }
    fn supports_micropayments(&self) -> bool {
        false
    }
    fn autonomy_level(&self) -> f64 {
        0.5
    }
}
