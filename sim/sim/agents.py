"""Agent profile generation for Meridian simulations."""

import random
from .types import AgentProfile, AgentRole, Protocol


FIRST_NAMES = [
    "Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank",
    "Iris", "Jake", "Kate", "Leo", "Maya", "Nick", "Olga", "Paul",
    "Quinn", "Rosa", "Sam", "Tina", "Uma", "Vic", "Wendy", "Xander",
    "Yara", "Zane", "Aria", "Blake", "Cleo", "Dax", "Elsa", "Finn",
    "Gaia", "Hugo", "Ivy", "Jace", "Kira", "Liam", "Mila", "Noah",
    "Opal", "Pax", "Remy", "Sage", "Theo", "Uri", "Vale", "Wren",
]

CATEGORIES = ["footwear", "electronics", "food", "digital", "hardware"]

PERSONAS = [
    {"price_sensitivity": 0.9, "brand_loyalty": 0.1, "risk_tolerance": 0.2, "desc": "bargain hunter"},
    {"price_sensitivity": 0.3, "brand_loyalty": 0.8, "risk_tolerance": 0.5, "desc": "brand loyalist"},
    {"price_sensitivity": 0.5, "brand_loyalty": 0.3, "risk_tolerance": 0.9, "desc": "early adopter"},
    {"price_sensitivity": 0.7, "brand_loyalty": 0.5, "risk_tolerance": 0.5, "desc": "practical shopper"},
    {"price_sensitivity": 0.2, "brand_loyalty": 0.2, "risk_tolerance": 0.7, "desc": "impulse buyer"},
    {"price_sensitivity": 0.6, "brand_loyalty": 0.6, "risk_tolerance": 0.3, "desc": "cautious consumer"},
    {"price_sensitivity": 0.4, "brand_loyalty": 0.4, "risk_tolerance": 0.6, "desc": "balanced buyer"},
]


def generate_agents(
    num_agents: int,
    budget_range: tuple[int, int] = (5000, 50000),
    seed: int = 42,
) -> list[AgentProfile]:
    """Generate a diverse set of buyer agents with varied personas."""
    rng = random.Random(seed)
    agents = []

    for i in range(num_agents):
        persona = rng.choice(PERSONAS)
        name = rng.choice(FIRST_NAMES)
        budget = rng.randint(budget_range[0], budget_range[1])
        num_cats = rng.randint(1, 3)
        preferred = rng.sample(CATEGORIES, num_cats)

        protocol_pref = None
        if rng.random() < 0.3:
            protocol_pref = rng.choice(list(Protocol))

        agents.append(AgentProfile(
            agent_id=f"agent_{i:04d}",
            name=f"{name}_{i}",
            role=AgentRole.BUYER,
            budget=budget,
            price_sensitivity=max(0.0, min(1.0, persona["price_sensitivity"] + rng.gauss(0, 0.05))),
            brand_loyalty=max(0.0, min(1.0, persona["brand_loyalty"] + rng.gauss(0, 0.05))),
            preferred_categories=preferred,
            risk_tolerance=max(0.0, min(1.0, persona["risk_tolerance"] + rng.gauss(0, 0.05))),
            protocol_preference=protocol_pref,
            state_idx=i,  # distribute across US states
            checkout_patience=max(0.0, min(1.0, 0.5 + rng.gauss(0, 0.2))),
            social_influence=max(0.0, min(1.0, 0.5 + rng.gauss(0, 0.2))),
            protocol_trust={p.value: 0.6 for p in Protocol},
        ))

    return agents
