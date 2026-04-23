"""Static drift check for the simulation payload documentation.

Run from the repository root:

    python3 sim/tests/payload_contract_static.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import fields
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sim"))

from sim.types import (  # noqa: E402
    AgentMemoryEvent,
    EconomyWorldEvent,
    RoundSummary,
    SimulationResult,
)


def code_tokens(text: str) -> set[str]:
    return set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", text))


def assert_no_payload_doc_drift() -> None:
    contract = (ROOT / "docs/simulation-payload-contract.md").read_text()
    architecture = (ROOT / "docs/simulation-architecture.md").read_text()
    helper_source = (ROOT / "web/src/lib/simStream.ts").read_text()
    tokens = code_tokens(contract)

    assert "docs/simulation-payload-contract.md" in architecture

    for payload_type in (
        AgentMemoryEvent,
        EconomyWorldEvent,
        RoundSummary,
        SimulationResult,
    ):
        assert payload_type.__name__ in tokens
        missing_fields = sorted(
            field.name for field in fields(payload_type)
            if field.name not in tokens
        )
        assert missing_fields == [], (
            f"{payload_type.__name__} fields missing from payload contract: "
            f"{', '.join(missing_fields)}"
        )

    exported_helpers = set(
        re.findall(
            r"^export function ([A-Za-z_][A-Za-z0-9_]*)",
            helper_source,
            re.MULTILINE,
        )
    )
    assert exported_helpers
    missing_helpers = sorted(exported_helpers - tokens)
    assert missing_helpers == [], (
        "simStream exports missing from payload contract: "
        f"{', '.join(missing_helpers)}"
    )

    stream_events = {
        "setup",
        "simulation_start",
        "round_complete",
        "simulation_complete",
        "purchase",
        "purchase_failed",
        "route_execution",
        "balance_update",
        "agent_memory",
        "trust_snapshot",
        "world_event",
        "route_pressure",
        "treasury_rebalance",
        "treasury_rebalance_failed",
        "treasury_posture",
        "social_memory_diffusion",
        "merchant_switch",
        "agent_preference_shift",
        "rail_pnl_update",
        "market_snapshot",
    }
    missing_events = sorted(stream_events - tokens)
    assert missing_events == [], (
        "stream events missing from payload contract: "
        f"{', '.join(missing_events)}"
    )

    required_phrases = (
        "ref/mirofish",
        "ref/deps/*",
        "OASIS",
        "CAMEL",
        "reference rails",
        "unknown fields",
        "python3 sim/tests/payload_contract_static.py",
    )
    missing_phrases = sorted(
        phrase for phrase in required_phrases
        if phrase not in contract
    )
    assert missing_phrases == [], (
        "reference/maintenance guidance missing from payload contract: "
        f"{', '.join(missing_phrases)}"
    )


if __name__ == "__main__":
    assert_no_payload_doc_drift()
    print("simulation payload contract ok")
