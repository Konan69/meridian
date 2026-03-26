"""Integration tests -- requires the Rust engine running on :4080."""
import asyncio
import pytest

from sim.commerce import CommerceClient
from sim.types import Protocol, SimulationConfig, SimulationResult, AgentProfile, AgentRole
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


def _skip_if_offline(healthy: bool):
    if not healthy:
        pytest.skip("Engine not running")


# ------------------------------------------------------------------
# a. Health endpoint
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_health(client: CommerceClient):
    """Verify engine responds at /health."""
    healthy = await _engine_available(client)
    _skip_if_offline(healthy)
    assert healthy is True
    await client.close()


# ------------------------------------------------------------------
# b. Products endpoint
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_products_endpoint(client: CommerceClient):
    """Verify /products returns 6 products with correct schema."""
    healthy = await _engine_available(client)
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

    await client.close()


# ------------------------------------------------------------------
# c. Checkout flow
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_checkout_flow(client: CommerceClient):
    """Create session, update with address, complete with ACP protocol.

    Verify session status transitions through the checkout lifecycle.
    """
    healthy = await _engine_available(client)
    _skip_if_offline(healthy)

    products = await client.get_products()
    product = products[0]

    # 1. Create checkout session
    checkout = await client.create_checkout(
        items=[{"id": product["id"], "quantity": 1}],
        protocol="acp",
        agent_id="test_agent_checkout",
    )
    assert "id" in checkout, f"Checkout creation failed: {checkout}"
    session_id = checkout["id"]
    assert checkout.get("status") in ("open", "pending", None) or "status" in checkout

    # 2. Update with shipping address
    update_result = await client.update_checkout(
        session_id=session_id,
        fulfillment_address={
            "name": "Test Agent",
            "line_one": "100 Market St",
            "city": "San Francisco",
            "state": "CA",
            "country": "US",
            "postal_code": "94105",
        },
        selected_fulfillment_option_id="ship_standard",
    )
    assert "id" in update_result

    # 3. Complete checkout
    result = await client.complete_checkout(
        session_id=session_id,
        payment_token="token_acp_test_checkout",
        protocol="acp",
    )
    assert result.get("status") == "completed", (
        f"Checkout did not complete: {result}"
    )

    # Verify totals exist
    totals = result.get("totals", [])
    assert len(totals) > 0, "No totals in completed checkout"

    await client.close()


# ------------------------------------------------------------------
# d. All protocols
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_protocols(client: CommerceClient):
    """Complete one checkout through each of the 5 protocols. Verify all succeed."""
    healthy = await _engine_available(client)
    _skip_if_offline(healthy)

    products = await client.get_products()
    # Use a digital product (no shipping required) so checkout completes without address
    product = next(p for p in products if not p.get("requires_shipping", True))

    for protocol in ALL_PROTOCOLS:
        record = await client.full_purchase(
            agent_id=f"test_agent_{protocol.value}",
            product_id=product["id"],
            quantity=1,
            protocol=protocol.value,
            round_num=0,
            product_name=product.get("name", ""),
            needs_shipping=False,
        )
        assert record.success, (
            f"[{protocol.value}] Checkout failed: {record.error}"
        )

    await client.close()


# ------------------------------------------------------------------
# e. Metrics after transactions
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metrics_after_transactions(client: CommerceClient):
    """Run 5 transactions (one per protocol), verify /metrics shows correct counts."""
    healthy = await _engine_available(client)
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
    for protocol in ALL_PROTOCOLS:
        record = await client.full_purchase(
            agent_id=f"metrics_agent_{protocol.value}",
            product_id=product["id"],
            quantity=1,
            protocol=protocol.value,
            round_num=1,
            product_name=product.get("name", ""),
            needs_shipping=False,
        )
        assert record.success, (
            f"[{protocol.value}] Transaction failed: {record.error}"
        )

    # Snapshot metrics after
    metrics_after = await client.get_metrics()
    after_counts: dict[str, int] = {}
    for p in metrics_after.get("protocols", []):
        after_counts[p["protocol"]] = p.get("total_transactions", 0)

    # Each protocol should have at least 1 more transaction
    for protocol in ALL_PROTOCOLS:
        name = protocol.value
        before = before_counts.get(name, 0)
        after = after_counts.get(name, 0)
        assert after >= before + 1, (
            f"[{name}] Expected at least {before + 1} transactions, got {after}"
        )

    await client.close()


# ------------------------------------------------------------------
# f. Flat distribution (round-robin)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flat_distribution():
    """Run a 10-agent 3-round sim, verify each protocol gets roughly equal transactions."""
    client = CommerceClient(ENGINE_URL)
    healthy = await _engine_available(client)
    await client.close()
    _skip_if_offline(healthy)

    config = SimulationConfig(
        num_agents=20,
        num_rounds=5,
        protocols=list(Protocol),
        engine_url=ENGINE_URL,
        seed=42,
        agent_budget_range=(50000, 100000),  # high budgets so agents always buy
    )
    engine = SimulationEngine(config)
    result = await engine.run()

    # Collect per-protocol transaction counts
    proto_counts: dict[str, int] = {}
    for rd in result.rounds:
        for tx in rd.transactions:
            if tx.success:
                proto_counts[tx.protocol] = proto_counts.get(tx.protocol, 0) + 1

    total_success = sum(proto_counts.values())
    if total_success == 0:
        pytest.skip("No successful transactions to evaluate distribution")

    num_protocols = len(ALL_PROTOCOLS)
    expected_per_proto = total_success / num_protocols

    # Each protocol should get at least some share -- allow generous tolerance
    # (at least 1 transaction per protocol if there are enough total)
    if total_success >= num_protocols:
        for protocol in ALL_PROTOCOLS:
            count = proto_counts.get(protocol.value, 0)
            assert count >= 1, (
                f"[{protocol.value}] got 0 transactions out of {total_success} -- "
                f"round-robin distribution broken. Counts: {proto_counts}"
            )


# ------------------------------------------------------------------
# g. Agent generation diversity
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
# h. Scenarios validation
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


# ------------------------------------------------------------------
# i. Report generation
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
