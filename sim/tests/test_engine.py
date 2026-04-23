"""Integration tests -- requires the Rust engine running on :4080."""
import asyncio
import uuid
import pytest

from sim.commerce import CommerceClient
from sim.types import (
    AgentMemoryEvent,
    AgentProfile,
    AgentRole,
    EconomyWorldEvent,
    Protocol,
    SimulationConfig,
    SimulationResult,
)
from sim.agents import generate_agents
from sim.scenarios import SCENARIOS, SCENARIO_DESCRIPTIONS
from sim.report import ReportGenerator
from sim.engine import SimulationEngine


ALL_PROTOCOLS = [Protocol.ACP, Protocol.AP2, Protocol.X402, Protocol.MPP, Protocol.ATXP]
ENGINE_URL = "http://localhost:4080"


async def _engine_available(client: CommerceClient) -> bool:
    """Return True if the Rust engine is reachable."""
    try:
        return await client.health()
    except Exception:
        return False


async def _supported_protocols(client: CommerceClient) -> list[str]:
    caps = await client.get_capabilities()
    return caps.get("supported_protocols", [])


async def _wait_for_engine(client: CommerceClient, timeout_s: float = 45.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await _engine_available(client):
            return True
        await asyncio.sleep(1)
    return False


def _unique_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _skip_if_offline(healthy: bool):
    if not healthy:
        pytest.skip("Engine not running")


# ------------------------------------------------------------------
# a. Health endpoint
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_health(client: CommerceClient):
    """Verify engine responds at /health."""
    healthy = await _wait_for_engine(client)
    _skip_if_offline(healthy)
    assert healthy is True


# ------------------------------------------------------------------
# b. Products endpoint
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_products_endpoint(client: CommerceClient):
    """Verify /products returns 6 products with correct schema."""
    healthy = await _wait_for_engine(client)
    _skip_if_offline(healthy)

    products = await client.get_products()
    assert len(products) == 6

    required_keys = {"id", "name", "base_price", "category"}
    for product in products:
        assert required_keys.issubset(product.keys()), (
            f"Product missing keys: {required_keys - product.keys()}"
        )
        assert isinstance(product["base_price"], int)
        assert product["base_price"] > 0

# ------------------------------------------------------------------
# c. Live x402 checkout + metrics
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_x402_checkout_and_metrics(client: CommerceClient):
    """Run a full live x402 checkout and verify settlement side effects.

    This is the strongest engine-facing test:
    - waits for engine readiness
    - uses a unique agent so wallet creation/funding is isolated
    - checks checkout completion
    - checks payment_result message
    - checks metrics increment
    - checks transaction persistence
    """
    healthy = await _wait_for_engine(client)
    _skip_if_offline(healthy)

    supported = await _supported_protocols(client)
    if "x402" not in supported:
        pytest.skip(f"x402 not supported by engine: {supported}")

    metrics_before = await client.get_metrics()
    before_x402 = next(
        (p for p in metrics_before.get("protocols", []) if p.get("protocol") == "x402"),
        {"total_transactions": 0, "successful_transactions": 0},
    )

    products = await client.get_products()
    product = next(
        p for p in products
        if p.get("id") == "prod_data_report"
        or (not p.get("requires_shipping", True) and p.get("base_price", 0) <= 500)
    )

    agent_id = _unique_id("live_x402_agent")
    merchant_id = _unique_id("live_x402_merchant")
    checkout = await client.create_checkout(
        items=[{"id": product["id"], "quantity": 1}],
        protocol="x402",
        agent_id=agent_id,
    )
    assert "id" in checkout, f"Checkout creation failed: {checkout}"

    result = await client.complete_checkout(
        session_id=checkout["id"],
        payment_token=f"token_x402_{agent_id}",
        protocol="x402",
        merchant=merchant_id,
    )
    assert result.get("status") == "completed", f"x402 checkout failed: {result}"

    payment_messages = [m for m in result.get("messages", []) if m.get("type") == "payment_result"]
    assert payment_messages, f"Missing payment_result message: {result}"
    assert any('"status":"settled"' in m.get("content", "") for m in payment_messages), (
        f"Payment message did not report settlement: {payment_messages}"
    )

    metrics_after = await client.get_metrics()
    after_x402 = next(
        (p for p in metrics_after.get("protocols", []) if p.get("protocol") == "x402"),
        None,
    )
    assert after_x402 is not None, f"Missing x402 metrics after checkout: {metrics_after}"
    assert after_x402["total_transactions"] >= before_x402.get("total_transactions", 0) + 1
    assert after_x402["successful_transactions"] >= before_x402.get("successful_transactions", 0) + 1

    transactions = await client.get_transactions()
    assert any(tx.get("session_id") == checkout["id"] for tx in transactions), (
        f"Missing persisted transaction for session {checkout['id']}"
    )


# ------------------------------------------------------------------
# d. Live ATXP direct payment
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_atxp_direct_payment(client: CommerceClient):
    """Run a real low-value ATXP payment through the engine direct-payment path."""
    healthy = await _wait_for_engine(client)
    _skip_if_offline(healthy)

    supported = await _supported_protocols(client)
    if "atxp" not in supported:
        pytest.skip(f"atxp not supported by engine: {supported}")

    record = await client.execute_payment(
        actor_id=_unique_id("atxp_exec"),
        protocol="atxp",
        amount_cents=1,
        merchant=_unique_id("atxp_merchant"),
        round_num=0,
        workload_type="atxp_direct_probe",
    )
    assert record.success, f"ATXP direct payment failed: {record.error}"
    assert record.protocol == "atxp"
    assert record.amount == 1
    assert record.fee >= 1


# ------------------------------------------------------------------
# e. Live AP2 direct payment
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_ap2_direct_payment(client: CommerceClient):
    """Run a real AP2 mandate/receipt flow through the engine direct-payment path."""
    healthy = await _wait_for_engine(client)
    _skip_if_offline(healthy)

    supported = await _supported_protocols(client)
    if "ap2" not in supported:
        pytest.skip(f"ap2 not supported by engine: {supported}")

    record = await client.execute_payment(
        actor_id=_unique_id("ap2_exec"),
        protocol="ap2",
        amount_cents=125,
        merchant=_unique_id("ap2_merchant"),
        round_num=0,
        workload_type="ap2_direct_probe",
    )
    assert record.success, f"AP2 direct payment failed: {record.error}"
    assert record.protocol == "ap2"
    assert record.amount == 125
    assert record.fee >= 20


# ------------------------------------------------------------------
# f. Live MPP direct payment
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_mpp_direct_payment(client: CommerceClient):
    """Run a real MPP payment through the engine direct-payment path."""
    healthy = await _wait_for_engine(client)
    _skip_if_offline(healthy)

    supported = await _supported_protocols(client)
    if "mpp" not in supported:
        pytest.skip(f"mpp not supported by engine: {supported}")

    record = await client.execute_payment(
        actor_id=_unique_id("mpp_exec"),
        protocol="mpp",
        amount_cents=1,
        merchant=_unique_id("mpp_merchant"),
        round_num=0,
        workload_type="mpp_direct_probe",
    )
    assert record.success, f"MPP direct payment failed: {record.error}"
    assert record.protocol == "mpp"
    assert record.amount == 1
    assert record.fee >= 1


# ------------------------------------------------------------------
# g. All protocols
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_protocols(client: CommerceClient):
    """Complete one checkout through each supported engine protocol."""
    healthy = await _wait_for_engine(client)
    _skip_if_offline(healthy)

    products = await client.get_products()
    # Use a digital product (no shipping required) so checkout completes without address
    product = next(p for p in products if not p.get("requires_shipping", True))

    supported = await _supported_protocols(client)
    assert supported, "Engine reported no supported protocols"

    for protocol_name in supported:
        record = await client.full_purchase(
            agent_id=_unique_id(f"test_agent_{protocol_name}"),
            product_id=product["id"],
            quantity=1,
            protocol=protocol_name,
            round_num=0,
            product_name=product.get("name", ""),
            needs_shipping=False,
            merchant_id=_unique_id(f"merchant_{protocol_name}"),
            merchant_name=f"{protocol_name}_merchant",
        )
        assert record.success, (
            f"[{protocol_name}] Checkout failed: {record.error}"
        )


# ------------------------------------------------------------------
# h. Metrics after transactions
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metrics_after_transactions(client: CommerceClient):
    """Run one transaction per supported protocol, verify /metrics shows correct counts."""
    healthy = await _wait_for_engine(client)
    _skip_if_offline(healthy)

    # Snapshot metrics before
    metrics_before = await client.get_metrics()
    before_counts: dict[str, int] = {}
    for p in metrics_before.get("protocols", []):
        before_counts[p["protocol"]] = p.get("total_transactions", 0)

    products = await client.get_products()
    # Use a digital product so no address is needed
    product = next(p for p in products if not p.get("requires_shipping", True))

    # Run one transaction per protocol
    supported = await _supported_protocols(client)
    assert supported, "Engine reported no supported protocols"

    for protocol_name in supported:
        record = await client.full_purchase(
            agent_id=_unique_id(f"metrics_agent_{protocol_name}"),
            product_id=product["id"],
            quantity=1,
            protocol=protocol_name,
            round_num=1,
            product_name=product.get("name", ""),
            needs_shipping=False,
            merchant_id=_unique_id(f"metrics_merchant_{protocol_name}"),
            merchant_name=f"metrics_{protocol_name}_merchant",
        )
        assert record.success, (
            f"[{protocol_name}] Transaction failed: {record.error}"
        )

    # Snapshot metrics after
    metrics_after = await client.get_metrics()
    after_counts: dict[str, int] = {}
    for p in metrics_after.get("protocols", []):
        after_counts[p["protocol"]] = p.get("total_transactions", 0)

    # Each protocol should have at least 1 more transaction
    for name in supported:
        before = before_counts.get(name, 0)
        after = after_counts.get(name, 0)
        assert after >= before + 1, (
            f"[{name}] Expected at least {before + 1} transactions, got {after}"
        )
# ------------------------------------------------------------------
# i. Ecosystem outputs
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ecosystem_outputs():
    """Run a small sim and verify ecosystem summaries are populated."""
    client = CommerceClient(ENGINE_URL)
    healthy = await _wait_for_engine(client)
    await client.close()
    _skip_if_offline(healthy)

    config = SimulationConfig(
        num_agents=12,
        num_rounds=3,
        protocols=[Protocol.X402],
        engine_url=ENGINE_URL,
        seed=42,
        agent_budget_range=(20000, 90000),
    )
    engine = SimulationEngine(config)
    result = await engine.run()

    assert result.ecosystem_summary, "Missing ecosystem summary"
    assert result.route_usage_summary is not None
    assert result.float_summary, "Missing float summary"
    assert result.treasury_distribution is not None
    assert result.rail_pnl_history, "Missing rail PnL history"

    for protocol in config.protocols:
        assert protocol.value in result.ecosystem_summary
        assert protocol.value in result.rail_pnl_history


# ------------------------------------------------------------------
# j. Agent generation diversity
# ------------------------------------------------------------------

def test_agent_generation():
    """Generate 100 agents, verify diversity across states, categories, and protocol preferences."""
    agents = generate_agents(num_agents=100, budget_range=(5000, 50000), seed=42)
    assert len(agents) == 100

    # Multiple US states represented
    states = {a.state_idx % 10 for a in agents}
    assert len(states) >= 5, (
        f"Expected at least 5 distinct states, got {len(states)}"
    )

    # Multiple categories represented
    all_categories: set[str] = set()
    for a in agents:
        all_categories.update(a.preferred_categories)
    assert len(all_categories) >= 3, (
        f"Expected at least 3 categories, got {all_categories}"
    )

    # Some agents have protocol preferences, some do not
    with_pref = [a for a in agents if a.protocol_preference is not None]
    without_pref = [a for a in agents if a.protocol_preference is None]
    assert len(with_pref) > 0, "No agents with protocol preferences"
    assert len(without_pref) > 0, "All agents have protocol preferences -- no diversity"

    # Multiple distinct protocol preferences
    prefs = {a.protocol_preference for a in with_pref}
    assert len(prefs) >= 2, (
        f"Expected at least 2 distinct protocol preferences, got {prefs}"
    )

    # Budget diversity
    budgets = [a.budget for a in agents]
    assert max(budgets) > min(budgets), "All agents have the same budget"


# ------------------------------------------------------------------
# k. Scenarios validation
# ------------------------------------------------------------------

def test_scenarios():
    """Verify all 6 predefined scenarios have valid configs."""
    assert len(SCENARIOS) == 6, f"Expected 6 scenarios, got {len(SCENARIOS)}"

    expected_names = {
        "traditional_retail",
        "full_autonomy",
        "crypto_native",
        "micropayment_api",
        "protocol_arena",
        "stress_test",
    }
    assert set(SCENARIOS.keys()) == expected_names

    for name, config in SCENARIOS.items():
        assert isinstance(config, SimulationConfig), (
            f"Scenario '{name}' is not a SimulationConfig"
        )
        assert config.num_agents > 0, f"Scenario '{name}' has no agents"
        assert config.num_rounds > 0, f"Scenario '{name}' has no rounds"
        assert len(config.protocols) > 0, f"Scenario '{name}' has no protocols"
        for proto in config.protocols:
            assert isinstance(proto, Protocol), (
                f"Scenario '{name}' has invalid protocol: {proto}"
            )
        assert config.agent_budget_range[0] > 0, (
            f"Scenario '{name}' has zero min budget"
        )
        assert config.agent_budget_range[1] >= config.agent_budget_range[0], (
            f"Scenario '{name}' has invalid budget range"
        )

        # Every scenario should have a description
        assert name in SCENARIO_DESCRIPTIONS, (
            f"Scenario '{name}' missing description"
        )
        assert len(SCENARIO_DESCRIPTIONS[name]) > 10, (
            f"Scenario '{name}' has a trivially short description"
        )


def test_emergent_world_report_section():
    """Report includes MiroFish-style world/memory state without a live engine."""
    config = SimulationConfig(
        num_agents=2,
        num_rounds=1,
        protocols=[Protocol.X402, Protocol.ATXP],
        world_seed="test-agent-economy",
        scenario_prompt="agents compare payment protocols",
    )
    result = SimulationResult(config=config)
    result.trust_summary = {
        "x402": {"avg": 0.72, "min": 0.61, "max": 0.83},
        "atxp": {"avg": 0.66, "min": 0.55, "max": 0.77},
    }
    result.agent_memory_log = [
        AgentMemoryEvent(
            round_num=1,
            agent_id="agent_0001",
            agent_name="Alice_1",
            event_type="protocol_experience",
            protocol="x402",
            workload_type="api_micro",
            sentiment_delta=0.05,
            trust_before=0.6,
            trust_after=0.65,
            amount_cents=100,
            reason="payment_settled",
        )
    ]
    result.world_events = [
        EconomyWorldEvent(
            round_num=1,
            event_type="round_closed",
            summary="Round 1 closed with protocol trust changes.",
        )
    ]

    sections = ReportGenerator(result=result, agents=[]).generate()
    emergent = next((s for s in sections if s["title"] == "Emergent Agent Economy"), None)
    assert emergent is not None
    assert "test-agent-economy" in emergent["content"]
    assert "Agent memory events: 1" in emergent["content"]
    assert "X402" in emergent["content"]


def test_self_sustainability_report_section():
    """Report promotes treasury and route pressure as economy signals."""
    config = SimulationConfig(
        num_agents=2,
        num_rounds=1,
        protocols=[Protocol.X402, Protocol.ATXP],
    )
    result = SimulationResult(config=config)
    result.route_pressure_summary = [
        {
            "route_id": "base_direct_usdc",
            "source_domain": "base_usdc",
            "target_domain": "base_usdc",
            "primitive": "direct_same_domain",
            "protocols": ["x402", "atxp"],
            "total_usage_cents": 2_000_000,
            "max_capacity_ratio": 0.8,
            "pressure_rounds": 1,
            "last_pressure_level": "elevated",
        }
    ]
    result.world_events = [
        EconomyWorldEvent(
            round_num=1,
            event_type="treasury_rebalance",
            summary="merchant_test rebalanced $25.00 from gateway_unified_usdc to base_usdc.",
            actor_id="merchant_test",
            protocol="atxp",
        ),
        EconomyWorldEvent(
            round_num=1,
            event_type="route_pressure",
            summary="base_direct_usdc ran at 80.0% of round capacity.",
            protocol="x402",
        ),
    ]

    sections = ReportGenerator(result=result, agents=[]).generate()
    signals = next((s for s in sections if s["title"] == "Self-Sustainability Signals"), None)

    assert signals is not None
    assert signals["status"] == "ok"
    assert "Treasury rebalances: 1 succeeded, 0 failed" in signals["content"]
    assert "base_direct_usdc" in signals["content"]
    assert "$20,000.00" in signals["content"]


# ------------------------------------------------------------------
# l. Report generation
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_report_generation():
    """Run a small sim, generate report, verify all 6 sections present."""
    client = CommerceClient(ENGINE_URL)
    healthy = await _engine_available(client)
    await client.close()
    _skip_if_offline(healthy)

    config = SimulationConfig(
        num_agents=5,
        num_rounds=2,
        protocols=list(Protocol),
        engine_url=ENGINE_URL,
        seed=99,
        agent_budget_range=(50000, 100000),
    )
    engine = SimulationEngine(config)
    result = await engine.run()

    report_gen = ReportGenerator(result=result, agents=engine.agents)
    sections = report_gen.generate()

    # ReportGenerator.generate() produces:
    # 1 executive summary + up to 5 per-protocol + comparative ranking +
    # agent behavior + micropayment analysis + recommendations
    # Minimum 6 sections when all protocols are active
    assert len(sections) >= 6, (
        f"Expected at least 6 report sections, got {len(sections)}: "
        f"{[s['title'] for s in sections]}"
    )

    titles = [s["title"] for s in sections]

    # Verify key sections are present
    assert "Executive Summary" in titles
    assert "Comparative Ranking" in titles
    assert "Agent Behavior Analysis" in titles
    assert "Micropayment Analysis" in titles
    assert "Recommendations" in titles

    # At least one per-protocol section
    proto_sections = [t for t in titles if t.startswith("Protocol:")]
    assert len(proto_sections) >= 1, "No per-protocol sections in report"

    # Every section has content
    for section in sections:
        assert "title" in section
        assert "content" in section
        assert "status" in section
        assert len(section["content"]) > 0, (
            f"Section '{section['title']}' has empty content"
        )
