use axum::{
    Json,
    extract::{Path, State},
    http::StatusCode,
};
use serde::Deserialize;
use std::sync::Arc;
use uuid::Uuid;

use crate::AppState;
use crate::core::error::{EngineError, Result};
use crate::core::pricing;
use crate::core::types::*;

// ---------------------------------------------------------------------------
// Request types
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct CreateSessionRequest {
    pub items: Vec<ItemRequest>,
    pub buyer: Option<Buyer>,
    pub fulfillment_address: Option<Address>,
    pub protocol: String,
    pub agent_id: Option<String>,
}

#[derive(Deserialize)]
pub struct ItemRequest {
    pub id: String,
    pub quantity: u32,
}

#[derive(Deserialize)]
pub struct UpdateSessionRequest {
    pub items: Option<Vec<ItemRequest>>,
    pub buyer: Option<Buyer>,
    pub fulfillment_address: Option<Address>,
    pub selected_fulfillment_option_id: Option<String>,
}

#[derive(Deserialize)]
pub struct CompleteSessionRequest {
    pub buyer: Option<Buyer>,
    #[allow(dead_code)]
    pub payment_token: String,
    pub protocol: Option<String>,
    pub merchant: Option<String>,
}

// ---------------------------------------------------------------------------
// POST /checkout_sessions
// ---------------------------------------------------------------------------

pub async fn create_session(
    State(state): State<Arc<AppState>>,
    Json(req): Json<CreateSessionRequest>,
) -> Result<(StatusCode, Json<CheckoutSession>)> {
    if req.items.is_empty() {
        return Err(EngineError::InvalidRequest("items cannot be empty".into()));
    }

    // Validate all items have valid quantity
    for item in &req.items {
        if item.quantity == 0 {
            return Err(EngineError::InvalidRequest(format!(
                "quantity must be positive for product {}",
                item.id
            )));
        }
    }

    let protocol = req.protocol.as_str();
    if !state.protocols.contains_key(protocol) {
        return Err(EngineError::ProtocolError(format!(
            "unsupported protocol: {}. strict live mode currently supports: {}",
            protocol,
            state
                .protocols
                .keys()
                .cloned()
                .collect::<Vec<_>>()
                .join(", ")
        )));
    }
    let mut session = CheckoutSession::new(protocol, req.agent_id);

    // Resolve items against catalog with stock validation
    // NOTE: For simulation, we validate stock at request time but don't decrement
    // (catalog is static reference data, not live inventory)
    let mut line_items = Vec::new();
    for item in &req.items {
        let product = state
            .catalog
            .iter()
            .find(|p| p.id == item.id)
            .ok_or_else(|| EngineError::NotFound(format!("product {}", item.id)))?;

        // Stock validation at request time (simulates what would happen in real checkout)
        if item.quantity > product.available_quantity {
            return Err(EngineError::InvalidRequest(format!(
                "insufficient stock for {} (requested: {}, available: {})",
                product.name, item.quantity, product.available_quantity
            )));
        }

        let li_id = format!("li_{}", Uuid::new_v4().simple());
        line_items.push(pricing::calculate_line_item(product, item.quantity, &li_id));
    }

    session.line_items = line_items;
    session.buyer = req.buyer;
    session.fulfillment_address = req.fulfillment_address.clone();

    // Fulfillment options
    let needs_shipping = session.line_items.iter().any(|li| {
        state
            .catalog
            .iter()
            .find(|p| p.id == li.product_id)
            .map_or(false, |p| p.requires_shipping)
    });

    if needs_shipping {
        session.fulfillment_options = pricing::default_fulfillment_options();
    }

    // Determine status
    session.status = determine_status(&session, needs_shipping);

    // Calculate totals
    let fulfillment = session
        .selected_fulfillment_option_id
        .as_ref()
        .and_then(|id| session.fulfillment_options.iter().find(|f| f.id == *id));
    let addr_state = req.fulfillment_address.as_ref().map(|a| a.state.as_str());
    session.totals = pricing::calculate_totals(&session.line_items, fulfillment, addr_state);

    // Store session in memory
    state
        .sessions
        .lock()
        .unwrap()
        .insert(session.id.clone(), session.clone());

    // Persist session to SQLite
    {
        let store = state.store.lock().unwrap();
        let _ = store.save_session(&session);
    }

    Ok((StatusCode::CREATED, Json(session)))
}

