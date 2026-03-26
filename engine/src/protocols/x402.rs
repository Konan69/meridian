use async_trait::async_trait;
use hmac::{Hmac, Mac};
use k256::ecdsa::{Signature, SigningKey, signature::Signer};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use super::{
    AuthToken, MetricsTracker, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult,
    SettlementResult,
};
use crate::config::Config;
use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents, ProtocolMetrics, SpendingConstraints};

const BASE_SEPOLIA_CHAIN_ID: &str = "eip155:84532";
const USDC_CONTRACT_BASE_SEPOLIA: &str = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";

#[derive(Debug, Clone)]
pub struct X402Adapter {
    metrics: MetricsTracker,
    http_client: reqwest::Client,
    rpc_url: String,
    master_seed: String,
    pay_to: String,
    public_base_url: String,
}

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, Serialize, Deserialize)]
struct PaymentRequirements {
    scheme: String,
    network: String,
    amount: String,
    asset: String,
    pay_to: String,
    max_timeout_seconds: u64,
    extra: PaymentRequirementsExtra,
}

#[derive(Debug, Serialize, Deserialize)]
struct PaymentRequirementsExtra {
    name: String,
    version: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct PaymentPayload {
    #[serde(rename = "x402Version")]
    x402_version: u32,
    resource: PaymentResource,
    accepted: AcceptedPayment,
    payload: PaymentAuth,
    extensions: serde_json::Value,
}

#[derive(Debug, Serialize, Deserialize)]
struct PaymentResource {
    url: String,
    description: String,
    mime_type: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct AcceptedPayment {
    scheme: String,
    network: String,
    amount: String,
    asset: String,
    pay_to: String,
    #[serde(rename = "maxTimeoutSeconds")]
    max_timeout_seconds: u64,
    extra: PaymentRequirementsExtra,
}

#[derive(Debug, Serialize, Deserialize)]
struct PaymentAuth {
    signature: String,
    authorization: EIP3009Authorization,
}

#[derive(Debug, Serialize, Deserialize)]
struct EIP3009Authorization {
    from: String,
    to: String,
    value: String,
    valid_after: String,
    valid_before: String,
    nonce: String,
}

#[derive(Debug, Serialize, Deserialize)]
struct FacilitatorVerifyRequest {
    #[serde(rename = "x402Version")]
    x402_version: u32,
    #[serde(rename = "paymentPayload")]
    payment_payload: PaymentPayload,
    #[serde(rename = "paymentRequirements")]
    payment_requirements: PaymentRequirements,
}

#[derive(Debug, Deserialize)]
struct FacilitatorResponse {
    success: bool,
    transaction: Option<String>,
    network: String,
    payer: Option<String>,
    #[serde(rename = "errorReason")]
    error_reason: Option<String>,
}

impl X402Adapter {
    pub fn new(config: Config) -> Self {
        Self {
            metrics: MetricsTracker::new(),
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default(),
            rpc_url: config.x402.rpc_url.clone(),
            master_seed: config.x402.master_seed.clone(),
            pay_to: config.x402.pay_to.clone(),
            public_base_url: config.public_base_url.clone(),
        }
    }

    fn derive_agent_key(&self, agent_id: &str) -> SigningKey {
        let mut mac = HmacSha256::new_from_slice(self.master_seed.as_bytes())
            .expect("HMAC can take key of any size");
        mac.update(format!("x402:{}", agent_id).as_bytes());
        let result = mac.finalize();
        let bytes = result.into_bytes();
        SigningKey::from_slice(&bytes[..32])
            .unwrap_or_else(|_| SigningKey::random(&mut rand::thread_rng()))
    }

    fn wallet_address(&self, agent_id: &str) -> String {
        let signing_key = self.derive_agent_key(agent_id);
        let verifying_key = signing_key.verifying_key();
        let pub_key = verifying_key.to_encoded_point(false);
        let hash = Sha256::digest(&pub_key.as_bytes()[1..]);
        let last_20 = &hash[hash.len() - 20..];
        format!("0x{}", hex::encode(last_20))
    }

