use axum::{Json, extract::State};
use std::sync::Arc;

use crate::AppState;
use crate::core::types::Product;

/// GET /products — return the product catalog
/// Note: catalog.clone() copies the Vec pointer + length + capacity (cheap for read-only)
/// but does allocate a new Vec header. For high-frequency calls, consider
/// making catalog an Arc<Vec<Product>> in AppState.
pub async fn list_products(State(state): State<Arc<AppState>>) -> Json<Vec<Product>> {
    Json((*state.catalog).clone())
}
