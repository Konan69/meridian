#[derive(Debug, Clone)]
pub struct Config {
    pub x402: X402Config,
    pub public_base_url: String,
    pub cdp_service_url: String,
    pub stripe_service_url: String,
    pub atxp_service_url: String,
    pub ap2_service_url: String,
}

#[derive(Debug, Clone)]
pub struct X402Config {
    pub rpc_url: String,
    pub usdc_contract: String,
    pub chain_id: u64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            x402: X402Config {
                rpc_url: std::env::var("X402_RPC_URL").expect("X402_RPC_URL must be set"),
                usdc_contract: "0x036CbD53842c5426634e7929541eC2318f3dCF7e".into(),
                chain_id: 84532,
            },
            public_base_url: std::env::var("MERIDIAN_PUBLIC_BASE_URL")
                .unwrap_or_else(|_| "http://localhost:4080".into()),
            cdp_service_url: std::env::var("CDP_SERVICE_URL")
                .expect("CDP_SERVICE_URL must be set"),
            stripe_service_url: std::env::var("STRIPE_SERVICE_URL")
                .unwrap_or_else(|_| "http://localhost:3020".into()),
            atxp_service_url: std::env::var("ATXP_SERVICE_URL")
                .unwrap_or_else(|_| "http://localhost:3010".into()),
            ap2_service_url: std::env::var("AP2_SERVICE_URL")
                .unwrap_or_else(|_| "http://localhost:3040".into()),
        }
    }
}

pub fn load() -> Config {
    Config::default()
}
