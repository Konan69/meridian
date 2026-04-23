from sim.agents import generate_agents
from sim.economy import StablecoinEconomy
from sim.types import AgentRole, BalanceDomain, MerchantProfile, Protocol, WorkloadType


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
