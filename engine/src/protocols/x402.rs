use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use sha2::Digest;
use std::collections::HashSet;
use std::sync::{Arc, Mutex};
use uuid::Uuid;

use super::{
    AuthToken, MetricsTracker, PaymentResult, PaymentStatus, ProtocolAdapter, RefundResult,
    SettlementResult,
};
use crate::config::Config;
use crate::core::error::{EngineError, Result};
use crate::core::types::{ActorWallet, Cents, ProtocolMetrics, SpendingConstraints};

const BASE_SEPOLIA_CHAIN_ID: &str = "eip155:84532";
const NATIVE_ETH_CONTRACT: &str = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE";

#[derive(Debug, Clone)]
pub struct X402Adapter {
    metrics: MetricsTracker,
    http_client: reqwest::Client,
    public_base_url: String,
    cdp_service_url: String,
    usdc_contract: String,
    funded_accounts: Arc<Mutex<HashSet<String>>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PaymentRequirements {
    scheme: String,
    network: String,
    amount: String,
    asset: String,
    #[serde(rename = "payTo")]
    pay_to: String,
    #[serde(rename = "maxTimeoutSeconds")]
    max_timeout_seconds: u64,
    extra: PaymentRequirementsExtra,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PaymentRequirementsExtra {
    name: String,
    version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PaymentPayload {
    #[serde(rename = "x402Version")]
    x402_version: u32,
    resource: PaymentResource,
    accepted: AcceptedPayment,
    payload: PaymentAuth,
    extensions: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PaymentResource {
    url: String,
    description: String,
    #[serde(rename = "mimeType")]
    mime_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct AcceptedPayment {
    scheme: String,
    network: String,
    amount: String,
    asset: String,
    #[serde(rename = "payTo")]
    pay_to: String,
    #[serde(rename = "maxTimeoutSeconds")]
    max_timeout_seconds: u64,
    extra: PaymentRequirementsExtra,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PaymentAuth {
    signature: String,
    authorization: EIP3009Authorization,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct EIP3009Authorization {
    from: String,
    to: String,
    value: String,
    #[serde(rename = "validAfter")]
    valid_after: String,
    #[serde(rename = "validBefore")]
    valid_before: String,
    nonce: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct FacilitatorVerifyRequest {
    #[serde(rename = "x402Version")]
    x402_version: u32,
    #[serde(rename = "paymentPayload")]
    payment_payload: PaymentPayload,
    #[serde(rename = "paymentRequirements")]
    payment_requirements: PaymentRequirements,
}

#[derive(Debug, Deserialize)]
struct FacilitatorVerifyResponse {
    #[serde(rename = "isValid")]
    is_valid: bool,
    #[serde(rename = "payer")]
    _payer: Option<String>,
    #[serde(rename = "invalidReason")]
    invalid_reason: Option<String>,
    #[serde(rename = "invalidMessage")]
    invalid_message: Option<String>,
}

#[derive(Debug, Deserialize)]
struct FacilitatorSettleResponse {
    success: bool,
    transaction: Option<String>,
    network: String,
    #[serde(rename = "payer")]
    _payer: Option<String>,
    #[serde(rename = "errorReason")]
    error_reason: Option<String>,
    #[serde(rename = "errorMessage")]
    error_message: Option<String>,
}

impl X402Adapter {
    pub fn new(config: Config) -> Self {
        Self {
            metrics: MetricsTracker::new(),
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default(),
            public_base_url: config.public_base_url.clone(),
            cdp_service_url: config.cdp_service_url.clone(),
            usdc_contract: config.x402.usdc_contract,
            funded_accounts: Arc::new(Mutex::new(HashSet::new())),
        }
    }

    fn server_wallet_name(owner_kind: &str, owner_id: &str) -> String {
        let kind_tag = match owner_kind {
            "merchant" => "m",
            "agent" => "a",
            other => {
                if other.is_empty() {
                    "x"
                } else {
                    &other[..1]
                }
            }
        };
        let normalized = owner_id
            .chars()
            .map(|ch| {
                if ch.is_ascii_alphanumeric() {
                    ch.to_ascii_lowercase()
                } else {
                    '-'
                }
            })
            .collect::<String>();
        let normalized = normalized
            .split('-')
            .filter(|part| !part.is_empty())
            .collect::<Vec<_>>()
            .join("-");
        let hash = &hex::encode(sha2::Sha256::digest(format!("{}:{}", owner_kind, owner_id)))[..8];
        let prefix = format!("mer-{}-", kind_tag);
        let max_slug_len = 36usize.saturating_sub(prefix.len() + 1 + hash.len());
        let slug = if normalized.is_empty() {
            "wallet".to_string()
        } else {
            normalized.chars().take(max_slug_len.max(1)).collect::<String>()
        };
        format!("{}{}-{}", prefix, slug.trim_matches('-'), hash)
    }

    fn is_evm_address(value: &str) -> bool {
        value.starts_with("0x") && value.len() == 42 && value[2..].chars().all(|c| c.is_ascii_hexdigit())
    }

    async fn cdp_get_or_create_account(&self, owner_kind: &str, owner_id: &str) -> Result<String> {
        #[derive(Deserialize)]
        struct AccountResponse {
            address: String,
        }

        let resp = self
            .http_client
            .post(format!(
                "{}/evm/get-or-create-account",
                self.cdp_service_url.trim_end_matches('/')
            ))
            .json(&serde_json::json!({
                "name": Self::server_wallet_name(owner_kind, owner_id),
                "owner_kind": owner_kind,
                "owner_id": owner_id,
            }))
            .send()
            .await
            .map_err(|e| EngineError::ExternalService(format!("cdp account request failed: {}", e)))?;

        let status = resp.status();
        let bytes = resp.bytes().await.unwrap_or_default();
        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "cdp account request returned {}: {}",
                status,
                String::from_utf8_lossy(&bytes)
            )));
        }

        let body: AccountResponse = serde_json::from_slice(&bytes)
            .map_err(|e| EngineError::ExternalService(format!("cdp account parse failed: {}", e)))?;
        Ok(body.address)
    }

    async fn cdp_sign_typed_data(
        &self,
        address: &str,
        domain: serde_json::Value,
        message: serde_json::Value,
    ) -> Result<String> {
        let types = serde_json::json!({
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
        });

        #[derive(Deserialize)]
        struct SignatureResponse {
            signature: String,
        }

        let resp = self
            .http_client
            .post(format!(
                "{}/evm/sign-typed-data",
                self.cdp_service_url.trim_end_matches('/')
            ))
            .json(&serde_json::json!({
                "address": address,
                "domain": domain,
                "types": types,
                "primaryType": "TransferWithAuthorization",
                "message": message,
            }))
            .send()
            .await
            .map_err(|e| EngineError::ExternalService(format!("cdp signTypedData failed: {}", e)))?;

        let status = resp.status();
        let bytes = resp.bytes().await.unwrap_or_default();
        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "cdp signTypedData returned {}: {}",
                status,
                String::from_utf8_lossy(&bytes)
            )));
        }

        let body: SignatureResponse = serde_json::from_slice(&bytes)
            .map_err(|e| EngineError::ExternalService(format!("cdp signature parse failed: {}", e)))?;
        Ok(body.signature)
    }

