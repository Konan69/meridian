import json

from sim.agents import generate_agents
from sim.economy import StablecoinEconomy
from sim.engine import SimulationEngine
from sim.types import (
    AgentProfile,
    AgentRole,
    BalanceDomain,
    MerchantProfile,
    Protocol,
    RoundSummary,
    SimulationConfig,
    WorkloadType,
)


def _merchant() -> MerchantProfile:
    return MerchantProfile(
        merchant_id="merchant_test",
        name="merchant_test",
        category="digital",
        product_ids=["prod_api_credits"],
        accepted_protocols=[Protocol.X402, Protocol.AP2, Protocol.MPP],
        reputation=0.7,
        scale_bias=0.6,
        preferred_settlement_domain=BalanceDomain.BASE_USDC,
        accepted_settlement_domains=[
            BalanceDomain.BASE_USDC,
            BalanceDomain.GATEWAY_UNIFIED_USDC,
            BalanceDomain.TEMPO_USD,
        ],
        rebalance_threshold_cents=2_500,
        rebalance_target_mix={BalanceDomain.BASE_USDC.value: 0.7, BalanceDomain.GATEWAY_UNIFIED_USDC.value: 0.3},
        working_capital_cents=20_000,
    )


def test_routes_feasible_from_fragmented_balances():
    agents = generate_agents(3, seed=42)
    merchant = _merchant()
    economy = StablecoinEconomy(
        agents=agents,
        merchants=[merchant],
        protocols=list(Protocol),
        rng=__import__("random").Random(42),
    )

    options = economy.enumerate_payment_options(
        owner_kind=AgentRole.BUYER,
        owner_id=agents[0].agent_id,
        amount_cents=500,
        workload_type=WorkloadType.API_MICRO,
        target_domains=merchant.accepted_settlement_domains,
        available_protocols=merchant.accepted_protocols,
    )

    assert options, "Expected at least one feasible route option"
    assert any(opt["protocol"] == Protocol.X402 for opt in options)


def test_reservation_release_rolls_back_balance():
    agents = generate_agents(1, seed=7)
    merchant = _merchant()
    economy = StablecoinEconomy(
        agents=agents,
        merchants=[merchant],
        protocols=list(Protocol),
        rng=__import__("random").Random(7),
    )
    option = economy.enumerate_payment_options(
        owner_kind=AgentRole.BUYER,
        owner_id=agents[0].agent_id,
        amount_cents=500,
        workload_type=WorkloadType.API_MICRO,
        target_domains=merchant.accepted_settlement_domains,
        available_protocols=merchant.accepted_protocols,
    )[0]

    source_domain = option["source_domain"]
    before = economy._get_or_create_bucket(AgentRole.BUYER, agents[0].agent_id, source_domain).available_cents
    reservation = economy.reserve(
        owner_kind=AgentRole.BUYER,
        owner_id=agents[0].agent_id,
        option=option,
        amount_cents=500,
        workload_type=WorkloadType.API_MICRO,
        round_num=1,
    )
    assert reservation is not None
    economy.release_reservation(reservation.reservation_id, "test_release")
    after = economy._get_or_create_bucket(AgentRole.BUYER, agents[0].agent_id, source_domain).available_cents
    assert after == before


def test_merchant_rebalance_trigger():
    agents = generate_agents(1, seed=9)
    merchant = _merchant()
    economy = StablecoinEconomy(
        agents=agents,
        merchants=[merchant],
        protocols=list(Protocol),
        rng=__import__("random").Random(9),
    )

    preferred_bucket = economy._get_or_create_bucket(
        AgentRole.MERCHANT, merchant.merchant_id, merchant.preferred_settlement_domain
    )
    preferred_bucket.available_cents = 0
    gateway_bucket = economy._get_or_create_bucket(
        AgentRole.MERCHANT, merchant.merchant_id, BalanceDomain.GATEWAY_UNIFIED_USDC
    )
    gateway_bucket.available_cents = 10_000

    intent = economy.merchant_needs_rebalance(merchant)
    assert intent is not None
    assert intent["target_domain"] == merchant.preferred_settlement_domain


def test_float_summary_populated():
    agents = generate_agents(2, seed=5)
    merchant = _merchant()
    economy = StablecoinEconomy(
        agents=agents,
        merchants=[merchant],
        protocols=list(Protocol),
        rng=__import__("random").Random(5),
    )

    float_summary = economy.snapshot_float_summary()
    assert float_summary
    assert sum(float_summary.values()) > 0


