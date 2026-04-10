"""Pre-defined simulation scenarios for Meridian."""

from .types import Protocol, SimulationConfig

SCENARIOS: dict[str, SimulationConfig] = {
    "traditional_retail": SimulationConfig(
        num_agents=100,
        num_rounds=20,
        protocols=[Protocol.ACP, Protocol.AP2],
        agent_budget_range=(10000, 100000),  # $100–$1000
    ),
    "full_autonomy": SimulationConfig(
        num_agents=100,
        num_rounds=20,
        protocols=[Protocol.X402, Protocol.MPP, Protocol.ATXP],
        agent_budget_range=(5000, 50000),  # $50–$500
    ),
    "crypto_native": SimulationConfig(
        num_agents=100,
        num_rounds=20,
        protocols=[Protocol.X402, Protocol.ATXP],
        agent_budget_range=(1000, 30000),  # $10–$300
    ),
    "micropayment_api": SimulationConfig(
        num_agents=100,
        num_rounds=20,
        protocols=[Protocol.X402, Protocol.MPP, Protocol.ATXP],
        agent_budget_range=(500, 5000),  # $5–$50
    ),
    "protocol_arena": SimulationConfig(
        num_agents=100,
        num_rounds=20,
        protocols=list(Protocol),
        agent_budget_range=(5000, 50000),  # $50–$500
    ),
    "stress_test": SimulationConfig(
        num_agents=500,
        num_rounds=50,
        protocols=list(Protocol),
        agent_budget_range=(2000, 20000),  # $20–$200
    ),
}

SCENARIO_DESCRIPTIONS: dict[str, str] = {
    "traditional_retail": (
        "Traditional e-commerce checkout flows using ACP and AP2. "
        "Higher budgets, consumer-protection-oriented protocols."
    ),
    "full_autonomy": (
        "Fully autonomous agent-to-agent commerce using X402, MPP, and ATXP. "
        "No human-in-the-loop checkout flows."
    ),
    "crypto_native": (
        "Crypto-native payment rails only — X402 (stateless HTTP payments) and "
        "ATXP (agent-to-agent trust). Low-friction, high-speed settlement."
    ),
    "micropayment_api": (
        "Micropayment-heavy scenario with small budgets. Tests which protocols "
        "handle sub-$1 transactions efficiently without excessive fee ratios."
    ),
    "protocol_arena": (
        "All five protocols competing inside the same stablecoin economy. "
        "Agents, merchants, treasury balances, and route pressure determine usage."
    ),
    "stress_test": (
        "High-load scenario: 500 agents over 50 rounds. Stress-tests throughput, "
        "error handling, and settlement latency under pressure."
    ),
}
