"""Core types for the Meridian simulation layer."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Protocol(str, Enum):
    ACP = "acp"
    AP2 = "ap2"
    X402 = "x402"
    MPP = "mpp"
    ATXP = "atxp"


class AgentRole(str, Enum):
    BUYER = "buyer"
    MERCHANT = "merchant"


# Protocol fee formulas (mirrors Rust engine, for client-side estimation)
PROTOCOL_FEE_FORMULAS = {
    Protocol.ACP: lambda amount: (amount * 29 // 1000) + 30,
    Protocol.AP2: lambda amount: (amount * 25 // 1000) + 20,
    Protocol.X402: lambda amount: max(amount // 1000, 1),
    Protocol.MPP: lambda amount: max((amount * 15 // 1000) + 5, 1),
    Protocol.ATXP: lambda amount: max(amount * 5 // 1000, 1),
}

# Protocol characteristics for intelligent selection
PROTOCOL_TRAITS = {
    Protocol.ACP: {"supports_micropay": False, "min_practical": 1000, "settlement_ms": 2000, "autonomy": 0.6},
    Protocol.AP2: {"supports_micropay": False, "min_practical": 800, "settlement_ms": 3000, "autonomy": 0.5},
    Protocol.X402: {"supports_micropay": True, "min_practical": 1, "settlement_ms": 200, "autonomy": 1.0},
    Protocol.MPP: {"supports_micropay": True, "min_practical": 1, "settlement_ms": 500, "autonomy": 0.8},
    Protocol.ATXP: {"supports_micropay": True, "min_practical": 1, "settlement_ms": 150, "autonomy": 0.9},
}

# US states for address diversity
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
class AgentProfile:
    agent_id: str
    name: str
    role: AgentRole
    budget: int  # cents
    price_sensitivity: float
    brand_loyalty: float
    preferred_categories: list[str] = field(default_factory=list)
    risk_tolerance: float = 0.5
    protocol_preference: Optional[Protocol] = None
    spent: int = 0
    state_idx: int = 0  # index into US_STATES for address diversity

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
        """Rule-based purchase decision using the simulation's seeded RNG."""
        if price > self.remaining_budget:
            return False

        # Price sensitivity: high-sensitivity agents reject expensive items
        if self.price_sensitivity > 0.7 and price > self.budget * 0.3:
            return rng.random() > self.price_sensitivity

        # Category preference: loyal agents reject off-category products
        if self.preferred_categories and category not in self.preferred_categories:
            if rng.random() < self.brand_loyalty:
                return False

        # Base buy probability from risk tolerance
        buy_probability = 0.5 + (self.risk_tolerance - 0.5) * 0.3
        return rng.random() < buy_probability

    def pick_protocol(self, amount: int, protocols: list, rng) -> str:
        """Intelligently select protocol based on transaction characteristics."""
        # If agent has a preference and it's available, use it (70% of the time)
        if self.protocol_preference and self.protocol_preference in protocols:
            if rng.random() < 0.7:
                return self.protocol_preference.value

        # Micropayment: prefer protocols that support them
        if amount < 100:  # < $1.00
            micro_protos = [p for p in protocols if PROTOCOL_TRAITS[p]["supports_micropay"]]
            if micro_protos:
                return rng.choice(micro_protos).value

        # Price-sensitive agents prefer low-fee protocols
        if self.price_sensitivity > 0.7:
            # Sort by estimated fee, pick from cheapest 2
            sorted_protos = sorted(protocols, key=lambda p: PROTOCOL_FEE_FORMULAS[p](amount))
            return rng.choice(sorted_protos[:2]).value

        # High-value purchases: prefer consumer-protected protocols (ACP, AP2)
        if amount > 10000:  # > $100
            safe_protos = [p for p in protocols if p in (Protocol.ACP, Protocol.AP2)]
            if safe_protos and rng.random() < 0.6:
                return rng.choice(safe_protos).value

        # Default: random
        return rng.choice(protocols).value


@dataclass
class SimulationConfig:
    num_agents: int = 50
    num_rounds: int = 10
    protocols: list[Protocol] = field(default_factory=lambda: list(Protocol))
    engine_url: str = "http://localhost:4080"
    seed: int = 42
    agent_budget_range: tuple[int, int] = (5000, 50000)


@dataclass
class TransactionRecord:
    round_num: int
    agent_id: str
    protocol: str
    product_id: str
    product_name: str
    amount: int  # cents
    fee: int  # cents
    settlement_ms: float
    success: bool
    session_id: Optional[str] = None
    order_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class RoundSummary:
    round_num: int
    transactions: list[TransactionRecord] = field(default_factory=list)
    total_volume: int = 0
    total_fees: int = 0
    success_count: int = 0
    fail_count: int = 0
    active_agents: int = 0


@dataclass
class SimulationResult:
    config: SimulationConfig
    rounds: list[RoundSummary] = field(default_factory=list)
    protocol_summaries: dict = field(default_factory=dict)
    total_transactions: int = 0
    total_volume: int = 0
    duration_seconds: float = 0.0