    fn sign_eip712_transfer_with_auth(
        &self,
        agent_id: &str,
        from: &str,
        to: &str,
        value: &str,
        valid_after: u64,
        valid_before: u64,
        nonce: &str,
    ) -> Signature {
        let signing_key = self.derive_agent_key(agent_id);

        let domain = serde_json::json!({
            "name": "USDC",
            "version": "2",
            "chainId": 84532,
            "verifyingContract": USDC_CONTRACT_BASE_SEPOLIA,
        });

        let message = serde_json::json!({
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"}
                ],
                "TransferWithAuthorization": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "validAfter", "type": "uint256"},
                    {"name": "validBefore", "type": "uint256"},
                    {"name": "nonce", "type": "bytes32"}
                ]
            },
            "primaryType": "TransferWithAuthorization",
            "domain": domain,
            "message": {
                "from": from,
                "to": to,
                "value": value,
                "validAfter": valid_after.to_string(),
                "validBefore": valid_before.to_string(),
                "nonce": nonce
            }
        });

        let domain_hash = Sha256::digest(&serde_json::to_vec(&message["domain"]).unwrap());
        let message_hash = Sha256::digest(&serde_json::to_vec(&message["message"]).unwrap());

        let mut signing_input = Vec::new();
        signing_input.extend_from_slice(b"\x19\x01");
        signing_input.extend_from_slice(&domain_hash);
        signing_input.extend_from_slice(&message_hash);

        let digest = Sha256::digest(&signing_input);
        signing_key.sign(&digest)
    }

    fn build_payment_requirements(amount: Cents, pay_to: &str) -> PaymentRequirements {
        PaymentRequirements {
            scheme: "exact".to_string(),
            network: BASE_SEPOLIA_CHAIN_ID.to_string(),
            amount: amount.to_string(),
            asset: USDC_CONTRACT_BASE_SEPOLIA.to_string(),
            pay_to: pay_to.to_string(),
            max_timeout_seconds: 3600,
            extra: PaymentRequirementsExtra {
                name: "USDC".to_string(),
                version: "2".to_string(),
            },
        }
    }

    fn build_payment_payload(
        &self,
        agent_id: &str,
        resource_url: &str,
        amount: Cents,
        pay_to: &str,
    ) -> (PaymentPayload, String, u64, u64, String) {
        let from = self.wallet_address(agent_id);
        let valid_after = chrono::Utc::now().timestamp() as u64;
        let valid_before = valid_after + 3600;
        let nonce = format!("0x{}", hex::encode(Uuid::new_v4().as_bytes()));

        let authorization = EIP3009Authorization {
            from: from.clone(),
            to: pay_to.to_string(),
            value: amount.to_string(),
            valid_after: valid_after.to_string(),
            valid_before: valid_before.to_string(),
            nonce: nonce.clone(),
        };

        let signature = self.sign_eip712_transfer_with_auth(
            agent_id,
            &from,
            pay_to,
            &amount.to_string(),
            valid_after,
            valid_before,
            &nonce,
        );

        let payload = PaymentPayload {
            x402_version: 2,
            resource: PaymentResource {
                url: resource_url.to_string(),
                description: "Meridian Agentic Commerce Payment".to_string(),
                mime_type: "application/json".to_string(),
            },
            accepted: AcceptedPayment {
                scheme: "exact".to_string(),
                network: BASE_SEPOLIA_CHAIN_ID.to_string(),
                amount: amount.to_string(),
                asset: USDC_CONTRACT_BASE_SEPOLIA.to_string(),
                pay_to: pay_to.to_string(),
                max_timeout_seconds: 3600,
                extra: PaymentRequirementsExtra {
                    name: "USDC".to_string(),
                    version: "2".to_string(),
                },
            },
            payload: PaymentAuth {
                signature: format!("0x{}", hex::encode(signature.to_bytes())),
                authorization,
            },
            extensions: serde_json::json!({}),
        };

        (payload, from, valid_after, valid_before, nonce)
    }

    async fn verify_and_settle_facilitator(
        &self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> Result<String> {
        let verify_request = FacilitatorVerifyRequest {
            x402_version: 2,
            payment_payload: payload,
            payment_requirements: requirements,
        };

        let resp = self
            .http_client
            .post("https://x402.org/facilitator/verify")
            .json(&verify_request)
            .send()
            .await
            .map_err(|e| {
                EngineError::ExternalService(format!("facilitator request failed: {}", e))
            })?;

        let status = resp.status();
        let error_body = resp.text().await.unwrap_or_default();

        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "facilitator returned status: {} - {}",
                status, error_body
            )));
        }

        let result: FacilitatorResponse = serde_json::from_str(&error_body).map_err(|e| {
            EngineError::ExternalService(format!("failed to parse facilitator response: {}", e))
        })?;

        if !result.success {
            return Err(EngineError::ExternalService(format!(
                "payment verification failed: {:?}",
                result.error_reason
            )));
        }

        result.transaction.ok_or_else(|| {
            EngineError::ExternalService(format!(
                "facilitator verify succeeded without a settlement transaction on {}",
                result.network
            ))
        })
    }
}

