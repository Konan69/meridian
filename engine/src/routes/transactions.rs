use axum::Json;
use axum::extract::State;
use std::sync::Arc;

use crate::AppState;
use crate::core::error::Result;
use crate::core::types::TransactionRecord;

pub async fn list_transactions(
    State(state): State<Arc<AppState>>,
) -> Result<Json<Vec<TransactionRecord>>> {
    let store = state.store.lock().unwrap();
    let transactions = store.get_transactions(100)?;
    Ok(Json(transactions))
}
