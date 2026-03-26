use hmac::{Hmac, Mac};
use k256::ecdsa::SigningKey;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::{Arc, RwLock};

use crate::core::error::{EngineError, Result};
use crate::core::types::{AgentWallet, Cents};

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, Clone)]
pub struct WalletInfo {
    pub agent_id: String,
    pub protocol: String,
    pub balance: Cents,
    pub address: String,
}

pub struct WalletService {
    wallets: RwLock<HashMap<String, WalletInfo>>,
    master_seed: String,
}

impl WalletService {
    pub fn new(master_seed: String) -> Self {
        Self {
            wallets: RwLock::new(HashMap::new()),
            master_seed,
        }
    }

    fn derive_key(&self, protocol: &str, agent_id: &str) -> [u8; 32] {
        let mut mac = HmacSha256::new_from_slice(self.master_seed.as_bytes())
            .expect("HMAC can take key of any size");
        mac.update(format!("{}:{}", protocol, agent_id).as_bytes());
        let result = mac.finalize();
        let bytes = result.into_bytes();
        let mut key = [0u8; 32];
        key.copy_from_slice(&bytes[..32]);
        key
    }

    fn derive_address(&self, protocol: &str, agent_id: &str) -> String {
        let key = self.derive_key(protocol, agent_id);
        let signing_key = SigningKey::from_slice(&key).expect("key is valid 32 bytes");
        let verifying_key = signing_key.verifying_key();
        let pub_key = verifying_key.to_encoded_point(false);
        let hash = Sha256::digest(&pub_key.as_bytes()[1..]);
        let last_20 = &hash[hash.len() - 20..];
        format!("0x{}", hex::encode(last_20))
    }

    pub fn create_wallet(
        &self,
        agent_id: &str,
        protocol: &str,
        initial_balance: Cents,
    ) -> Result<WalletInfo> {
        let address = self.derive_address(protocol, agent_id);
        let wallet = WalletInfo {
            agent_id: agent_id.to_string(),
            protocol: protocol.to_string(),
            balance: initial_balance,
            address,
        };

        let key = format!("{}:{}", agent_id, protocol);
        let mut wallets = self.wallets.write().unwrap();
        wallets.insert(key, wallet.clone());

        Ok(wallet)
    }

    pub fn get_wallet(&self, agent_id: &str, protocol: &str) -> Result<WalletInfo> {
        let key = format!("{}:{}", agent_id, protocol);
        let wallets = self.wallets.read().unwrap();

        wallets.get(&key).cloned().ok_or_else(|| {
            EngineError::NotFound(format!("wallet for agent {} on {}", agent_id, protocol))
        })
    }

    pub fn get_or_create_wallet(&self, agent_id: &str, protocol: &str) -> Result<WalletInfo> {
        let key = format!("{}:{}", agent_id, protocol);
        let wallets = self.wallets.read().unwrap();

        if let Some(wallet) = wallets.get(&key) {
            return Ok(wallet.clone());
        }
        drop(wallets);

        self.create_wallet(agent_id, protocol, 0)?;
        self.get_wallet(agent_id, protocol)
    }

    pub fn deduct(&self, agent_id: &str, protocol: &str, amount: Cents) -> Result<()> {
        let key = format!("{}:{}", agent_id, protocol);
        let mut wallets = self.wallets.write().unwrap();

        let wallet = wallets.get_mut(&key).ok_or_else(|| {
            EngineError::NotFound(format!("wallet for agent {} on {}", agent_id, protocol))
        })?;

        if wallet.balance < amount {
            return Err(EngineError::PaymentDeclined(format!(
                "insufficient balance: {} < {}",
                wallet.balance, amount
            )));
        }

        wallet.balance -= amount;
        tracing::debug!(
            "deducted {} from {}:{}. new balance: {}",
            amount,
            agent_id,
            protocol,
            wallet.balance
        );
        Ok(())
    }

    pub fn credit(&self, agent_id: &str, protocol: &str, amount: Cents) -> Result<()> {
        let key = format!("{}:{}", agent_id, protocol);
        let mut wallets = self.wallets.write().unwrap();

        let wallet = wallets.get_mut(&key).ok_or_else(|| {
            EngineError::NotFound(format!("wallet for agent {} on {}", agent_id, protocol))
        })?;

        wallet.balance += amount;
        tracing::debug!(
            "credited {} to {}:{}. new balance: {}",
            amount,
            agent_id,
            protocol,
            wallet.balance
        );
        Ok(())
    }

    pub fn to_agent_wallet(&self, agent_id: &str, protocol: &str) -> Result<AgentWallet> {
        let wallet = self.get_or_create_wallet(agent_id, protocol)?;
        Ok(AgentWallet {
            agent_id: wallet.agent_id,
            balance: wallet.balance,
            protocol: wallet.protocol.clone(),
            credentials: serde_json::json!({
                "address": wallet.address,
            }),
        })
    }

    pub fn list_wallets(&self) -> Vec<WalletInfo> {
        let wallets = self.wallets.read().unwrap();
        wallets.values().cloned().collect()
    }

    pub fn total_balance(&self) -> Cents {
        let wallets = self.wallets.read().unwrap();
        wallets.values().map(|w| w.balance).sum()
    }
}

pub type SharedWalletService = Arc<WalletService>;

pub fn create_wallet_service(master_seed: &str) -> SharedWalletService {
    Arc::new(WalletService::new(master_seed.to_string()))
}