// ---------------------------------------------------------------------------
// GET /checkout_sessions/:id
// ---------------------------------------------------------------------------

pub async fn get_session(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
) -> Result<Json<CheckoutSession>> {
    let sessions = state.sessions.lock().unwrap();
    sessions
        .get(&id)
        .cloned()
        .map(Json)
        .ok_or_else(|| EngineError::NotFound(format!("session {id}")))
}

// ---------------------------------------------------------------------------
// POST /checkout_sessions/:id (update)
// ---------------------------------------------------------------------------

pub async fn update_session(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
    Json(req): Json<UpdateSessionRequest>,
) -> Result<Json<CheckoutSession>> {
    let mut sessions = state.sessions.lock().unwrap();
    let session = sessions
        .get_mut(&id)
        .ok_or_else(|| EngineError::NotFound(format!("session {id}")))?;

    if session.status.is_terminal() {
        return Err(EngineError::SessionTerminal(format!(
            "session {id} is {:?}",
            session.status
        )));
    }

    // Update buyer
    if let Some(buyer) = req.buyer {
        session.buyer = Some(buyer);
    }

    // Update fulfillment address
    if let Some(addr) = req.fulfillment_address {
        session.fulfillment_address = Some(addr);
    }

    // Update items
    if let Some(items) = req.items {
        let mut line_items = Vec::new();
        for item in &items {
            let product = state
                .catalog
                .iter()
                .find(|p| p.id == item.id)
                .ok_or_else(|| EngineError::NotFound(format!("product {}", item.id)))?;
            let li_id = format!("li_{}", Uuid::new_v4().simple());
            line_items.push(pricing::calculate_line_item(product, item.quantity, &li_id));
        }
        session.line_items = line_items;
    }

    // Update fulfillment selection
    if let Some(fo_id) = req.selected_fulfillment_option_id {
        if session.fulfillment_options.iter().any(|f| f.id == fo_id) {
            session.selected_fulfillment_option_id = Some(fo_id);
        }
    }

    // Recalculate
    let needs_shipping = session.line_items.iter().any(|li| {
        state
            .catalog
            .iter()
            .find(|p| p.id == li.product_id)
            .map_or(false, |p| p.requires_shipping)
    });
    session.status = determine_status(session, needs_shipping);

    let fulfillment = session
        .selected_fulfillment_option_id
        .as_ref()
        .and_then(|id| session.fulfillment_options.iter().find(|f| f.id == *id));
    let addr_state = session
        .fulfillment_address
        .as_ref()
        .map(|a| a.state.as_str());
    session.totals = pricing::calculate_totals(&session.line_items, fulfillment, addr_state);
    session.updated_at = chrono::Utc::now();

    let result = session.clone();

    // Persist updated session to SQLite
    {
        let store = state.store.lock().unwrap();
        let _ = store.save_session(&result);
    }

    Ok(Json(result))
}

// ---------------------------------------------------------------------------
// POST /checkout_sessions/:id/complete
// ---------------------------------------------------------------------------

