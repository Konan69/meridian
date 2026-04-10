use axum::{
    Json,
    extract::{Path, State},
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

use crate::AppState;
use crate::core::error::Result;
use crate::core::wallet::WalletInfo;

#[derive(Serialize)]
pub struct WalletResponse {
    pub owner_kind: String,
    pub owner_id: String,
    pub protocol: String,
    pub balance: u64,
    pub address: Option<String>,
}

impl From<WalletInfo> for WalletResponse {
    fn from(w: WalletInfo) -> Self {
        Self {
            owner_kind: w.owner_kind,
            owner_id: w.owner_id,
            protocol: w.protocol,
            balance: w.balance,
            address: w.address,
        }
    }
}

#[derive(Deserialize)]
pub struct CreateWalletRequest {
    pub owner_kind: String,
    pub owner_id: String,
    pub protocol: String,
    #[serde(default = "default_balance")]
    pub initial_balance: u64,
}

fn default_balance() -> u64 {
    0
}

pub async fn create_wallet(
    State(state): State<Arc<AppState>>,
    Json(req): Json<CreateWalletRequest>,
) -> Result<Json<WalletResponse>> {
    let wallet =
        state
            .wallet_service
            .create_wallet(&req.owner_kind, &req.owner_id, &req.protocol, req.initial_balance)?;

    Ok(Json(WalletResponse::from(wallet)))
}

pub async fn get_wallet(
    State(state): State<Arc<AppState>>,
    Path((owner_kind, owner_id, protocol)): Path<(String, String, String)>,
) -> Result<Json<WalletResponse>> {
    let wallet = state.wallet_service.get_wallet(&owner_kind, &owner_id, &protocol)?;
    Ok(Json(WalletResponse::from(wallet)))
}

pub async fn list_wallets(State(state): State<Arc<AppState>>) -> Result<Json<Vec<WalletResponse>>> {
    let wallets = state.wallet_service.list_wallets();
    Ok(Json(
        wallets.into_iter().map(WalletResponse::from).collect(),
    ))
}

#[derive(Serialize)]
pub struct BalanceResponse {
    pub total_balance: u64,
    pub wallet_count: usize,
}

pub async fn total_balance(State(state): State<Arc<AppState>>) -> Result<Json<BalanceResponse>> {
    Ok(Json(BalanceResponse {
        total_balance: state.wallet_service.total_balance(),
        wallet_count: state.wallet_service.list_wallets().len(),
    }))
}
