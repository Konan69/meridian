use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// All monetary amounts are in minor units (cents for USD).
/// $20.00 = 2000 cents. No floating point anywhere.
pub type Cents = u64;

// ---------------------------------------------------------------------------
// Checkout Session
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum SessionStatus {
    NotReadyForPayment,
    ReadyForPayment,
    Completed,
    Canceled,
}

impl SessionStatus {
    pub fn is_terminal(&self) -> bool {
        matches!(self, Self::Completed | Self::Canceled)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckoutSession {
    pub id: String,
    pub status: SessionStatus,
    pub currency: String,
    pub buyer: Option<Buyer>,
    pub line_items: Vec<LineItem>,
    pub fulfillment_address: Option<Address>,
    pub fulfillment_options: Vec<FulfillmentOption>,
    pub selected_fulfillment_option_id: Option<String>,
    pub totals: Vec<Total>,
    pub messages: Vec<Message>,
    pub links: Vec<Link>,
    pub order: Option<Order>,
    pub protocol: String,
    pub agent_id: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

impl CheckoutSession {
    pub fn new(protocol: &str, agent_id: Option<String>) -> Self {
        let id = format!("cs_{}", Uuid::new_v4().simple());
        let now = Utc::now();
        Self {
            id,
            status: SessionStatus::NotReadyForPayment,
            currency: "usd".into(),
            buyer: None,
            line_items: Vec::new(),
            fulfillment_address: None,
            fulfillment_options: Vec::new(),
            selected_fulfillment_option_id: None,
            totals: Vec::new(),
            messages: Vec::new(),
            links: vec![
                Link {
                    link_type: "terms_of_use".into(),
                    url: "https://meridian.dev/terms".into(),
                },
                Link {
                    link_type: "privacy_policy".into(),
                    url: "https://meridian.dev/privacy".into(),
                },
            ],
            order: None,
            protocol: protocol.into(),
            agent_id,
            created_at: now,
            updated_at: now,
        }
    }
}

// ---------------------------------------------------------------------------
// Buyer & Address
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Buyer {
    pub first_name: String,
    pub last_name: String,
    pub email: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub phone_number: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Address {
    pub name: String,
    pub line_one: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line_two: Option<String>,
    pub city: String,
    pub state: String,
    pub country: String,
    pub postal_code: String,
}

// ---------------------------------------------------------------------------
// Line Items & Products
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LineItem {
    pub id: String,
    pub product_id: String,
    pub quantity: u32,
    pub base_amount: Cents,
    pub discount: Cents,
    pub subtotal: Cents,
    pub tax: Cents,
    pub total: Cents,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Product {
    pub id: String,
    pub name: String,
    pub description: String,
    pub base_price: Cents,
    pub category: String,
    pub available_quantity: u32,
    pub requires_shipping: bool,
    pub image_url: Option<String>,
}

// ---------------------------------------------------------------------------
// Fulfillment
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FulfillmentOption {
    pub id: String,
    #[serde(rename = "type")]
    pub fulfillment_type: String,
    pub title: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subtitle: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub carrier: Option<String>,
    pub subtotal: Cents,
    pub tax: Cents,
    pub total: Cents,
}

// ---------------------------------------------------------------------------
// Totals
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Total {
    #[serde(rename = "type")]
    pub total_type: String,
    pub display_text: String,
    pub amount: Cents,
}

// ---------------------------------------------------------------------------
// Messages & Links
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    #[serde(rename = "type")]
    pub msg_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code: Option<String>,
    pub content: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Link {
    #[serde(rename = "type")]
    pub link_type: String,
    pub url: String,
}

// ---------------------------------------------------------------------------
// Orders
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    pub id: String,
    pub checkout_session_id: String,
    pub permalink_url: String,
    pub created_at: DateTime<Utc>,
}

impl Order {
    pub fn from_session(session_id: &str) -> Self {
        let id = format!("order_{}", Uuid::new_v4().simple());
        Self {
            id: id.clone(),
            checkout_session_id: session_id.into(),
            permalink_url: format!("https://meridian.dev/orders/{id}"),
            created_at: Utc::now(),
        }
    }
}

// ---------------------------------------------------------------------------
// Transaction Record (persisted to SQLite)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransactionRecord {
    pub id: String,
    pub session_id: String,
    pub protocol: String,
    pub agent_id: String,
    pub amount: Cents,
    pub fee: Cents,
    pub execution_us: u64,
    pub status: String,
    pub created_at: DateTime<Utc>,
}

// Payment types (VaultToken, PaymentIntent) are managed internally
// by the protocol adapters — ACP keeps its own vault in acp.rs,
// x402 signs per-request, etc. No shared payment types needed here.

// ---------------------------------------------------------------------------
// Agent Wallet (protocol-agnostic)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentWallet {
    pub agent_id: String,
    pub balance: Cents,
    pub protocol: String,
    /// For ACP: card details. For x402: USDC wallet address. For AP2: VDC credentials.
    pub credentials: serde_json::Value,
}

// ---------------------------------------------------------------------------
// Spending Constraints (maps to AP2 IntentMandate / ATXP Mandate / ACP SPT scope)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpendingConstraints {
    pub max_amount: Cents,
    pub currency: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub merchants: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub categories: Option<Vec<String>>,
    pub expires_at: DateTime<Utc>,
    /// false = agent can buy autonomously (AP2 IntentMandate style)
    /// true = requires explicit cart confirmation (AP2 CartMandate style)
    pub requires_confirmation: bool,
}

// ---------------------------------------------------------------------------
// Protocol Metrics
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ProtocolMetrics {
    pub protocol: String,
    pub total_transactions: u64,
    pub successful_transactions: u64,
    pub failed_transactions: u64,
    pub total_volume_cents: u64,
    pub total_fees_cents: u64,
    pub avg_settlement_ms: f64,
    pub avg_authorization_ms: f64,
    pub micropayment_count: u64,
    pub refund_count: u64,
}
