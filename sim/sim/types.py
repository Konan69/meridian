"""Core types for the Meridian simulation layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Protocol(str, Enum):
    ACP = "acp"
    AP2 = "ap2"
    X402 = "x402"
    MPP = "mpp"
    ATXP = "atxp"


class AgentRole(str, Enum):
    BUYER = "buyer"
    MERCHANT = "merchant"
    OPERATOR = "operator"


class BalanceDomain(str, Enum):
    BASE_USDC = "base_usdc"
    SOLANA_USDC = "solana_usdc"
    TEMPO_USD = "tempo_usd"
    STRIPE_INTERNAL_USD = "stripe_internal_usd"
    GATEWAY_UNIFIED_USDC = "gateway_unified_usdc"


class SettlementPrimitive(str, Enum):
    DIRECT_SAME_DOMAIN = "direct_same_domain"
    BATCHED_NANOPAYMENT = "batched_nanopayment"
    TEMPO_SESSION = "tempo_session"
    STRIPE_INTERNAL_CHECKOUT = "stripe_internal_checkout"
    GATEWAY_UNIFIED = "gateway_unified"
    CCTP_TRANSFER = "cctp_transfer"
    LIFI_ROUTED = "lifi_routed"


class WorkloadType(str, Enum):
    API_MICRO = "api_micro"
    CONSUMER_CHECKOUT = "consumer_checkout"
    TREASURY_REBALANCE = "treasury_rebalance"


PROTOCOL_FEE_FORMULAS = {
    Protocol.ACP: lambda amount: (amount * 29 // 1000) + 30,
    Protocol.AP2: lambda amount: (amount * 25 // 1000) + 20,
    Protocol.X402: lambda amount: max(amount // 1000, 1),
    Protocol.MPP: lambda amount: max((amount * 15 // 1000) + 5, 1),
    Protocol.ATXP: lambda amount: max(amount * 5 // 1000, 1),
}

PROTOCOL_TRAITS = {
    Protocol.ACP: {
        "supports_micropay": False,
        "min_practical": 1000,
        "settlement_ms": 2000,
        "autonomy": 0.6,
    },
    Protocol.AP2: {
        "supports_micropay": False,
        "min_practical": 800,
        "settlement_ms": 3000,
        "autonomy": 0.5,
    },
    Protocol.X402: {
        "supports_micropay": True,
        "min_practical": 1,
        "settlement_ms": 200,
        "autonomy": 1.0,
    },
    Protocol.MPP: {
        "supports_micropay": True,
        "min_practical": 1,
        "settlement_ms": 500,
        "autonomy": 0.8,
    },
    Protocol.ATXP: {
        "supports_micropay": True,
        "min_practical": 1,
        "settlement_ms": 150,
        "autonomy": 0.9,
    },
}

PROTOCOL_FIXED_COST_CENTS = {
    Protocol.ACP: 35_000,
    Protocol.AP2: 28_000,
    Protocol.X402: 8_000,
    Protocol.MPP: 14_000,
    Protocol.ATXP: 10_000,
}

PROTOCOL_CAPACITY_PER_ROUND = {
    Protocol.ACP: 18,
    Protocol.AP2: 15,
    Protocol.X402: 55,
    Protocol.MPP: 42,
    Protocol.ATXP: 48,
}

PROTOCOL_PRIMITIVE_SUPPORT = {
    Protocol.X402: {
        SettlementPrimitive.DIRECT_SAME_DOMAIN,
        SettlementPrimitive.BATCHED_NANOPAYMENT,
    },
    Protocol.MPP: {
        SettlementPrimitive.TEMPO_SESSION,
        SettlementPrimitive.STRIPE_INTERNAL_CHECKOUT,
    },
    Protocol.ACP: {
        SettlementPrimitive.STRIPE_INTERNAL_CHECKOUT,
    },
    Protocol.AP2: {
        SettlementPrimitive.DIRECT_SAME_DOMAIN,
        SettlementPrimitive.CCTP_TRANSFER,
        SettlementPrimitive.LIFI_ROUTED,
    },
    Protocol.ATXP: {
        SettlementPrimitive.DIRECT_SAME_DOMAIN,
        SettlementPrimitive.LIFI_ROUTED,
    },
}

PROTOCOL_PREFERRED_WORKLOADS = {
    Protocol.X402: {WorkloadType.API_MICRO, WorkloadType.CONSUMER_CHECKOUT},
    Protocol.MPP: {WorkloadType.API_MICRO, WorkloadType.CONSUMER_CHECKOUT},
    Protocol.ACP: {WorkloadType.CONSUMER_CHECKOUT},
    Protocol.AP2: {WorkloadType.CONSUMER_CHECKOUT, WorkloadType.TREASURY_REBALANCE},
    Protocol.ATXP: {WorkloadType.API_MICRO, WorkloadType.TREASURY_REBALANCE},
}

DOMAIN_LABELS = {
    BalanceDomain.BASE_USDC: "Base USDC",
    BalanceDomain.SOLANA_USDC: "Solana USDC",
    BalanceDomain.TEMPO_USD: "Tempo USD",
    BalanceDomain.STRIPE_INTERNAL_USD: "Stripe Internal USD",
    BalanceDomain.GATEWAY_UNIFIED_USDC: "Gateway Unified USDC",
}

US_STATES = [
    ("CA", "San Francisco", "94105"),
    ("NY", "New York", "10001"),
    ("TX", "Austin", "73301"),
    ("WA", "Seattle", "98101"),
    ("IL", "Chicago", "60601"),
    ("FL", "Miami", "33101"),
    ("CO", "Denver", "80201"),
    ("MA", "Boston", "02101"),
    ("GA", "Atlanta", "30301"),
    ("OR", "Portland", "97201"),
]


@dataclass
class StableBalanceBucket:
    owner_kind: AgentRole
    owner_id: str
    domain: BalanceDomain
    asset: str = "USDC"
    available_cents: int = 0
    reserved_cents: int = 0
    pending_in_cents: int = 0
    pending_out_cents: int = 0


@dataclass
class TreasuryPolicy:
    preferred_settlement_domain: BalanceDomain
    accepted_settlement_domains: list[BalanceDomain]
    rebalance_threshold_cents: int
    rebalance_target_mix: dict[str, float]
    working_capital_cents: int


@dataclass
class SettlementReservation:
    reservation_id: str
    owner_kind: AgentRole
    owner_id: str
    source_domain: BalanceDomain
    amount_cents: int
    reserved_total_cents: int
    protocol: Protocol
    workload_type: WorkloadType
    route_id: str
    primitive: SettlementPrimitive
    round_num: int


@dataclass
class RouteSpec:
    route_id: str
    source_domain: BalanceDomain
    target_domain: BalanceDomain
    primitive: SettlementPrimitive
    supported_protocols: list[Protocol]
    fee_bps: int
    fixed_fee_cents: int
    latency_ms: int
    capacity_cents_per_round: int
    base_fail_prob: float


@dataclass
class RouteExecutionRecord:
    route_id: str
    protocol: Protocol
    primitive: SettlementPrimitive
    source_domain: BalanceDomain
    target_domain: BalanceDomain
    amount_cents: int
    route_fee_cents: int
    protocol_fee_cents: int
    latency_ms: float
    success: bool
    workload_type: WorkloadType
    reservation_id: str
    fail_reason: Optional[str] = None


@dataclass
class AgentProfile:
    agent_id: str
    name: str
    role: AgentRole
    budget: int
    price_sensitivity: float
    brand_loyalty: float
    preferred_categories: list[str] = field(default_factory=list)
    risk_tolerance: float = 0.5
    protocol_preference: Optional[Protocol] = None
    spent: int = 0
    state_idx: int = 0
    checkout_patience: float = 0.5
    social_influence: float = 0.5
    protocol_trust: dict[str, float] = field(default_factory=dict)

    @property
    def remaining_budget(self) -> int:
        return max(0, self.budget - self.spent)

    @property
    def address(self) -> dict:
        state, city, zip_code = US_STATES[self.state_idx % len(US_STATES)]
        return {
            "name": self.name,
            "line_one": f"{100 + self.state_idx} Market St",
            "city": city,
            "state": state,
            "country": "US",
            "postal_code": zip_code,
        }

    def wants_to_buy(self, price: int, category: str, rng) -> bool:
        if price > self.remaining_budget:
            return False

        if self.price_sensitivity > 0.7 and price > self.budget * 0.3:
            return rng.random() > self.price_sensitivity

        if self.preferred_categories and category not in self.preferred_categories:
            if rng.random() < self.brand_loyalty:
                return False

        buy_probability = 0.5 + (self.risk_tolerance - 0.5) * 0.3
        return rng.random() < buy_probability


@dataclass
class MerchantProfile:
    merchant_id: str
    name: str
    category: str
    product_ids: list[str]
    accepted_protocols: list[Protocol]
    reputation: float
    scale_bias: float
    preferred_settlement_domain: BalanceDomain
    accepted_settlement_domains: list[BalanceDomain]
    rebalance_threshold_cents: int
    rebalance_target_mix: dict[str, float]
    working_capital_cents: int

    @property
    def treasury_policy(self) -> TreasuryPolicy:
        return TreasuryPolicy(
            preferred_settlement_domain=self.preferred_settlement_domain,
            accepted_settlement_domains=self.accepted_settlement_domains,
            rebalance_threshold_cents=self.rebalance_threshold_cents,
            rebalance_target_mix=self.rebalance_target_mix,
            working_capital_cents=self.working_capital_cents,
        )


@dataclass
class ProtocolEcosystemState:
    protocol: Protocol
    merchant_count: int = 0
    attempted_transactions: int = 0
    successful_transactions: int = 0
    failed_transactions: int = 0
    gross_volume_cents: int = 0
    fee_revenue_cents: int = 0
    infrastructure_cost_cents: int = 0
    operator_margin_cents: int = 0
    network_effect: float = 0.0
    congestion: float = 0.0
    reliability: float = 0.98
    scale_pressure: float = 0.0
    observed_settlement_ms: float = 0.0
    route_mix: dict[str, int] = field(default_factory=dict)


@dataclass
class SimulationConfig:
    num_agents: int = 50
    num_rounds: int = 10
    protocols: list[Protocol] = field(default_factory=lambda: list(Protocol))
    engine_url: str = "http://localhost:4080"
    seed: int = 42
    world_seed: str = "meridian-protocol-economy"
    scenario_prompt: str = ""
    agent_budget_range: tuple[int, int] = (5000, 50000)
    use_llm: bool = False
    llm_model: str = "minimax-m2.5"
    merchants_per_category: int = 3
    max_active_ratio: float = 0.45
    stable_universe: str = "usdc_centric"
    market_learning_rate: float = 1.0
    social_memory_strength: float = 0.35
    flow_mix: dict[WorkloadType | str, float] = field(
        default_factory=lambda: {
            WorkloadType.API_MICRO: 0.55,
            WorkloadType.CONSUMER_CHECKOUT: 0.30,
            WorkloadType.TREASURY_REBALANCE: 0.15,
        }
    )

    def __post_init__(self):
        if self.agent_budget_range[0] > self.agent_budget_range[1]:
            self.agent_budget_range = (
                self.agent_budget_range[1],
                self.agent_budget_range[0],
            )

        normalized: dict[WorkloadType, float] = {}
        for key, value in self.flow_mix.items():
            normalized[WorkloadType(key)] = float(value)
        total = sum(normalized.values()) or 1.0
        self.flow_mix = {
            workload: value / total for workload, value in normalized.items()
        }
        self.market_learning_rate = max(0.0, min(2.0, self.market_learning_rate))
        self.social_memory_strength = max(0.0, min(1.0, self.social_memory_strength))


@dataclass
class AgentMemoryEvent:
    round_num: int
    agent_id: str
    agent_name: str
    event_type: str
    protocol: str
    workload_type: str
    sentiment_delta: float
    trust_before: float
    trust_after: float
    amount_cents: int = 0
    merchant_id: Optional[str] = None
    merchant_name: Optional[str] = None
    product_name: Optional[str] = None
    route_id: Optional[str] = None
    reason: str = ""


@dataclass
class EconomyWorldEvent:
    round_num: int
    event_type: str
    summary: str
    actor_id: Optional[str] = None
    protocol: Optional[str] = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class TransactionRecord:
    round_num: int
    agent_id: str
    protocol: str
    product_id: str
    product_name: str
    amount: int
    fee: int
    settlement_ms: float
    success: bool
    session_id: Optional[str] = None
    order_id: Optional[str] = None
    error: Optional[str] = None
    merchant_id: Optional[str] = None
    merchant_name: Optional[str] = None
    ecosystem_pressure: float = 0.0
    workload_type: Optional[str] = None
    source_domain: Optional[str] = None
    target_domain: Optional[str] = None
    primitive: Optional[str] = None
    route_id: Optional[str] = None
    margin_delta_cents: int = 0


@dataclass
class RoundSummary:
    round_num: int
    transactions: list[TransactionRecord] = field(default_factory=list)
    route_executions: list[RouteExecutionRecord] = field(default_factory=list)
    agent_memories: list[AgentMemoryEvent] = field(default_factory=list)
    world_events: list[EconomyWorldEvent] = field(default_factory=list)
    total_volume: int = 0
    total_fees: int = 0
    success_count: int = 0
    fail_count: int = 0
    active_agents: int = 0
    protocol_attempts: dict[str, int] = field(default_factory=dict)
    merchant_sales: dict[str, int] = field(default_factory=dict)
    ecosystem: dict[str, ProtocolEcosystemState] = field(default_factory=dict)
    route_usage: dict[str, int] = field(default_factory=dict)
    balance_summary: dict[str, int] = field(default_factory=dict)
    treasury_distribution: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class SimulationResult:
    config: SimulationConfig
    rounds: list[RoundSummary] = field(default_factory=list)
    protocol_summaries: dict = field(default_factory=dict)
    trust_summary: dict[str, dict[str, float]] = field(default_factory=dict)
    agent_memory_log: list[AgentMemoryEvent] = field(default_factory=list)
    world_events: list[EconomyWorldEvent] = field(default_factory=list)
    total_transactions: int = 0
    total_volume: int = 0
    duration_seconds: float = 0.0
    ecosystem_summary: dict[str, ProtocolEcosystemState] = field(default_factory=dict)
    route_usage_summary: dict[str, int] = field(default_factory=dict)
    float_summary: dict[str, int] = field(default_factory=dict)
    treasury_distribution: dict[str, dict[str, int]] = field(default_factory=dict)
    rail_pnl_history: dict[str, list[int]] = field(default_factory=dict)
