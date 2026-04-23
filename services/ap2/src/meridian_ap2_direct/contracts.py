"""Small AP2 contract helpers that stay offline and dependency-light."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def rounded_usd_equal(left: float, right: float) -> bool:
    return round(float(left), 2) == round(float(right), 2)


def settlement_contract_errors(
    credential: dict[str, Any],
    merchant: str,
    amount_usd: float,
) -> list[str]:
    errors: list[str] = []
    if credential.get("merchant") != merchant:
        errors.append("merchant mismatch")

    credential_amount = credential.get("amountUsd")
    try:
        credential_amount_value = float(credential_amount)
    except (TypeError, ValueError):
        errors.append("amount mismatch")
    else:
        if not rounded_usd_equal(credential_amount_value, amount_usd):
            errors.append("amount mismatch")

    return errors