#[async_trait]
impl ProtocolAdapter for X402Adapter {
    fn name(&self) -> &str {
        "x402"
    }

    async fn authorize(
        &self,
        wallet: &AgentWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        let start = std::time::Instant::now();
        let token_id = format!("x402_{}", Uuid::new_v4().simple());
        let wallet_addr = self.wallet_address(&wallet.agent_id);

        let pay_to = constraints
            .merchants
            .as_ref()
            .and_then(|m| m.first())
            .map(|s| s.as_str())
            .unwrap_or(&self.pay_to);

        let token = AuthToken {
            token_id,
            protocol: "x402".into(),
            max_amount: constraints.max_amount,
            currency: "usdc".into(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "scheme": "exact",
                "network": BASE_SEPOLIA_CHAIN_ID,
                "asset": USDC_CONTRACT_BASE_SEPOLIA,
                "pay_to": pay_to,
                "agent_id": wallet.agent_id,
                "wallet_address": wallet_addr.to_string(),
                "usdc_contract": USDC_CONTRACT_BASE_SEPOLIA,
            }),
        };

        let auth_us = start.elapsed().as_micros() as u64;
        self.metrics.record_auth(auth_us);
        Ok(token)
    }

    async fn pay(&self, token: &AuthToken, amount: Cents, merchant: &str) -> Result<PaymentResult> {
        let start = std::time::Instant::now();

        if amount > token.max_amount {
            self.metrics
                .record_failure(start.elapsed().as_micros() as u64);
            return Err(EngineError::PaymentDeclined(
                "amount exceeds authorization".into(),
            ));
        }

        let agent_id = token
            .protocol_data
            .get("agent_id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| EngineError::ProtocolError("missing x402 agent_id".into()))?;

        let resource_url = format!("{}/payments/x402/{}", self.public_base_url, token.token_id);
        let (payload, from_addr, valid_after, valid_before, nonce) =
            self.build_payment_payload(agent_id, &resource_url, amount, merchant);

        let requirements = Self::build_payment_requirements(amount, merchant);

        let tx_hash = self
            .verify_and_settle_facilitator(payload, requirements)
            .await?;
        let exec_us = start.elapsed().as_micros() as u64;
        let fee = self.fee_for(amount);

        let payment = PaymentResult {
            payment_id: format!("x402_pi_{}", Uuid::new_v4().simple()),
            protocol: "x402".into(),
            amount,
            currency: "usdc".into(),
            status: PaymentStatus::Settled,
            execution_us: exec_us,
            fee,
            protocol_data: serde_json::json!({
                "merchant": merchant,
                "agent_id": agent_id,
                "from": from_addr,
                "valid_after": valid_after,
                "valid_before": valid_before,
                "nonce": nonce,
                "tx_hash": tx_hash,
                "network": BASE_SEPOLIA_CHAIN_ID,
                "asset": USDC_CONTRACT_BASE_SEPOLIA,
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
            refund_id: format!("x402_rf_{}", Uuid::new_v4().simple()),
            original_payment_id: payment.payment_id.clone(),
            amount: payment.amount,
            success: true,
            execution_us: start.elapsed().as_micros() as u64,
        })
    }

    fn metrics(&self) -> ProtocolMetrics {
        self.metrics.to_metrics("x402")
    }
    fn fee_for(&self, amount: Cents) -> Cents {
        std::cmp::max(amount / 1000, 1)
    }
    fn supports_micropayments(&self) -> bool {
        true
    }
    fn autonomy_level(&self) -> f64 {
        1.0
    }
}