def _agent(agent_id: str, *, trust: dict[str, float] | None = None) -> AgentProfile:
    return AgentProfile(
        agent_id=agent_id,
        name=agent_id.title(),
        role=AgentRole.BUYER,
        budget=10_000,
        price_sensitivity=0.4,
        brand_loyalty=0.3,
        preferred_categories=["digital"],
        risk_tolerance=0.7,
        protocol_preference=Protocol.X402,
        social_influence=0.5,
        protocol_trust=trust or {},
    )


def test_world_event_records_summary_and_ndjson_contract(capsys):
    config = SimulationConfig(
        seed=11,
        protocols=[Protocol.X402],
        world_seed="offline-agent-economy",
        scenario_prompt="buyers compare protocol trust",
    )
    engine = SimulationEngine(config)
    summary = RoundSummary(round_num=2)

    engine._record_world_event(
        summary,
        2,
        "round_closed",
        "Round 2 closed with a trust snapshot.",
        actor_id="agent_001",
        protocol=Protocol.X402,
        data={"trust_summary": {"x402": {"avg": 0.7, "min": 0.6, "max": 0.8}}},
    )

    assert len(engine.world_events) == 1
    assert summary.world_events == engine.world_events
    event = engine.world_events[0]
    assert event.round_num == 2
    assert event.event_type == "round_closed"
    assert event.protocol == "x402"
    assert event.data["trust_summary"]["x402"]["avg"] == 0.7

    emitted = json.loads(capsys.readouterr().out)
    assert emitted["type"] == "world_event"
    assert emitted["world_id"] == engine.world_id
    assert emitted["round"] == 2
    assert emitted["event_type"] == "round_closed"
    assert emitted["actor_id"] == "agent_001"
    assert emitted["protocol"] == "x402"
    assert emitted["timestamp"].endswith("+00:00")


def test_agent_memory_records_trust_change_and_ndjson_contract(capsys):
    config = SimulationConfig(
        seed=12,
        protocols=[Protocol.X402, Protocol.ATXP],
        world_seed="offline-memory-world",
    )
    engine = SimulationEngine(config)
    summary = RoundSummary(round_num=1)
    agent = _agent("agent_001", trust={"x402": 0.6})
    merchant = _merchant()

    before, after, sentiment_delta = engine._apply_protocol_experience(
        agent,
        Protocol.X402,
        success=True,
        ecosystem_pressure=0.0,
    )
    engine._record_agent_memory(
        summary,
        round_num=1,
        agent=agent,
        protocol=Protocol.X402,
        workload_type=WorkloadType.API_MICRO,
        sentiment_delta=sentiment_delta,
        trust_before=before,
        trust_after=after,
        amount_cents=125,
        merchant=merchant,
        product_name="API credits",
        route_id="base-direct",
        reason="payment_settled",
    )

    assert before == 0.6
    assert after > before
    assert len(engine.agent_memory_log) == 1
    assert summary.agent_memories == engine.agent_memory_log
    memory = engine.agent_memory_log[0]
    assert memory.agent_id == "agent_001"
    assert memory.protocol == "x402"
    assert memory.workload_type == "api_micro"
    assert memory.trust_before == round(before, 4)
    assert memory.trust_after == round(after, 4)
    assert memory.sentiment_delta == round(sentiment_delta, 4)
    assert memory.merchant_id == "merchant_test"
    assert memory.product_name == "API credits"
    assert memory.route_id == "base-direct"

    emitted = json.loads(capsys.readouterr().out)
    assert emitted["type"] == "agent_memory"
    assert emitted["world_id"] == engine.world_id
    assert emitted["round"] == 1
    assert emitted["round_num"] == 1
    assert emitted["agent_id"] == "agent_001"
    assert emitted["agent_name"] == "Agent_001"
    assert emitted["protocol"] == "x402"
    assert emitted["trust_before"] == round(before, 4)
    assert emitted["trust_after"] == round(after, 4)
    assert emitted["reason"] == "payment_settled"
    assert emitted["timestamp"].endswith("+00:00")


def test_protocol_trust_summary_covers_active_protocols_with_defaults():
    config = SimulationConfig(protocols=[Protocol.X402, Protocol.ATXP])
    engine = SimulationEngine(config)
    engine.agents = [
        _agent("agent_001", trust={"x402": 0.7, "atxp": 0.55}),
        _agent("agent_002", trust={"x402": 0.5}),
    ]

    summary = engine._protocol_trust_summary()

    assert set(summary) == {"x402", "atxp"}
    assert summary["x402"] == {"avg": 0.6, "min": 0.5, "max": 0.7}
    assert summary["atxp"] == {"avg": 0.575, "min": 0.55, "max": 0.6}
