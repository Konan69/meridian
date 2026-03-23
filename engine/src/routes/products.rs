use axum::{extract::State, Json};
use std::sync::Arc;

use crate::core::types::Product;
use crate::AppState;

/// GET /products — return the product catalog
pub async fn list_products(State(state): State<Arc<AppState>>) -> Json<Vec<Product>> {
    Json(state.catalog.clone())
}
