use std::sync::Arc;
use tokio::sync::RwLock;

#[derive(Debug, Clone)]
pub struct Config {
    pub x402: X402Config,
    pub stripe: StripeConfig,
    pub ap2: Ap2Config,
    pub atxp: AtxpConfig,
    pub public_base_url: String,
    pub remote_adapters: RemoteAdaptersConfig,
}

#[derive(Debug, Clone)]
pub struct X402Config {
    pub rpc_url: String,
    pub master_seed: String,
    pub usdc_contract: String,
    pub chain_id: u64,
    pub pay_to: String,
}

#[derive(Debug, Clone)]
pub struct StripeConfig {
    pub secret_key: String,
}

#[derive(Debug, Clone)]
pub struct Ap2Config {
    pub rpc_url: String,
    pub master_seed: String,
}

#[derive(Debug, Clone)]
pub struct AtxpConfig {
    pub coordinator_url: String,
}

#[derive(Debug, Clone)]
pub struct RemoteAdaptersConfig {
    pub acp_url: String,
    pub mpp_url: String,
    pub ap2_url: String,
    pub atxp_url: String,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            x402: X402Config {
                rpc_url: std::env::var("X402_RPC_URL").expect("X402_RPC_URL must be set"),
                master_seed: std::env::var("X402_MASTER_SEED")
                    .expect("X402_MASTER_SEED must be set"),
                usdc_contract: "0x036CbD53842c5426634e7929541eC2318f3dCF7e".into(),
                chain_id: 84532,
                pay_to: std::env::var("X402_PAY_TO").expect("X402_PAY_TO must be set"),
            },
            stripe: StripeConfig {
                secret_key: std::env::var("STRIPE_SECRET_KEY")
                    .expect("STRIPE_SECRET_KEY must be set"),
            },
            ap2: Ap2Config {
                rpc_url: std::env::var("AP2_RPC_URL").expect("AP2_RPC_URL must be set"),
                master_seed: std::env::var("AP2_MASTER_SEED").expect("AP2_MASTER_SEED must be set"),
            },
            atxp: AtxpConfig {
                coordinator_url: std::env::var("ATXP_COORDINATOR_URL")
                    .expect("ATXP_COORDINATOR_URL must be set"),
            },
            public_base_url: std::env::var("MERIDIAN_PUBLIC_BASE_URL")
                .unwrap_or_else(|_| "http://localhost:4080".into()),
            remote_adapters: RemoteAdaptersConfig {
                acp_url: std::env::var("ACP_ADAPTER_URL").expect("ACP_ADAPTER_URL must be set"),
                mpp_url: std::env::var("MPP_ADAPTER_URL").expect("MPP_ADAPTER_URL must be set"),
                ap2_url: std::env::var("AP2_ADAPTER_URL").expect("AP2_ADAPTER_URL must be set"),
                atxp_url: std::env::var("ATXP_ADAPTER_URL").expect("ATXP_ADAPTER_URL must be set"),
            },
        }
    }
}

pub type SharedConfig = Arc<RwLock<Config>>;

pub fn load() -> Config {
    Config::default()
}