    async fn cdp_request_faucet(&self, address: &str, token: &str) -> Result<()> {
        let resp = self
            .http_client
            .post(format!(
                "{}/evm/request-faucet",
                self.cdp_service_url.trim_end_matches('/')
            ))
            .json(&serde_json::json!({
                "address": address,
                "token": token,
            }))
            .send()
            .await
            .map_err(|e| EngineError::ExternalService(format!("cdp faucet request failed: {}", e)))?;

        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "cdp faucet request returned {}: {}",
                status, body
            )));
        }
        Ok(())
    }

    async fn cdp_get_token_balances(&self, address: &str) -> Result<Vec<serde_json::Value>> {
        let resp = self
            .http_client
            .get(format!(
                "{}/evm/token-balances/{}",
                self.cdp_service_url.trim_end_matches('/'),
                address
            ))
            .send()
            .await
            .map_err(|e| EngineError::ExternalService(format!("cdp token balance request failed: {}", e)))?;

        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "cdp token balance request returned {}: {}",
                status, body
            )));
        }

        let json: serde_json::Value = serde_json::from_str(&body).map_err(|e| {
            EngineError::ExternalService(format!("cdp token balance parse failed: {}", e))
        })?;

        Ok(json
            .get("balances")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default())
    }

    async fn wait_for_test_funds(&self, address: &str) -> Result<()> {
        for _ in 0..20 {
            let balances = self.cdp_get_token_balances(address).await?;
            let has_eth = balances.iter().any(|balance| {
                balance
                    .get("contractAddress")
                    .and_then(|v| v.as_str())
                    .map(|value| value.eq_ignore_ascii_case(NATIVE_ETH_CONTRACT))
                    .unwrap_or(false)
                    && balance
                        .get("amount")
                        .and_then(|v| v.as_str())
                        .and_then(|amount| amount.parse::<u128>().ok())
                        .map(|amount| amount > 0)
                        .unwrap_or(false)
            });
            let has_usdc = balances.iter().any(|balance| {
                balance
                    .get("contractAddress")
                    .and_then(|v| v.as_str())
                    .map(|value| value.eq_ignore_ascii_case(&self.usdc_contract))
                    .unwrap_or(false)
                    && balance
                        .get("amount")
                        .and_then(|v| v.as_str())
                        .and_then(|amount| amount.parse::<u128>().ok())
                        .map(|amount| amount > 0)
                        .unwrap_or(false)
            });

            if has_eth && has_usdc {
                return Ok(());
            }

            tokio::time::sleep(std::time::Duration::from_secs(2)).await;
        }

        Err(EngineError::ExternalService(format!(
            "test funds not visible yet for {} after waiting",
            address
        )))
    }

    async fn ensure_test_funding(&self, address: &str) -> Result<()> {
        {
            let funded = self.funded_accounts.lock().unwrap();
            if funded.contains(address) {
                return Ok(());
            }
        }

        let existing_balances = self.cdp_get_token_balances(address).await?;
        let already_funded = existing_balances.iter().any(|balance| {
            balance
                .get("contractAddress")
                .and_then(|v| v.as_str())
                .map(|value| value.eq_ignore_ascii_case(&self.usdc_contract))
                .unwrap_or(false)
                && balance
                    .get("amount")
                    .and_then(|v| v.as_str())
                    .and_then(|amount| amount.parse::<u128>().ok())
                    .map(|amount| amount > 0)
                    .unwrap_or(false)
        });

        if already_funded {
            let mut funded = self.funded_accounts.lock().unwrap();
            funded.insert(address.to_string());
            return Ok(());
        }

        self.cdp_request_faucet(address, "eth").await?;
        self.cdp_request_faucet(address, "usdc").await?;
        self.wait_for_test_funds(address).await?;

        let mut funded = self.funded_accounts.lock().unwrap();
        funded.insert(address.to_string());
        Ok(())
    }

    async fn resolve_pay_to(&self, merchant_ref: &str) -> Result<String> {
        if Self::is_evm_address(merchant_ref) {
            return Ok(merchant_ref.to_string());
        }

        self.cdp_get_or_create_account("merchant", merchant_ref).await
    }

    fn build_payment_requirements(&self, amount: Cents, pay_to: &str) -> PaymentRequirements {
        PaymentRequirements {
            scheme: "exact".to_string(),
            network: BASE_SEPOLIA_CHAIN_ID.to_string(),
            amount: amount.to_string(),
            asset: self.usdc_contract.clone(),
            pay_to: pay_to.to_string(),
            max_timeout_seconds: 3600,
            extra: PaymentRequirementsExtra {
                name: "USDC".to_string(),
                version: "2".to_string(),
            },
        }
    }

    async fn build_payment_payload(
        &self,
        from_address: &str,
        resource_url: &str,
        amount: Cents,
        pay_to: &str,
    ) -> Result<(PaymentPayload, String, u64, u64, String)> {
        let from = from_address.to_string();
        let valid_after = chrono::Utc::now().timestamp() as u64;
        let valid_before = valid_after + 3600;
        let nonce = format!("0x{}", hex::encode(rand::random::<[u8; 32]>()));

        let authorization = EIP3009Authorization {
            from: from.clone(),
            to: pay_to.to_string(),
            value: amount.to_string(),
            valid_after: valid_after.to_string(),
            valid_before: valid_before.to_string(),
            nonce: nonce.clone(),
        };

        let domain = serde_json::json!({
            "name": "USDC",
            "version": "2",
            "chainId": 84532,
            "verifyingContract": self.usdc_contract.clone(),
        });
        let message = serde_json::json!({
            "from": from,
            "to": pay_to,
            "value": amount.to_string(),
            "validAfter": valid_after.to_string(),
            "validBefore": valid_before.to_string(),
            "nonce": nonce
        });
        let signature = self
            .cdp_sign_typed_data(&from, domain, message)
            .await?;

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
                asset: self.usdc_contract.clone(),
                pay_to: pay_to.to_string(),
                max_timeout_seconds: 3600,
                extra: PaymentRequirementsExtra {
                    name: "USDC".to_string(),
                    version: "2".to_string(),
                },
            },
            payload: PaymentAuth {
                signature,
                authorization,
            },
            extensions: serde_json::json!({}),
        };

        Ok((payload, from, valid_after, valid_before, nonce))
    }

    async fn verify_and_settle_facilitator(
        &self,
        payload: PaymentPayload,
        requirements: PaymentRequirements,
    ) -> Result<String> {
        for attempt in 0..3 {
            let request = FacilitatorVerifyRequest {
                x402_version: 2,
                payment_payload: payload.clone(),
                payment_requirements: requirements.clone(),
            };

            let verify_resp = self
                .http_client
                .post("https://x402.org/facilitator/verify")
                .json(&request)
                .send()
                .await
                .map_err(|e| {
                    EngineError::ExternalService(format!("facilitator request failed: {}", e))
                })?;

            let verify_status = verify_resp.status();
            let verify_body = verify_resp.text().await.unwrap_or_default();

            if !verify_status.is_success() {
                return Err(EngineError::ExternalService(format!(
                    "facilitator returned status: {} - {}",
                    verify_status, verify_body
                )));
            }

            let verify_result: FacilitatorVerifyResponse =
                serde_json::from_str(&verify_body).map_err(|e| {
                    EngineError::ExternalService(format!(
                        "failed to parse facilitator verify response: {} - body: {}",
                        e, verify_body
                    ))
                })?;

            if !verify_result.is_valid {
                let transient = matches!(
                    verify_result.invalid_reason.as_deref(),
                    Some("invalid_exact_evm_insufficient_balance")
                        | Some("invalid_exact_evm_transaction_simulation_failed")
                );

                if transient && attempt < 2 {
                    tokio::time::sleep(std::time::Duration::from_secs(3)).await;
                    continue;
                }

                return Err(EngineError::ExternalService(format!(
                    "payment verification failed: {:?} - {:?}",
                    verify_result.invalid_reason,
                    verify_result.invalid_message
                )));
            }

            let settle_resp = self
                .http_client
                .post("https://x402.org/facilitator/settle")
                .json(&request)
                .send()
                .await
                .map_err(|e| {
                    EngineError::ExternalService(format!("facilitator settle request failed: {}", e))
                })?;

            let settle_status = settle_resp.status();
            let settle_body = settle_resp.text().await.unwrap_or_default();

            if !settle_status.is_success() {
                return Err(EngineError::ExternalService(format!(
                    "facilitator settle returned status: {} - {}",
                    settle_status, settle_body
                )));
            }

            let settle_result: FacilitatorSettleResponse =
                serde_json::from_str(&settle_body).map_err(|e| {
                    EngineError::ExternalService(format!(
                        "failed to parse facilitator settle response: {} - body: {}",
                        e, settle_body
                    ))
                })?;

            if !settle_result.success {
                return Err(EngineError::ExternalService(format!(
                    "payment settlement failed: {:?} - {:?}",
                    settle_result.error_reason,
                    settle_result.error_message
                )));
            }

            return settle_result.transaction.ok_or_else(|| {
                EngineError::ExternalService(format!(
                    "facilitator settle succeeded without a settlement transaction on {}",
                    settle_result.network
                ))
            });
        }

        Err(EngineError::ExternalService(
            "facilitator verification retries exhausted".into(),
        ))
    }
}