pub async fn complete_session(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
    Json(req): Json<CompleteSessionRequest>,
) -> Result<Json<CheckoutSession>> {
    // Extract what we need from the session, then drop the lock before async
    let (total, protocol_name, currency, merchant_name) = {
        let sessions = state.sessions.lock().unwrap();
        let session = sessions
            .get(&id)
            .ok_or_else(|| EngineError::NotFound(format!("session {id}")))?;

        if session.status == SessionStatus::Completed {
            return Err(EngineError::SessionTerminal("already completed".into()));
        }
        if session.status == SessionStatus::Canceled {
            return Err(EngineError::SessionTerminal("session canceled".into()));
        }
        if session.status == SessionStatus::NotReadyForPayment {
            return Err(EngineError::InvalidRequest(
                "session not ready for payment".into(),
            ));
        }

        let total = session
            .totals
            .iter()
            .find(|t| t.total_type == "total")
            .map(|t| t.amount)
            .unwrap_or(0);
        let protocol = req
            .protocol
            .clone()
            .unwrap_or_else(|| session.protocol.clone());
        let currency = session.currency.clone();
        let merchant = req
            .merchant
            .clone()
            .unwrap_or_else(|| "meridian_merchant".to_string());

        (total, protocol, currency, merchant)
    }; // lock dropped here

    // Get protocol adapter and run FULL protocol flow: authorize → pay
    let adapter = state
        .protocols
        .get(&protocol_name)
        .ok_or_else(|| EngineError::ProtocolError(format!("unknown protocol: {protocol_name}")))?;

    // 1. Authorize using a real externally funded wallet.
    // NOTE: agent_id should come from session, not from payment_token (security)
    let agent_id = state
        .sessions
        .lock()
        .unwrap()
        .get(&id)
        .and_then(|s| s.agent_id.clone())
        .unwrap_or_else(|| "unknown_agent".to_string());

    // No treasury auto-topups or synthetic balances in strict live mode.
    let wallet = state
        .wallet_service
        .to_actor_wallet("agent", &agent_id, &protocol_name)
        .map_err(|e| EngineError::PaymentDeclined(format!("wallet error: {}", e)))?;

    let constraints = crate::core::types::SpendingConstraints {
        max_amount: total,
        currency: currency.clone(),
        merchants: Some(vec![merchant_name.clone()]),
        categories: None,
        expires_at: chrono::Utc::now() + chrono::Duration::hours(1),
        requires_confirmation: false,
    };
    let auth_token = adapter.authorize(&wallet, &constraints).await?;

    // 3. Pay — validation and settlement happen on the real rail. Any insufficient-funds
    // failure must come from the rail itself, not an internal shadow balance.
    let settlement_target = auth_token
        .protocol_data
        .get("pay_to")
        .and_then(|value| value.as_str())
        .unwrap_or(&merchant_name)
        .to_string();
    let payment = adapter.pay(&auth_token, total, &settlement_target).await?;

    // Re-acquire lock and finalize
    let mut sessions = state.sessions.lock().unwrap();
    let session = sessions
        .get_mut(&id)
        .ok_or_else(|| EngineError::NotFound(format!("session {id}")))?;

    if let Some(buyer) = req.buyer {
        session.buyer = Some(buyer);
    }

    session.status = SessionStatus::Completed;
    session.order = Some(Order::from_session(&session.id));
    session.updated_at = chrono::Utc::now();

    // Add payment details as a message so the Python sim can read fee/execution time
    session.messages.push(Message {
        msg_type: "payment_result".into(),
        code: Some(payment.protocol.clone()),
        content: serde_json::json!({
            "payment_id": payment.payment_id,
            "fee_cents": payment.fee,
            "execution_us": payment.execution_us,
            "status": payment.status,
            "merchant": merchant_name,
        })
        .to_string(),
    });

    let result = session.clone();

    // Persist session and transaction to SQLite
    {
        let store = state.store.lock().unwrap();
        let _ = store.save_session(&result);

        let tx_record = TransactionRecord {
            id: payment.payment_id.clone(),
            session_id: id.clone(),
            protocol: payment.protocol.clone(),
            agent_id: result.agent_id.clone().unwrap_or_default(),
            amount: payment.amount,
            fee: payment.fee,
            execution_us: payment.execution_us,
            status: format!("{:?}", payment.status),
            created_at: chrono::Utc::now(),
        };
        let _ = store.save_transaction(&tx_record);
    }

    Ok(Json(result))
}

// ---------------------------------------------------------------------------
// POST /checkout_sessions/:id/cancel
// ---------------------------------------------------------------------------

pub async fn cancel_session(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
) -> Result<Json<CheckoutSession>> {
    let mut sessions = state.sessions.lock().unwrap();
    let session = sessions
        .get_mut(&id)
        .ok_or_else(|| EngineError::NotFound(format!("session {id}")))?;

    if session.status == SessionStatus::Completed {
        return Err(EngineError::SessionTerminal(
            "cannot cancel completed session".into(),
        ));
    }

    session.status = SessionStatus::Canceled;
    session.updated_at = chrono::Utc::now();

    let result = session.clone();

    // Persist canceled session to SQLite
    {
        let store = state.store.lock().unwrap();
        let _ = store.save_session(&result);
    }

    Ok(Json(result))
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn determine_status(session: &CheckoutSession, needs_shipping: bool) -> SessionStatus {
    if session.line_items.is_empty() {
        return SessionStatus::NotReadyForPayment;
    }

    if needs_shipping
        && (session.fulfillment_address.is_none()
            || session.selected_fulfillment_option_id.is_none())
    {
        return SessionStatus::NotReadyForPayment;
    }

    SessionStatus::ReadyForPayment
}
