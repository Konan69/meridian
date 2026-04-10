use std::collections::HashMap;

use crate::config::Config;
use crate::core::types::ProtocolCapability;

use super::{ProtocolAdapter, ap2, atxp, mpp, x402};

pub struct RuntimeCatalog {
    pub protocols: HashMap<String, Box<dyn ProtocolAdapter>>,
    pub capabilities: Vec<ProtocolCapability>,
}

async fn service_ok(url: &str) -> bool {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .unwrap_or_default();
    client
        .get(url)
        .send()
        .await
        .map(|response| response.status().is_success())
        .unwrap_or(false)
}

pub async fn build_runtime_catalog(cfg: &Config) -> RuntimeCatalog {
    let mut protocols: HashMap<String, Box<dyn ProtocolAdapter>> = HashMap::new();
    let mut capabilities: Vec<ProtocolCapability> = Vec::new();

    protocols.insert("x402".into(), Box::new(x402::X402Adapter::new(cfg.clone())));
    capabilities.push(ProtocolCapability {
        protocol: "x402".into(),
        runtime_ready: true,
        integration: "in_engine".into(),
        reason: "live facilitator-backed engine integration".into(),
    });

    let atxp_health = atxp::AtxpAdapter::health_status(cfg).await;
    if atxp_health.runtime_ready {
        protocols.insert("atxp".into(), Box::new(atxp::AtxpAdapter::new(cfg.clone())));
        capabilities.push(ProtocolCapability {
            protocol: "atxp".into(),
            runtime_ready: true,
            integration: "in_engine".into(),
            reason: atxp_health.reason.clone(),
        });
    } else {
        capabilities.push(ProtocolCapability {
            protocol: "atxp".into(),
            runtime_ready: false,
            integration: "service_only".into(),
            reason: atxp_health.reason.clone(),
        });
    }

    let mpp_health = mpp::MppAdapter::health_status(cfg).await;
    if mpp_health.runtime_ready {
        protocols.insert("mpp".into(), Box::new(mpp::MppAdapter::new(cfg.clone())));
        capabilities.push(ProtocolCapability {
            protocol: "mpp".into(),
            runtime_ready: true,
            integration: "in_engine".into(),
            reason: mpp_health.reason.clone(),
        });
    } else {
        capabilities.push(ProtocolCapability {
            protocol: "mpp".into(),
            runtime_ready: false,
            integration: if service_ok(&format!(
                "{}/health",
                cfg.stripe_service_url.trim_end_matches('/')
            ))
            .await
            {
                "service_only".into()
            } else {
                "unavailable".into()
            },
            reason: mpp_health.reason.clone(),
        });
    }

    let ap2_health = ap2::Ap2Adapter::health_status(cfg).await;
    if ap2_health.runtime_ready {
        protocols.insert("ap2".into(), Box::new(ap2::Ap2Adapter::new(cfg.clone())));
        capabilities.push(ProtocolCapability {
            protocol: "ap2".into(),
            runtime_ready: true,
            integration: "in_engine".into(),
            reason: ap2_health.reason.clone(),
        });
    } else {
        capabilities.push(ProtocolCapability {
            protocol: "ap2".into(),
            runtime_ready: false,
            integration: "service_only".into(),
            reason: ap2_health.reason.clone(),
        });
    }

    capabilities.push(ProtocolCapability {
        protocol: "acp".into(),
        runtime_ready: false,
        integration: "not_integrated".into(),
        reason: "ACP remains a seller-side protocol surface and is not wired back into the runtime yet".into(),
    });

    RuntimeCatalog {
        protocols,
        capabilities,
    }
}
