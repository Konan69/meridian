use hmac::{Hmac, Mac};
use k256::ecdsa::{Signature, SigningKey, signature::Signer};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::{Arc, RwLock};

use crate::core::error::{EngineError, Result};
use crate::core::types::Cents;

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, Clone)]
pub struct TreasuryConfig {
    pub eth_rpc_url: String,
    pub usdc_contract: String,
    pub chain_id: u64,
    pub treasury_private_key: String,
}

#[derive(Debug, Clone)]
pub struct AgentFunding {
    pub agent_id: String,
    pub protocol: String,
    pub balance: Cents,
    pub address: String,
    pub funded: bool,
}

pub struct TreasuryService {
    config: TreasuryConfig,
    http_client: reqwest::Client,
    funding: RwLock<HashMap<String, AgentFunding>>,
}

impl TreasuryService {
    pub fn new(treasury_private_key: String, eth_rpc_url: String) -> Self {
        Self {
            config: TreasuryConfig {
                eth_rpc_url,
                usdc_contract: "0x036CbD53842c5426634e7929541eC2318f3dCF7e".to_string(),
                chain_id: 84532,
                treasury_private_key,
            },
            http_client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap_or_default(),
            funding: RwLock::new(HashMap::new()),
        }
    }

    fn derive_treasury_address(&self) -> String {
        let key = SigningKey::from_slice(
            hex::decode(&self.config.treasury_private_key[2..])
                .unwrap()
                .as_slice(),
        )
        .unwrap();
        let verifying_key = key.verifying_key();
        let pub_key = verifying_key.to_encoded_point(false);
        let hash = Sha256::digest(&pub_key.as_bytes()[1..]);
        let last_20 = &hash[hash.len() - 20..];
        format!("0x{}", hex::encode(last_20))
    }

    fn derive_agent_address(&self, master_seed: &str, agent_id: &str, protocol: &str) -> String {
        let mut mac = HmacSha256::new_from_slice(master_seed.as_bytes())
            .expect("HMAC can take key of any size");
        mac.update(format!("{}:{}:{}", protocol, agent_id, "wallet").as_bytes());
        let result = mac.finalize();
        let bytes = result.into_bytes();

        let hash = Sha256::digest(&bytes);
        let last_20 = &hash[hash.len() - 20..];
        format!("0x{}", hex::encode(last_20))
    }

    pub fn treasury_address(&self) -> String {
        self.derive_treasury_address()
    }

    pub fn get_agent_funding(&self, agent_id: &str, protocol: &str) -> Option<AgentFunding> {
        let key = format!("{}:{}", agent_id, protocol);
        self.funding.read().unwrap().get(&key).cloned()
    }

    pub fn is_agent_funded(&self, agent_id: &str, protocol: &str) -> bool {
        self.get_agent_funding(agent_id, protocol)
            .map(|f| f.funded)
            .unwrap_or(false)
    }

    async fn transfer_to_agent(&self, to_address: &str, amount_wei: u64) -> Result<String> {
        let from = self.derive_treasury_address();
        let request = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "eth_sendTransaction",
            "params": [{
                "from": from,
                "to": to_address,
                "value": format!("0x{:x}", amount_wei),
                "data": "0x"
            }],
            "id": 1
        });

        let resp = self
            .http_client
            .post(&self.config.eth_rpc_url)
            .header("Content-Type", "application/json")
            .json(&request)
            .send()
            .await
            .map_err(|e| EngineError::ExternalService(format!("ETH transfer failed: {}", e)))?;

        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();

        if !status.is_success() {
            return Err(EngineError::ExternalService(format!(
                "ETH transfer rejected: {} - {}",
                status, body
            )));
        }

        #[derive(Deserialize)]
        struct RpcResponse {
            result: String,
        }

        let rpc_resp: RpcResponse = serde_json::from_str(&body).map_err(|e| {
            EngineError::ExternalService(format!("failed to parse RPC response: {}", e))
        })?;

        Ok(rpc_resp.result)
    }

    pub async fn fund_agent(
        &self,
        master_seed: &str,
        agent_id: &str,
        protocol: &str,
        amount_cents: Cents,
    ) -> Result<AgentFunding> {
        let key = format!("{}:{}", agent_id, protocol);
        let address = self.derive_agent_address(master_seed, agent_id, protocol);

        let amount_wei = (amount_cents as u64) * 10u64.pow(14);

        let tx_hash = self.transfer_to_agent(&address, amount_wei).await?;

        let funding = AgentFunding {
            agent_id: agent_id.to_string(),
            protocol: protocol.to_string(),
            balance: amount_cents,
            address: address.clone(),
            funded: true,
        };

        {
            let mut funding_map = self.funding.write().unwrap();
            funding_map.insert(key, funding.clone());
        }

        tracing::info!(
            "funded agent {} on {} with {} cents. tx: {}",
            agent_id,
            protocol,
            amount_cents,
            tx_hash
        );

        Ok(funding)
    }

    pub async fn fund_agent_if_needed(
        &self,
        master_seed: &str,
        agent_id: &str,
        protocol: &str,
        amount_cents: Cents,
    ) -> Result<AgentFunding> {
        if self.is_agent_funded(agent_id, protocol) {
            return self
                .get_agent_funding(agent_id, protocol)
                .ok_or_else(|| EngineError::NotFound("funding record not found".into()));
        }
        self.fund_agent(master_seed, agent_id, protocol, amount_cents)
            .await
    }

    pub fn list_funded_agents(&self) -> Vec<AgentFunding> {
        let funding = self.funding.read().unwrap();
        funding.values().cloned().collect()
    }

    pub fn total_funded(&self) -> Cents {
        let funding = self.funding.read().unwrap();
        funding.values().map(|f| f.balance).sum()
    }
}

pub type SharedTreasury = Arc<TreasuryService>;

pub fn create_treasury(treasury_private_key: &str, eth_rpc_url: &str) -> SharedTreasury {
    Arc::new(TreasuryService::new(
        treasury_private_key.to_string(),
        eth_rpc_url.to_string(),
    ))
}