#[async_trait]
impl ProtocolAdapter for X402Adapter {
    fn name(&self) -> &str {
        "x402"
    }

    async fn authorize(
        &self,
        wallet: &ActorWallet,
        constraints: &SpendingConstraints,
    ) -> Result<AuthToken> {
        let start = std::time::Instant::now();
        let token_id = format!("x402_{}", Uuid::new_v4().simple());
        let wallet_addr = self
            .cdp_get_or_create_account(&wallet.owner_kind, &wallet.owner_id)
            .await?;
        if wallet.owner_kind == "agent" {
            self.ensure_test_funding(&wallet_addr).await?;
        }

        let merchant_ref = constraints
            .merchants
            .as_ref()
            .and_then(|m| m.first())
            .map(|s| s.as_str())
            .ok_or_else(|| EngineError::InvalidRequest("x402 requires a merchant target".into()))?;
        let pay_to = self.resolve_pay_to(merchant_ref).await?;

        let token = AuthToken {
            token_id,
            protocol: "x402".into(),
            max_amount: constraints.max_amount,
            currency: "usdc".into(),
            expires_at: constraints.expires_at,
            protocol_data: serde_json::json!({
                "scheme": "exact",
                "network": BASE_SEPOLIA_CHAIN_ID,
                "asset": self.usdc_contract,
                "pay_to": pay_to,
                "merchant_ref": merchant_ref,
                "owner_kind": wallet.owner_kind,
                "owner_id": wallet.owner_id,
                "wallet_address": wallet_addr.to_string(),
                "usdc_contract": self.usdc_contract,
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

        let owner_kind = token
            .protocol_data
            .get("owner_kind")
            .and_then(|v| v.as_str())
            .ok_or_else(|| EngineError::ProtocolError("missing x402 owner_kind".into()))?;
        let owner_id = token
            .protocol_data
            .get("owner_id")
            .and_then(|v| v.as_str())
            .ok_or_else(|| EngineError::ProtocolError("missing x402 owner_id".into()))?;
        let from_address = token
            .protocol_data
            .get("wallet_address")
            .and_then(|v| v.as_str())
            .ok_or_else(|| EngineError::ProtocolError("missing x402 wallet address".into()))?;

        let resource_url = format!("{}/payments/x402/{}", self.public_base_url, token.token_id);
        let (payload, from_addr, valid_after, valid_before, nonce) =
            self.build_payment_payload(from_address, &resource_url, amount, merchant).await?;

        let requirements = self.build_payment_requirements(amount, merchant);

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
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "from": from_addr,
                "valid_after": valid_after,
                "valid_before": valid_before,
                "nonce": nonce,
                "tx_hash": tx_hash,
                "network": BASE_SEPOLIA_CHAIN_ID,
                "asset": self.usdc_contract,
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
