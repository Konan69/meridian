mod core;
mod protocols;
mod routes;

use axum::{
    routing::{get, post},
    Router,
};
use clap::Parser;
// No Docker needed. All protocol logic runs in-process.
// ACP: SPT lifecycle in Rust (ported from agentic-commerce-demo)
// x402: Real ECDSA secp256k1 via k256 crate
// AP2: Real ECDSA double-signing via k256 crate
// MPP: Session budget tracking + ECDSA receipts
// ATXP: Constraint engine with SHA256 mandates
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use tower_http::cors::CorsLayer;
use tracing_subscriber::EnvFilter;

use crate::core::types::{CheckoutSession, Product};
use crate::protocols::ProtocolAdapter;

pub struct AppState {
    pub catalog: Vec<Product>,
    pub sessions: Mutex<HashMap<String, CheckoutSession>>,
    pub protocols: HashMap<String, Box<dyn ProtocolAdapter>>,
}

#[derive(Parser)]
#[command(name = "meridian-engine", about = "Agentic commerce simulation engine")]
struct Cli {
    #[arg(long, default_value = "4080")]
    port: u16,

    #[arg(long, default_value = "catalog.json")]
    catalog: String,
}

fn default_catalog() -> Vec<Product> {
    vec![
        Product {
            id: "prod_running_shoes".into(),
            name: "Ultraboost Running Shoes".into(),
            description: "Lightweight responsive running shoes with Boost midsole".into(),
            base_price: 18000, // $180.00
            category: "footwear".into(),
            available_quantity: 500,
            requires_shipping: true,
            image_url: None,
        },
        Product {
            id: "prod_wireless_earbuds".into(),
            name: "AirPods Pro 3".into(),
            description: "Active noise cancelling wireless earbuds with spatial audio".into(),
            base_price: 24900, // $249.00
            category: "electronics".into(),
            available_quantity: 1000,
            requires_shipping: true,
            image_url: None,
        },
        Product {
            id: "prod_coffee_beans".into(),
            name: "Ethiopian Yirgacheffe Single Origin".into(),
            description: "Light roast single origin coffee beans, 12oz bag".into(),
            base_price: 1800, // $18.00
            category: "food".into(),
            available_quantity: 2000,
            requires_shipping: true,
            image_url: None,
        },
        Product {
            id: "prod_api_credits".into(),
            name: "API Credits Pack (1000)".into(),
            description: "1000 API credits for data access".into(),
            base_price: 500, // $5.00
            category: "digital".into(),
            available_quantity: 999999,
            requires_shipping: false,
            image_url: None,
        },
        Product {
            id: "prod_data_report".into(),
            name: "Market Analysis Report Q1 2026".into(),
            description: "Comprehensive market analysis with AI-generated insights".into(),
            base_price: 50, // $0.50 — micropayment test product
            category: "digital".into(),
            available_quantity: 999999,
            requires_shipping: false,
            image_url: None,
        },
        Product {
            id: "prod_premium_widget".into(),
            name: "Premium Widget Pro".into(),
            description: "Industrial-grade widget with titanium finish".into(),
            base_price: 4500, // $45.00
            category: "hardware".into(),
            available_quantity: 300,
            requires_shipping: true,
            image_url: None,
        },
    ]
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env().add_directive("meridian_engine=info".parse().unwrap()))
        .init();

    let cli = Cli::parse();

    // Load catalog
    let catalog = if std::path::Path::new(&cli.catalog).exists() {
        let data = std::fs::read_to_string(&cli.catalog).expect("failed to read catalog");
        serde_json::from_str(&data).expect("failed to parse catalog JSON")
    } else {
        tracing::info!("no catalog file found, using default catalog");
        default_catalog()
    };

    tracing::info!("loaded {} products", catalog.len());

    // Initialize protocol adapters
    let mut protocol_map: HashMap<String, Box<dyn ProtocolAdapter>> = HashMap::new();
    protocol_map.insert("acp".into(), Box::new(protocols::acp::AcpAdapter::new()));
    protocol_map.insert("x402".into(), Box::new(protocols::x402::X402Adapter::new()));
    protocol_map.insert("ap2".into(), Box::new(protocols::ap2::Ap2Adapter::new()));
    protocol_map.insert("mpp".into(), Box::new(protocols::mpp::MppAdapter::new()));
    protocol_map.insert("atxp".into(), Box::new(protocols::atxp::AtxpAdapter::new()));

    tracing::info!(
        "initialized {} protocol adapters: {:?}",
        protocol_map.len(),
        protocol_map.keys().collect::<Vec<_>>()
    );

    let state = Arc::new(AppState {
        catalog,
        sessions: Mutex::new(HashMap::new()),
        protocols: protocol_map,
    });

    let app = Router::new()
        // Product catalog
        .route("/products", get(routes::products::list_products))
        // Checkout sessions
        .route("/checkout_sessions", post(routes::checkout::create_session))
        .route(
            "/checkout_sessions/{id}",
            get(routes::checkout::get_session).post(routes::checkout::update_session),
        )
        .route(
            "/checkout_sessions/{id}/complete",
            post(routes::checkout::complete_session),
        )
        .route(
            "/checkout_sessions/{id}/cancel",
            post(routes::checkout::cancel_session),
        )
        // Metrics
        .route("/metrics", get(routes::metrics::get_metrics))
        // SSE event stream
        .route("/events", get(routes::events::event_stream))
        // Health
        .route("/health", get(|| async { "ok" }))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr = format!("0.0.0.0:{}", cli.port);
    tracing::info!("meridian engine listening on {addr}");
    tracing::info!("protocols: ACP, AP2, x402, MPP, ATXP");

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
