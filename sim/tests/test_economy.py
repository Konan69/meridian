import asyncio
import json

from sim.agents import generate_agents
from sim.economy import StablecoinEconomy
from sim.engine import SimulationEngine
from sim.routes import ROUTE_MATRIX
from sim.types import (
    AgentMemoryEvent,
    AgentProfile,
    AgentRole,
    BalanceDomain,
    MerchantProfile,
    PROTOCOL_FEE_FORMULAS,
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


def test_protocol_option_sustainability_bias_uses_margin_pressure_and_treasury_fit():
    config = SimulationConfig(protocols=[Protocol.AP2, Protocol.ATXP])
    engine = SimulationEngine(config)
    merchant = _merchant()
    merchant.accepted_protocols = [Protocol.AP2, Protocol.ATXP]
    agent = _agent("agent_001", trust={"ap2": 0.65, "atxp": 0.65})
    agent.protocol_preference = None

    for state in engine.protocol_state.values():
        state.reliability = 0.98
        state.network_effect = 0.4
        state.gross_volume_cents = 100_000
    engine.protocol_state["ap2"].operator_margin_cents = 6_000
    engine.protocol_state["atxp"].operator_margin_cents = -6_000

    amount = 100_000

    def option(protocol: Protocol, route_id: str, capacity_ratio: float) -> dict:
        route = next(route for route in ROUTE_MATRIX if route.route_id == route_id)
        route_fee = max(
            (amount * route.fee_bps) // 10_000 + route.fixed_fee_cents,
            route.fixed_fee_cents,
        )
        protocol_fee = 2_520 if protocol == Protocol.AP2 else 500
        return {
            "protocol": protocol,
            "route": route,
            "source_domain": route.source_domain,
            "target_domain": route.target_domain,
            "estimated_protocol_fee_cents": protocol_fee,
            "route_fee_cents": route_fee,
            "total_required_cents": amount + protocol_fee + route_fee,
            "capacity_ratio": capacity_ratio,
            "domain_mismatch": int(route.source_domain != route.target_domain),
        }

    sustainable = option(Protocol.AP2, "base_direct_usdc", 0.35)
    stressed = option(Protocol.ATXP, "lifi_base_to_gateway", 1.25)

    assert engine._protocol_self_sustainability_bias(merchant, amount, sustainable) > 0
    assert engine._protocol_self_sustainability_bias(merchant, amount, stressed) < 0
    assert engine._score_option(
        agent,
        merchant,
        amount,
        WorkloadType.TREASURY_REBALANCE,
        sustainable,
    ) > engine._score_option(
        agent,
        merchant,
        amount,
        WorkloadType.TREASURY_REBALANCE,
        stressed,
    )


def test_payment_option_refills_preferred_domain_when_treasury_is_under_pressure():
    config = SimulationConfig(protocols=[Protocol.ATXP, Protocol.MPP])
    engine = SimulationEngine(config)
    merchant = _merchant()
    merchant.accepted_protocols = [Protocol.ATXP, Protocol.MPP]
    merchant.accepted_settlement_domains = [
        BalanceDomain.BASE_USDC,
        BalanceDomain.TEMPO_USD,
    ]
    merchant.working_capital_cents = 20_000
    agent = _agent("agent_001", trust={"atxp": 0.7, "mpp": 0.7})
    agent.protocol_preference = None
    agent.checkout_patience = 0.95
    agent.price_sensitivity = 0.3
    amount = 10_000

    for state in engine.protocol_state.values():
        state.reliability = 0.98
        state.network_effect = 0.5
        state.gross_volume_cents = 100_000
        state.operator_margin_cents = 0

    def option(protocol: Protocol, route_id: str) -> dict:
        route = next(route for route in ROUTE_MATRIX if route.route_id == route_id)
        route_fee = max(
            (amount * route.fee_bps) // 10_000 + route.fixed_fee_cents,
            route.fixed_fee_cents,
        )
        protocol_fee = PROTOCOL_FEE_FORMULAS[protocol](amount)
        return {
            "protocol": protocol,
            "route": route,
            "source_domain": route.source_domain,
            "target_domain": route.target_domain,
            "estimated_protocol_fee_cents": protocol_fee,
            "route_fee_cents": route_fee,
            "total_required_cents": amount + protocol_fee + route_fee,
            "capacity_ratio": 0.1,
            "domain_mismatch": int(route.source_domain != route.target_domain),
        }

    options = [
        option(Protocol.ATXP, "lifi_tempo_to_base"),
        option(Protocol.MPP, "tempo_direct_session"),
    ]

    class _Bucket:
        def __init__(self, domain: BalanceDomain, available_cents: int):
            self.domain = domain
            self.available_cents = available_cents
            self.pending_in_cents = 0

    class _TreasuryRouteEconomy:
        def __init__(self, buckets: list[_Bucket]):
            self.buckets = buckets

        def available_buckets(self, *_args, **_kwargs):
            return self.buckets

        def enumerate_payment_options(self, **_kwargs):
            return options

    engine.economy = _TreasuryRouteEconomy(
        [
            _Bucket(BalanceDomain.BASE_USDC, 20_000),
            _Bucket(BalanceDomain.TEMPO_USD, 0),
        ]
    )
    funded_choice = engine._choose_payment_option(
        agent=agent,
        merchant=merchant,
        amount=amount,
        workload_type=WorkloadType.CONSUMER_CHECKOUT,
        available_protocols=merchant.accepted_protocols,
        target_domains=merchant.accepted_settlement_domains,
    )

    engine.economy = _TreasuryRouteEconomy(
        [
            _Bucket(BalanceDomain.BASE_USDC, 0),
            _Bucket(BalanceDomain.TEMPO_USD, 20_000),
        ]
    )
    pressured_choice = engine._choose_payment_option(
        agent=agent,
        merchant=merchant,
        amount=amount,
        workload_type=WorkloadType.CONSUMER_CHECKOUT,
        available_protocols=merchant.accepted_protocols,
        target_domains=merchant.accepted_settlement_domains,
    )

    assert funded_choice["protocol"] == Protocol.MPP
    assert funded_choice["target_domain"] == BalanceDomain.TEMPO_USD
    assert pressured_choice["protocol"] == Protocol.ATXP
    assert pressured_choice["target_domain"] == BalanceDomain.BASE_USDC


def test_rebalance_option_prefers_intended_surplus_source_domain():
    config = SimulationConfig(protocols=[Protocol.AP2, Protocol.ATXP])
    engine = SimulationEngine(config)
    merchant = _merchant()
    merchant.accepted_protocols = [Protocol.AP2, Protocol.ATXP]
    amount = 2_500
    intent = {
        "source_domain": BalanceDomain.SOLANA_USDC,
        "target_domain": BalanceDomain.BASE_USDC,
        "amount_cents": amount,
    }

    def option(protocol: Protocol, route_id: str) -> dict:
        route = next(route for route in ROUTE_MATRIX if route.route_id == route_id)
        route_fee = max(
            (amount * route.fee_bps) // 10_000 + route.fixed_fee_cents,
            route.fixed_fee_cents,
        )
        protocol_fee = PROTOCOL_FEE_FORMULAS[protocol](amount)
        return {
            "protocol": protocol,
            "route": route,
            "source_domain": route.source_domain,
            "target_domain": route.target_domain,
            "estimated_protocol_fee_cents": protocol_fee,
            "route_fee_cents": route_fee,
            "total_required_cents": amount + protocol_fee + route_fee,
            "capacity_ratio": 0.1,
            "domain_mismatch": int(route.source_domain != route.target_domain),
        }

    cheaper_preferred_source = option(Protocol.AP2, "base_direct_usdc")
    intended_surplus_source = option(Protocol.AP2, "cctp_solana_to_base")

    chosen = engine._choose_rebalance_option(
        merchant,
        intent,
        [cheaper_preferred_source, intended_surplus_source],
    )

    assert chosen["source_domain"] == BalanceDomain.SOLANA_USDC
    assert chosen["route"].route_id == "cctp_solana_to_base"

    fallback = engine._choose_rebalance_option(
        merchant,
        {**intent, "source_domain": BalanceDomain.TEMPO_USD},
        [cheaper_preferred_source],
    )

    assert fallback["route"].route_id == "base_direct_usdc"


def test_rebalance_without_feasible_protocol_route_records_world_event(capsys):
    config = SimulationConfig(protocols=[Protocol.MPP])
    engine = SimulationEngine(config)
    merchant = _merchant()
    merchant.accepted_protocols = [Protocol.MPP]
    merchant.accepted_settlement_domains = [
        BalanceDomain.BASE_USDC,
        BalanceDomain.TEMPO_USD,
    ]
    merchant.working_capital_cents = 20_000
    engine.merchants = [merchant]
    engine.agents = [_agent("agent_001")]
    engine.economy = StablecoinEconomy(
        agents=engine.agents,
        merchants=[merchant],
        protocols=config.protocols,
        rng=engine.rng,
    )
    engine.economy._get_or_create_bucket(
        AgentRole.MERCHANT,
        merchant.merchant_id,
        BalanceDomain.BASE_USDC,
    ).available_cents = 0
    engine.economy._get_or_create_bucket(
        AgentRole.MERCHANT,
        merchant.merchant_id,
        BalanceDomain.TEMPO_USD,
    ).available_cents = 12_000
    summary = RoundSummary(round_num=4)

    asyncio.run(engine._handle_rebalances(4, summary))

    assert summary.transactions == []
    failed = summary.world_events[0]
    assert failed.event_type == "treasury_rebalance_failed"
    assert failed.data["error"] == "no_feasible_rebalance_route"
    assert failed.data["source_domain"] == BalanceDomain.TEMPO_USD.value
    assert failed.data["target_domain"] == BalanceDomain.BASE_USDC.value
    assert failed.data["accepted_protocols"] == ["mpp"]
    assert summary.route_pressure[0]["reason"] == "no_feasible_rebalance_route"
    assert summary.route_pressure[0]["protocols"] == ["mpp"]
    assert summary.route_pressure[0]["pressure_level"] == "elevated"
    assert engine.route_pressure_log[0]["route_id"].startswith("treasury_rebalance_unroutable:")

    emitted = json.loads(capsys.readouterr().out)
    assert emitted["type"] == "world_event"
    assert emitted["event_type"] == "treasury_rebalance_failed"
    assert emitted["data"]["error"] == "no_feasible_rebalance_route"


def test_repeated_rebalance_infeasibility_becomes_market_evidence():
    config = SimulationConfig(
        seed=31,
        protocols=[Protocol.AP2, Protocol.ATXP, Protocol.MPP, Protocol.ACP],
        social_memory_strength=0.0,
    )
    engine = SimulationEngine(config)
    merchant = _merchant()
    merchant.accepted_protocols = [Protocol.MPP, Protocol.ACP, Protocol.AP2]
    merchant.accepted_settlement_domains = [
        BalanceDomain.BASE_USDC,
        BalanceDomain.TEMPO_USD,
    ]
    merchant.working_capital_cents = 20_000
    engine.merchants = [merchant]
    engine.agents = [
        _agent("agent_001", trust={"ap2": 0.74, "atxp": 0.78, "mpp": 0.74, "acp": 0.74}),
        _agent("agent_002", trust={"ap2": 0.74, "atxp": 0.78, "mpp": 0.74, "acp": 0.74}),
    ]
    for state in engine.protocol_state.values():
        state.reliability = 0.96
        state.network_effect = 0.55
        state.operator_margin_cents = 0

    engine.economy = StablecoinEconomy(
        agents=engine.agents,
        merchants=[merchant],
        protocols=config.protocols,
        rng=engine.rng,
    )
    engine.economy._get_or_create_bucket(
        AgentRole.MERCHANT,
        merchant.merchant_id,
        BalanceDomain.BASE_USDC,
    ).available_cents = 0
    engine.economy._get_or_create_bucket(
        AgentRole.MERCHANT,
        merchant.merchant_id,
        BalanceDomain.TEMPO_USD,
    ).available_cents = 12_000

    first = RoundSummary(round_num=4)
    asyncio.run(engine._handle_rebalances(4, first))
    second = RoundSummary(
        round_num=5,
        treasury_posture=[
            {
                "merchant_id": merchant.merchant_id,
                "merchant": merchant.name,
                "preferred_domain": BalanceDomain.BASE_USDC.value,
                "preferred_available_cents": 0,
                "non_preferred_cents": 12_000,
                "total_treasury_cents": 12_000,
                "preferred_shortfall_cents": 20_000,
                "preferred_ratio": 0.0,
                "rebalance_ready": True,
                "rebalance_threshold_cents": merchant.rebalance_threshold_cents,
            }
        ],
    )
    asyncio.run(engine._handle_rebalances(5, second))

    assert second.route_pressure[0]["failure_count"] == 2
    assert second.route_pressure[0]["capacity_ratio"] > 1.0

    engine._evolve_market(5, second)

    assert Protocol.ATXP in merchant.accepted_protocols
    removed = [
        event.data
        for event in second.world_events
        if event.event_type == "merchant_protocol_mix_changed"
        and event.data["action"] == "removed"
    ][0]
    assert removed["protocol"] in {"mpp", "acp"}
    assert removed["evidence"]["route_pressure"] > 1.0
    assert removed["reason"] == "ecosystem_evidence"


def test_market_evolution_adopts_protocol_that_can_rebalance_surplus_source():
    config = SimulationConfig(
        seed=28,
        protocols=[Protocol.AP2, Protocol.ATXP, Protocol.MPP, Protocol.ACP],
        social_memory_strength=0.0,
    )
    engine = SimulationEngine(config)
    merchant = _merchant()
    merchant.accepted_protocols = [Protocol.MPP, Protocol.ACP]
    merchant.working_capital_cents = 20_000
    engine.merchants = [merchant]
    engine.agents = [
        _agent("agent_001", trust={"ap2": 0.82, "atxp": 0.78, "mpp": 0.64, "acp": 0.64}),
        _agent("agent_002", trust={"ap2": 0.82, "atxp": 0.78, "mpp": 0.64, "acp": 0.64}),
    ]
    for state in engine.protocol_state.values():
        state.reliability = 0.96
        state.network_effect = 0.55
        state.operator_margin_cents = 0

    engine.economy = StablecoinEconomy(
        agents=engine.agents,
        merchants=[merchant],
        protocols=config.protocols,
        rng=engine.rng,
    )
    engine.economy._get_or_create_bucket(
        AgentRole.MERCHANT,
        merchant.merchant_id,
        BalanceDomain.BASE_USDC,
    ).available_cents = 0
    engine.economy._get_or_create_bucket(
        AgentRole.MERCHANT,
        merchant.merchant_id,
        BalanceDomain.TEMPO_USD,
    ).available_cents = 12_000
    summary = RoundSummary(
        round_num=8,
        treasury_posture=[
            {
                "merchant_id": merchant.merchant_id,
                "merchant": merchant.name,
                "preferred_domain": BalanceDomain.BASE_USDC.value,
                "preferred_available_cents": 0,
                "non_preferred_cents": 12_000,
                "total_treasury_cents": 12_000,
                "preferred_shortfall_cents": 20_000,
                "preferred_ratio": 0.0,
                "rebalance_ready": True,
                "rebalance_threshold_cents": merchant.rebalance_threshold_cents,
            }
        ],
    )

    engine._evolve_market(8, summary)

    assert Protocol.ATXP in merchant.accepted_protocols
    adopted = [
        event.data
        for event in summary.world_events
        if event.event_type == "merchant_protocol_mix_changed"
        and event.data["action"] == "adopted"
    ][0]
    assert adopted["protocol"] == "atxp"
    assert adopted["evidence"]["rebalance_source_domain"] == BalanceDomain.TEMPO_USD.value
    assert adopted["evidence"]["rebalance_source_feasible"] is True
    assert adopted["evidence"]["treasury_pressure"] == 1.0


def test_market_evolution_prunes_protocol_that_cannot_rebalance_surplus_source():
    config = SimulationConfig(
        seed=29,
        protocols=[Protocol.AP2, Protocol.ATXP, Protocol.MPP],
        social_memory_strength=0.0,
    )
    engine = SimulationEngine(config)
    merchant = _merchant()
    merchant.accepted_protocols = [Protocol.AP2, Protocol.ATXP, Protocol.MPP]
    merchant.working_capital_cents = 20_000
    engine.merchants = [merchant]
    engine.agents = [
        _agent("agent_001", trust={"ap2": 0.74, "atxp": 0.74, "mpp": 0.74}),
        _agent("agent_002", trust={"ap2": 0.74, "atxp": 0.74, "mpp": 0.74}),
    ]
    for state in engine.protocol_state.values():
        state.reliability = 0.97
        state.network_effect = 0.5
        state.operator_margin_cents = 0

    engine.economy = StablecoinEconomy(
        agents=engine.agents,
        merchants=[merchant],
        protocols=config.protocols,
        rng=engine.rng,
    )
    engine.economy._get_or_create_bucket(
        AgentRole.MERCHANT,
        merchant.merchant_id,
        BalanceDomain.BASE_USDC,
    ).available_cents = 0
    engine.economy._get_or_create_bucket(
        AgentRole.MERCHANT,
        merchant.merchant_id,
        BalanceDomain.TEMPO_USD,
    ).available_cents = 12_000
    summary = RoundSummary(
        round_num=9,
        treasury_posture=[
            {
                "merchant_id": merchant.merchant_id,
                "merchant": merchant.name,
                "preferred_domain": BalanceDomain.BASE_USDC.value,
                "preferred_available_cents": 0,
                "non_preferred_cents": 12_000,
                "total_treasury_cents": 12_000,
                "preferred_shortfall_cents": 20_000,
                "preferred_ratio": 0.0,
                "rebalance_ready": True,
                "rebalance_threshold_cents": merchant.rebalance_threshold_cents,
            }
        ],
    )

    engine._evolve_market(9, summary)

    assert Protocol.MPP not in merchant.accepted_protocols
    removed = [
        event.data
        for event in summary.world_events
        if event.event_type == "merchant_protocol_mix_changed"
        and event.data["action"] == "removed"
    ][0]
    assert removed["protocol"] == "mpp"
    assert removed["evidence"]["rebalance_source_domain"] == BalanceDomain.TEMPO_USD.value
    assert removed["evidence"]["rebalance_source_feasible"] is False
    assert removed["evidence"]["rebalance_target_feasible"] is False
    assert removed["evidence"]["removal_risk"] >= 0.34


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
        success=True,
        ecosystem_pressure=0.0,
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
    assert memory.outcome == "success"
    assert memory.trust_driver == "settled_on_reliable_protocol"
    assert memory.ecosystem_pressure == 0.0
    assert memory.merchant_id == "merchant_test"
    assert memory.merchant_reputation == 0.7
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
    assert emitted["outcome"] == "success"
    assert emitted["trust_driver"] == "settled_on_reliable_protocol"
    assert emitted["merchant_reputation"] == 0.7
    assert emitted["reason"] == "payment_settled"
    assert emitted["timestamp"].endswith("+00:00")

    engine._record_agent_memory(
        summary,
        round_num=1,
        agent=agent,
        protocol=Protocol.X402,
        workload_type=WorkloadType.API_MICRO,
        sentiment_delta=-0.13,
        trust_before=after,
        trust_after=after - 0.13,
        amount_cents=125,
        merchant=merchant,
        product_name="API credits",
        route_id="base-direct",
        reason="timeout",
        success=False,
        ecosystem_pressure=0.8,
    )

    failed = engine.agent_memory_log[1]
    assert failed.outcome == "failure"
    assert failed.trust_driver == "failed_under_route_pressure"
    assert failed.ecosystem_pressure == 0.8


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


def test_social_memory_diffusion_uses_recent_success_for_peers(capsys):
    config = SimulationConfig(
        seed=22,
        protocols=[Protocol.X402],
        social_memory_strength=0.5,
    )
    engine = SimulationEngine(config)
    source = _agent("agent_001", trust={"x402": 0.6})
    peer = _agent("agent_002", trust={"x402": 0.6})
    quiet_peer = _agent("agent_003", trust={"x402": 0.6})
    peer.social_influence = 0.75
    quiet_peer.social_influence = 0.0
    engine.agents = [source, peer, quiet_peer]
    merchant = _merchant()
    merchant.reputation = 0.84

    round_one = RoundSummary(round_num=1)
    engine._record_agent_memory(
        round_one,
        round_num=1,
        agent=source,
        protocol=Protocol.X402,
        workload_type=WorkloadType.API_MICRO,
        sentiment_delta=0.08,
        trust_before=0.6,
        trust_after=0.68,
        amount_cents=250,
        merchant=merchant,
        product_name="API credits",
        route_id="base-direct",
        reason="payment_settled",
        success=True,
        ecosystem_pressure=0.0,
    )
    capsys.readouterr()

    round_two = RoundSummary(round_num=2)
    adjustments = engine._diffuse_social_memory(2, round_two)

    assert len(adjustments) == 1
    assert adjustments[0]["agent_id"] == "agent_002"
    assert adjustments[0]["protocol"] == "x402"
    assert adjustments[0]["source_events"] == 1
    assert source.protocol_trust["x402"] == 0.6
    assert peer.protocol_trust["x402"] > 0.6
    assert quiet_peer.protocol_trust["x402"] == 0.6
    assert round_two.world_events[0].event_type == "social_memory_diffusion"

    emitted = json.loads(capsys.readouterr().out)
    assert emitted["type"] == "world_event"
    assert emitted["event_type"] == "social_memory_diffusion"
    assert emitted["data"]["memory_events"] == 1
    assert emitted["data"]["adjustments"][0]["agent_id"] == "agent_002"


def test_social_memory_diffusion_discounts_old_events_and_caps_failure():
    config = SimulationConfig(
        seed=23,
        protocols=[Protocol.X402],
        social_memory_strength=1.0,
    )
    engine = SimulationEngine(config)
    source = _agent("agent_001", trust={"x402": 0.6})
    peer = _agent("agent_002", trust={"x402": 0.6})
    peer.social_influence = 1.0
    engine.agents = [source, peer]
    engine.agent_memory_log = [
        AgentMemoryEvent(
            round_num=1,
            agent_id="agent_001",
            agent_name="Agent_001",
            event_type="protocol_experience",
            protocol="x402",
            workload_type="api_micro",
            sentiment_delta=0.14,
            trust_before=0.6,
            trust_after=0.74,
            outcome="success",
            trust_driver="settled_on_reliable_protocol",
        ),
        AgentMemoryEvent(
            round_num=3,
            agent_id="agent_001",
            agent_name="Agent_001",
            event_type="protocol_experience",
            protocol="x402",
            workload_type="api_micro",
            sentiment_delta=-1.0,
            trust_before=0.74,
            trust_after=0.2,
            outcome="failure",
            trust_driver="failed_low_protocol_reliability",
        ),
    ]

    adjustments = engine._diffuse_social_memory(4, RoundSummary(round_num=4))

    assert len(adjustments) == 1
    assert adjustments[0]["trust_delta"] == -0.025
    assert round(peer.protocol_trust["x402"], 4) == 0.575


def test_social_memory_diffusion_uses_outcome_for_direction():
    config = SimulationConfig(
        seed=24,
        protocols=[Protocol.X402, Protocol.AP2],
        social_memory_strength=1.0,
    )
    engine = SimulationEngine(config)
    source = _agent("agent_001", trust={"x402": 0.6})
    peer = _agent("agent_002", trust={"x402": 0.6})
    peer.social_influence = 1.0
    engine.agents = [source, peer]

    engine.agent_memory_log = [
        AgentMemoryEvent(
            round_num=1,
            agent_id="agent_001",
            agent_name="Agent_001",
            event_type="protocol_experience",
            protocol="x402",
            workload_type="api_micro",
            sentiment_delta=0.2,
            trust_before=0.7,
            trust_after=0.5,
            outcome="failure",
            trust_driver="failed_payment_error",
        )
    ]
    failed_adjustments = engine._diffuse_social_memory(2, RoundSummary(round_num=2))

    assert failed_adjustments[0]["trust_delta"] < 0
    assert peer.protocol_trust["x402"] < 0.6

    peer.protocol_trust["x402"] = 0.6
    engine.agent_memory_log = [
        AgentMemoryEvent(
            round_num=1,
            agent_id="agent_001",
            agent_name="Agent_001",
            event_type="protocol_experience",
            protocol="x402",
            workload_type="api_micro",
            sentiment_delta=-0.2,
            trust_before=0.5,
            trust_after=0.7,
            outcome="success",
            trust_driver="settled_payment",
        )
    ]
    success_adjustments = engine._diffuse_social_memory(2, RoundSummary(round_num=2))

    assert success_adjustments[0]["trust_delta"] > 0
    assert peer.protocol_trust["x402"] > 0.6

    route = next(route for route in ROUTE_MATRIX if route.route_id == "base_direct_usdc")
    route_choice_options = [
        {
            "protocol": Protocol.X402,
            "route": route,
            "estimated_protocol_fee_cents": 1,
            "route_fee_cents": 1,
            "capacity_ratio": 0.0,
            "domain_mismatch": 0,
        },
        {
            "protocol": Protocol.AP2,
            "route": route,
            "estimated_protocol_fee_cents": 1,
            "route_fee_cents": 1,
            "capacity_ratio": 0.0,
            "domain_mismatch": 0,
        },
    ]

    class _RouteChoiceEconomy:
        def enumerate_payment_options(self, **_kwargs):
            return route_choice_options

    engine.active_protocols = [Protocol.X402, Protocol.AP2]
    engine.economy = _RouteChoiceEconomy()
    peer.protocol_trust = {"x402": 0.62, "ap2": 0.61}
    peer.protocol_preference = None
    engine.agent_memory_log = [
        AgentMemoryEvent(
            round_num=1,
            agent_id="agent_001",
            agent_name="Agent_001",
            event_type="protocol_experience",
            protocol="x402",
            workload_type="consumer_checkout",
            sentiment_delta=-0.14,
            trust_before=0.74,
            trust_after=0.2,
            outcome="failure",
            trust_driver="failed_low_protocol_reliability",
        )
    ]
    before_choice = engine._choose_payment_option(
        agent=peer,
        merchant=_merchant(),
        amount=1_000,
        workload_type=WorkloadType.CONSUMER_CHECKOUT,
        available_protocols=[Protocol.X402, Protocol.AP2],
        target_domains=[BalanceDomain.BASE_USDC],
    )
    engine._diffuse_social_memory(2, RoundSummary(round_num=2))
    after_choice = engine._choose_payment_option(
        agent=peer,
        merchant=_merchant(),
        amount=1_000,
        workload_type=WorkloadType.CONSUMER_CHECKOUT,
        available_protocols=[Protocol.X402, Protocol.AP2],
        target_domains=[BalanceDomain.BASE_USDC],
    )

    assert before_choice["protocol"] == Protocol.X402
    assert after_choice["protocol"] == Protocol.AP2


def test_merchants_switch_protocols_from_trust_memory_and_world_pressure():
    config = SimulationConfig(
        seed=25,
        protocols=list(Protocol),
        social_memory_strength=1.0,
    )
    engine = SimulationEngine(config)
    merchant = _merchant()
    merchant.accepted_protocols = [Protocol.X402, Protocol.MPP, Protocol.ACP]
    merchant.working_capital_cents = 20_000
    engine.merchants = [merchant]
    engine.agents = [
        _agent(
            "agent_001",
            trust={"ap2": 0.92, "atxp": 0.55, "x402": 0.25, "mpp": 0.5, "acp": 0.48},
        ),
        _agent(
            "agent_002",
            trust={"ap2": 0.9, "atxp": 0.58, "x402": 0.28, "mpp": 0.52, "acp": 0.5},
        ),
    ]
    engine.protocol_state["ap2"].reliability = 0.99
    engine.protocol_state["ap2"].network_effect = 0.7
    engine.protocol_state["x402"].reliability = 0.65
    engine.protocol_state["x402"].operator_margin_cents = -8_000
    engine.protocol_state["x402"].network_effect = 0.2
    engine.agent_memory_log = [
        AgentMemoryEvent(
            round_num=4,
            agent_id="agent_001",
            agent_name="Agent_001",
            event_type="protocol_experience",
            protocol="ap2",
            workload_type="consumer_checkout",
            sentiment_delta=0.13,
            trust_before=0.79,
            trust_after=0.92,
            outcome="success",
            trust_driver="settled_on_reliable_protocol",
        ),
        AgentMemoryEvent(
            round_num=4,
            agent_id="agent_002",
            agent_name="Agent_002",
            event_type="protocol_experience",
            protocol="x402",
            workload_type="consumer_checkout",
            sentiment_delta=-0.12,
            trust_before=0.4,
            trust_after=0.28,
            outcome="failure",
            trust_driver="failed_low_protocol_reliability",
        ),
    ]
    summary = RoundSummary(
        round_num=5,
        route_pressure=[
            {
                "route_id": "gateway_batch_settle",
                "source_domain": "base_usdc",
                "target_domain": "gateway_unified_usdc",
                "primitive": "batched_nanopayment",
                "protocols": ["x402"],
                "usage_cents": 3_800_000,
                "capacity_cents": 3_500_000,
                "capacity_ratio": 1.08,
                "pressure_level": "critical",
            }
        ],
        treasury_posture=[
            {
                "merchant_id": merchant.merchant_id,
                "merchant": merchant.name,
                "preferred_domain": "base_usdc",
                "preferred_available_cents": 4_000,
                "non_preferred_cents": 16_000,
                "total_treasury_cents": 20_000,
                "preferred_shortfall_cents": 16_000,
                "preferred_ratio": 0.2,
                "rebalance_ready": True,
                "rebalance_threshold_cents": merchant.rebalance_threshold_cents,
            }
        ],
    )

    engine._evolve_market(5, summary)

    assert Protocol.AP2 in merchant.accepted_protocols
    assert Protocol.X402 not in merchant.accepted_protocols
    switches = [
        event.data
        for event in summary.world_events
        if event.event_type == "merchant_protocol_mix_changed"
    ]
    assert switches[0]["action"] == "adopted"
    assert switches[0]["protocol"] == "ap2"
    assert switches[0]["reason"] == "ecosystem_evidence"
    assert switches[0]["evidence"]["avg_trust"] > 0.9
    assert switches[0]["evidence"]["treasury_pressure"] > 0.7
    assert switches[1]["action"] == "removed"
    assert switches[1]["protocol"] == "x402"
    assert switches[1]["evidence"]["route_pressure"] > 1.0

    domain_config = SimulationConfig(
        seed=26,
        protocols=[Protocol.AP2, Protocol.MPP, Protocol.ACP],
        social_memory_strength=0.0,
    )
    domain_engine = SimulationEngine(domain_config)
    domain_merchant = _merchant()
    domain_merchant.accepted_protocols = [Protocol.AP2, Protocol.MPP, Protocol.ACP]
    domain_merchant.working_capital_cents = 20_000
    domain_engine.merchants = [domain_merchant]
    domain_engine.agents = [
        _agent("agent_003", trust={"ap2": 0.66, "mpp": 0.66, "acp": 0.66}),
        _agent("agent_004", trust={"ap2": 0.66, "mpp": 0.66, "acp": 0.66}),
    ]
    for state in domain_engine.protocol_state.values():
        state.reliability = 0.96
        state.network_effect = 0.4
        state.operator_margin_cents = 0

    domain_summary = RoundSummary(
        round_num=6,
        treasury_posture=[
            {
                "merchant_id": domain_merchant.merchant_id,
                "merchant": domain_merchant.name,
                "preferred_domain": BalanceDomain.BASE_USDC.value,
                "preferred_available_cents": 0,
                "non_preferred_cents": 20_000,
                "total_treasury_cents": 20_000,
                "preferred_shortfall_cents": 20_000,
                "preferred_ratio": 0.0,
                "rebalance_ready": True,
                "rebalance_threshold_cents": domain_merchant.rebalance_threshold_cents,
            }
        ],
    )

    domain_engine._evolve_market(6, domain_summary)

    assert Protocol.AP2 in domain_merchant.accepted_protocols
    assert len(domain_merchant.accepted_protocols) == 2
    removed = [
        event.data
        for event in domain_summary.world_events
        if event.event_type == "merchant_protocol_mix_changed"
        and event.data["action"] == "removed"
    ][0]
    assert removed["protocol"] in {"mpp", "acp"}
    assert removed["evidence"]["removal_risk"] >= 0.28


def test_merchants_prune_protocols_from_recent_route_pressure_memory():
    config = SimulationConfig(
        seed=27,
        protocols=[Protocol.X402, Protocol.AP2, Protocol.MPP],
        social_memory_strength=0.0,
    )
    engine = SimulationEngine(config)
    merchant = _merchant()
    merchant.accepted_protocols = [Protocol.X402, Protocol.AP2, Protocol.MPP]
    engine.merchants = [merchant]
    engine.agents = [
        _agent("agent_001", trust={"x402": 0.54, "ap2": 0.74, "mpp": 0.74}),
        _agent("agent_002", trust={"x402": 0.54, "ap2": 0.74, "mpp": 0.74}),
    ]
    for state in engine.protocol_state.values():
        state.reliability = 0.97
        state.network_effect = 0.5
        state.operator_margin_cents = 0

    engine.route_pressure_log = [
        {
            "round": 6,
            "route_id": "gateway_batch_settle",
            "source_domain": BalanceDomain.BASE_USDC.value,
            "target_domain": BalanceDomain.GATEWAY_UNIFIED_USDC.value,
            "primitive": "batched_nanopayment",
            "protocols": ["x402"],
            "usage_cents": 5_600_000,
            "capacity_cents": 3_500_000,
            "capacity_ratio": 1.6,
            "pressure_level": "critical",
        }
    ]
    summary = RoundSummary(round_num=7)

    engine._evolve_market(7, summary)

    assert Protocol.X402 not in merchant.accepted_protocols
    removed = [
        event.data
        for event in summary.world_events
        if event.event_type == "merchant_protocol_mix_changed"
        and event.data["action"] == "removed"
    ][0]
    assert removed["protocol"] == "x402"
    assert removed["evidence"]["route_pressure"] == 1.36
    assert removed["evidence"]["removal_risk"] >= 0.28


class _OfflineEconomy:
    total_route_usage = {"base-direct": 1}

    def snapshot_float_summary(self) -> dict[str, int]:
        return {"base_usdc": 10_000}

    def snapshot_treasury_distribution(self) -> dict[str, dict[str, int]]:
        return {"merchant_test": {"base_usdc": 10_000}}

    def snapshot_route_pressure(self) -> list[dict[str, object]]:
        return []

    def snapshot_treasury_posture(self) -> list[dict[str, object]]:
        return []

    def snapshot_balances(self) -> dict[str, dict[str, int]]:
        return {"agent_001": {"base_usdc": 8_500}}


def test_simulation_complete_payload_preserves_world_contract(capsys):
    config = SimulationConfig(
        num_rounds=1,
        seed=13,
        protocols=[Protocol.X402],
        world_seed="offline-complete-world",
        scenario_prompt="complete payload includes memory",
    )
    engine = SimulationEngine(config)
    agent = _agent("agent_001", trust={"x402": 0.6})
    merchant = _merchant()

    async def fake_setup():
        engine.agents = [agent]
        engine.merchants = [merchant]
        engine.economy = _OfflineEconomy()

    async def fake_run_round(round_num: int) -> RoundSummary:
        summary = RoundSummary(
            round_num=round_num,
            active_agents=1,
            success_count=1,
            total_volume=125,
            total_fees=1,
        )
        before, after, sentiment_delta = engine._apply_protocol_experience(
            agent,
            Protocol.X402,
            success=True,
            ecosystem_pressure=0.0,
        )
        engine._record_agent_memory(
            summary,
            round_num=round_num,
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
        engine._record_world_event(
            summary,
            round_num,
            "round_closed",
            "Round 1 closed with offline memory.",
            data={"trust_summary": engine._protocol_trust_summary()},
        )
        return summary

    engine.setup = fake_setup
    engine.run_round = fake_run_round

    result = asyncio.run(engine.run())
    emitted = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    complete = emitted[-1]

    assert result.total_transactions == 1
    assert result.trust_summary["x402"]["avg"] > 0.6
    assert len(result.agent_memory_log) == 1
    assert len(result.world_events) == 1

    assert complete["type"] == "simulation_complete"
    assert complete["world_id"] == engine.world_id
    assert complete["simulation_world"] == {
        "world_id": engine.world_id,
        "world_seed": "offline-complete-world",
        "scenario_prompt": "complete payload includes memory",
        "stable_universe": "usdc_centric",
        "agents": 1,
        "merchants": 1,
        "protocols": ["x402"],
        "memory_events": 1,
        "world_events": 1,
    }
    assert complete["trust_summary"] == result.trust_summary
    assert complete["agent_memory_log"][0]["reason"] == "payment_settled"
    assert complete["agent_memory_log"][0]["trust_after"] > complete["agent_memory_log"][0]["trust_before"]
    assert complete["world_events"][0]["event_type"] == "round_closed"
    assert complete["balances"] == {"agent_001": {"base_usdc": 8_500}}


def test_economy_observability_snapshots_mark_route_and_treasury_pressure():
    agents = generate_agents(1, seed=13)
    merchant = _merchant()
    economy = StablecoinEconomy(
        agents=agents,
        merchants=[merchant],
        protocols=list(Protocol),
        rng=__import__("random").Random(13),
    )
    economy.round_route_usage["base_direct_usdc"] = 2_000_000

    pressure = economy.snapshot_route_pressure()

    assert pressure[0]["route_id"] == "base_direct_usdc"
    assert pressure[0]["pressure_level"] == "elevated"
    assert pressure[0]["capacity_ratio"] == 0.8
    assert "x402" in pressure[0]["protocols"]

    preferred_bucket = economy._get_or_create_bucket(
        AgentRole.MERCHANT,
        merchant.merchant_id,
        merchant.preferred_settlement_domain,
    )
    preferred_bucket.available_cents = 1_000
    gateway_bucket = economy._get_or_create_bucket(
        AgentRole.MERCHANT,
        merchant.merchant_id,
        BalanceDomain.GATEWAY_UNIFIED_USDC,
    )
    gateway_bucket.available_cents = 10_000

    posture = economy.snapshot_treasury_posture()

    assert posture[0]["merchant_id"] == merchant.merchant_id
    assert posture[0]["preferred_domain"] == BalanceDomain.BASE_USDC.value
    assert posture[0]["preferred_shortfall_cents"] == 19_000
    assert posture[0]["rebalance_ready"] is True
