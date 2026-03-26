mod config;
mod core;
mod db;
mod protocols;
mod routes;

use axum::{
    Router,
    routing::{get, post},
};
use clap::Parser;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use tower_http::cors::CorsLayer;
use tracing_subscriber::EnvFilter;

use crate::core::types::{CheckoutSession, Product};
use crate::core::wallet::SharedWalletService;
use crate::db::Store;
use crate::protocols::ProtocolAdapter;

pub struct AppState {
    pub catalog: Arc<Vec<Product>>,
    pub sessions: Mutex<HashMap<String, CheckoutSession>>,
    pub protocols: HashMap<String, Box<dyn ProtocolAdapter>>,
    pub store: Mutex<Store>,
    pub wallet_service: SharedWalletService,
}

#[derive(Parser)]
#[command(name = "meridian-engine", about = "Agentic commerce simulation engine")]
struct Cli {
    #[arg(long, default_value = "4080")]
    port: u16,

    #[arg(long, default_value = "catalog.json")]
    catalog: String,

    #[arg(long, default_value = "meridian.db")]
    db: String,
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
        .with_env_filter(
            EnvFilter::from_default_env().add_directive("meridian_engine=info".parse().unwrap()),
        )
        .init();

    let cli = Cli::parse();

    // Initialize SQLite store
    let store = Store::new(&cli.db).expect("failed to open database");
    tracing::info!("opened SQLite database at {}", cli.db);

    // Load catalog
    let catalog = if std::path::Path::new(&cli.catalog).exists() {
        let data = std::fs::read_to_string(&cli.catalog).expect("failed to read catalog");
        serde_json::from_str(&data).expect("failed to parse catalog JSON")
    } else {
        tracing::info!("no catalog file found, using default catalog");
        default_catalog()
    };

    tracing::info!("loaded {} products", catalog.len());

    // Save products to DB
    for product in &catalog {
        store
            .save_product(product)
            .expect("failed to save product to DB");
    }
    tracing::info!("persisted {} products to SQLite", catalog.len());

    // Initialize protocol adapters with real credentials
    let cfg = config::load();
    tracing::info!(
        "x402 config: rpc={}, chain_id={}, pay_to={}",
        cfg.x402.rpc_url,
        cfg.x402.chain_id,
        cfg.x402.pay_to
    );
    tracing::info!(
        "stripe config: key={}...",
        cfg.stripe.secret_key.chars().take(10).collect::<String>()
    );
    tracing::info!("atxp config: coordinator={}", cfg.atxp.coordinator_url);
    tracing::warn!(
        "strict live mode enabled: all five protocols are required and must resolve to real adapters"
    );

    // Initialize wallet service with master seed for per-agent key derivation
    let wallet_master_seed =
        std::env::var("WALLET_MASTER_SEED").expect("WALLET_MASTER_SEED must be set");
    let wallet_service = crate::core::wallet::create_wallet_service(&wallet_master_seed);
    tracing::info!("wallet service initialized with master seed");

    let mut protocol_map: HashMap<String, Box<dyn ProtocolAdapter>> = HashMap::new();
    protocol_map.insert(
        "x402".into(),
        Box::new(protocols::x402::X402Adapter::new(cfg.clone())),
    );

    let acp_adapter = protocols::remote::RemoteAdapter::new("acp", &cfg.remote_adapters.acp_url)
        .await
        .expect("failed to initialize ACP remote adapter");
    protocol_map.insert("acp".into(), Box::new(acp_adapter));

    let mpp_adapter = protocols::remote::RemoteAdapter::new("mpp", &cfg.remote_adapters.mpp_url)
        .await
        .expect("failed to initialize MPP remote adapter");
    protocol_map.insert("mpp".into(), Box::new(mpp_adapter));

    let ap2_adapter = protocols::remote::RemoteAdapter::new("ap2", &cfg.remote_adapters.ap2_url)
        .await
        .expect("failed to initialize AP2 remote adapter");
    protocol_map.insert("ap2".into(), Box::new(ap2_adapter));

    let atxp_adapter = protocols::remote::RemoteAdapter::new("atxp", &cfg.remote_adapters.atxp_url)
        .await
        .expect("failed to initialize ATXP remote adapter");
    protocol_map.insert("atxp".into(), Box::new(atxp_adapter));

    tracing::info!(
        "initialized {} protocol adapters: {:?}",
        protocol_map.len(),
        protocol_map.keys().collect::<Vec<_>>()
    );
    assert_eq!(
        protocol_map.len(),
        5,
        "strict live mode requires acp, ap2, atxp, mpp, and x402 to all initialize"
    );

    let state = Arc::new(AppState {
        catalog: Arc::new(catalog),
        sessions: Mutex::new(HashMap::new()),
        protocols: protocol_map,
        store: Mutex::new(store),
        wallet_service,
    });

    let cors = if let Ok(origin) = std::env::var("CORS_ORIGIN") {
        tracing::info!("CORS enabled for origin: {}", origin);
        CorsLayer::new()
            .allow_origin(tower_http::cors::AllowOrigin::exact(
                origin.parse().unwrap(),
            ))
            .allow_methods(tower_http::cors::Any)
            .allow_headers(tower_http::cors::Any)
    } else {
        tracing::warn!("CORS_ORIGIN not set, defaulting to permissive (dev only!)");
        CorsLayer::permissive()
    };

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
        // Wallet management
        .route("/wallets", get(routes::wallet::list_wallets))
        .route("/wallets/balance", get(routes::wallet::total_balance))
        .route(
            "/wallets/{agent_id}/{protocol}",
            get(routes::wallet::get_wallet),
        )
        .route("/wallets", post(routes::wallet::create_wallet))
        // Transactions
        .route(
            "/transactions",
            get(routes::transactions::list_transactions),
        )
        // Metrics
        .route("/metrics", get(routes::metrics::get_metrics))
        // SSE event stream
        .route("/events", get(routes::events::event_stream))
        // Health
        .route("/health", get(|| async { "ok" }))
        .layer(cors)
        .with_state(state.clone());

    let addr = format!("0.0.0.0:{}", cli.port);
    tracing::info!("meridian engine listening on {addr}");
    tracing::info!(
        "protocols: {}",
        state
            .protocols
            .keys()
            .cloned()
            .collect::<Vec<_>>()
            .join(", ")
    );

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
