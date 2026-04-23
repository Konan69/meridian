use k256::ecdsa::SigningKey;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::{Arc, RwLock};

use crate::core::error::{EngineError, Result};
use crate::core::types::{ActorWallet, Cents};

#[derive(Debug, Clone)]
pub struct WalletInfo {
    pub owner_kind: String,
    pub owner_id: String,
    pub protocol: String,
    pub balance: Cents,
    pub address: Option<String>,
}

pub struct WalletService {
    wallets: RwLock<HashMap<String, WalletInfo>>,
}

impl WalletService {
    pub fn new() -> Self {
        Self {
            wallets: RwLock::new(HashMap::new()),
        }
    }

    fn derive_key(&self, owner_kind: &str, owner_id: &str, protocol: &str) -> [u8; 32] {
        let bytes = Sha256::digest(format!("{}:{}:{}", owner_kind, owner_id, protocol).as_bytes());
        let mut key = [0u8; 32];
        key.copy_from_slice(&bytes[..32]);
        key
    }

    fn derive_address(&self, owner_kind: &str, owner_id: &str, protocol: &str) -> String {
        let key = self.derive_key(owner_kind, owner_id, protocol);
        let signing_key = SigningKey::from_slice(&key).expect("key is valid 32 bytes");
        let verifying_key = signing_key.verifying_key();
        let pub_key = verifying_key.to_encoded_point(false);
        let hash = Sha256::digest(&pub_key.as_bytes()[1..]);
        let last_20 = &hash[hash.len() - 20..];
        format!("0x{}", hex::encode(last_20))
    }

    pub fn create_wallet(
        &self,
        owner_kind: &str,
        owner_id: &str,
        protocol: &str,
        initial_balance: Cents,
    ) -> Result<WalletInfo> {
        let wallet = WalletInfo {
            owner_kind: owner_kind.to_string(),
            owner_id: owner_id.to_string(),
            protocol: protocol.to_string(),
            balance: initial_balance,
            address: None,
        };

        let key = format!("{}:{}:{}", owner_kind, owner_id, protocol);
        let mut wallets = self.wallets.write().unwrap();
        wallets.insert(key, wallet.clone());

        Ok(wallet)
    }

    pub fn get_wallet(
        &self,
        owner_kind: &str,
        owner_id: &str,
        protocol: &str,
    ) -> Result<WalletInfo> {
        let key = format!("{}:{}:{}", owner_kind, owner_id, protocol);
        let wallets = self.wallets.read().unwrap();

        wallets.get(&key).cloned().ok_or_else(|| {
            EngineError::NotFound(format!(
                "wallet for {} {} on {}",
                owner_kind, owner_id, protocol
            ))
        })
    }

    pub fn get_or_create_wallet(
        &self,
        owner_kind: &str,
        owner_id: &str,
        protocol: &str,
    ) -> Result<WalletInfo> {
        let key = format!("{}:{}:{}", owner_kind, owner_id, protocol);
        let wallets = self.wallets.read().unwrap();

        if let Some(wallet) = wallets.get(&key) {
            return Ok(wallet.clone());
        }
        drop(wallets);

        self.create_wallet(owner_kind, owner_id, protocol, 0)?;
        self.get_wallet(owner_kind, owner_id, protocol)
    }

    pub fn deduct(
        &self,
        owner_kind: &str,
        owner_id: &str,
        protocol: &str,
        amount: Cents,
    ) -> Result<()> {
        let key = format!("{}:{}:{}", owner_kind, owner_id, protocol);
        let mut wallets = self.wallets.write().unwrap();

        let wallet = wallets.get_mut(&key).ok_or_else(|| {
            EngineError::NotFound(format!(
                "wallet for {} {} on {}",
                owner_kind, owner_id, protocol
            ))
        })?;

        if wallet.balance < amount {
            return Err(EngineError::PaymentDeclined(format!(
                "insufficient balance: {} < {}",
                wallet.balance, amount
            )));
        }

        wallet.balance -= amount;
        tracing::debug!(
            "deducted {} from {}:{}:{}. new balance: {}",
            amount,
            owner_kind,
            owner_id,
            protocol,
            wallet.balance
        );
        Ok(())
    }

    pub fn credit(
        &self,
        owner_kind: &str,
        owner_id: &str,
        protocol: &str,
        amount: Cents,
    ) -> Result<()> {
        let key = format!("{}:{}:{}", owner_kind, owner_id, protocol);
        let mut wallets = self.wallets.write().unwrap();

        let wallet = wallets.get_mut(&key).ok_or_else(|| {
            EngineError::NotFound(format!(
                "wallet for {} {} on {}",
                owner_kind, owner_id, protocol
            ))
        })?;

        wallet.balance += amount;
        tracing::debug!(
            "credited {} to {}:{}:{}. new balance: {}",
            amount,
            owner_kind,
            owner_id,
            protocol,
            wallet.balance
        );
        Ok(())
    }

    pub fn to_actor_wallet(
        &self,
        owner_kind: &str,
        owner_id: &str,
        protocol: &str,
    ) -> Result<ActorWallet> {
        let wallet = self.get_or_create_wallet(owner_kind, owner_id, protocol)?;
        Ok(ActorWallet {
            owner_kind: wallet.owner_kind,
            owner_id: wallet.owner_id,
            balance: wallet.balance,
            protocol: wallet.protocol.clone(),
            credentials: serde_json::json!({
                "derived_address": self.derive_address(owner_kind, owner_id, protocol),
                "provider_managed": true,
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

pub fn create_wallet_service() -> SharedWalletService {
    Arc::new(WalletService::new())
}
