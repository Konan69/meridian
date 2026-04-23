"""Small AP2 contract helpers that stay offline and dependency-light."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def rounded_usd_equal(left: float, right: float) -> bool:
    return round(float(left), 2) == round(float(right), 2)


def _nested_value(value: Any, path: Sequence[str]) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _amount_error(value: Any, expected: float, label: str) -> str | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return f"{label} amount mismatch"
    if not rounded_usd_equal(amount, expected):
        return f"{label} amount mismatch"
    return None


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


def settlement_semantic_errors(
    credential: dict[str, Any],
    *,
    actor_id: str,
    merchant: str,
    amount_usd: float,
) -> list[str]:
    """Validate AP2 settlement fields that must agree before receipt creation."""

    errors = settlement_contract_errors(credential, merchant, amount_usd)

    if credential.get("actorId") != actor_id:
        errors.append("actor mismatch")

    cart = credential.get("cartMandate")
    payment = credential.get("paymentMandate")
    if not isinstance(cart, dict):
        errors.append("cart mandate missing")
        cart = {}
    if not isinstance(payment, dict):
        errors.append("payment mandate missing")
        payment = {}

    merchant_checks = [
        ("cart merchant mismatch", _nested_value(cart, ["contents", "merchant_name"])),
        (
            "payment merchant mismatch",
            _nested_value(payment, ["payment_mandate_contents", "merchant_agent"]),
        ),
        (
            "payment response merchant mismatch",
            _nested_value(
                payment,
                ["payment_mandate_contents", "payment_response", "details", "merchant"],
            ),
        ),
    ]
    for label, value in merchant_checks:
        if value != merchant:
            errors.append(label)

    amount_checks = [
        (
            "cart total",
            _nested_value(
                cart,
                [
                    "contents",
                    "payment_request",
                    "details",
                    "total",
                    "amount",
                    "value",
                ],
            ),
        ),
        (
            "payment total",
            _nested_value(
                payment,
                [
                    "payment_mandate_contents",
                    "payment_details_total",
                    "amount",
                    "value",
                ],
            ),
        ),
    ]
    for label, value in amount_checks:
        error = _amount_error(value, amount_usd, label)
        if error:
            errors.append(error)

    return errors
