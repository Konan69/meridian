import unittest

from meridian_ap2_direct.contracts import (
    canonical_hash,
    rounded_usd_equal,
    settlement_contract_errors,
    settlement_semantic_errors,
)


def settlement_credential(
    *,
    actor_id: str = "agent-1",
    merchant: str = "merchant-a",
    amount_usd: float = 12.34,
) -> dict[str, object]:
    return {
        "actorId": actor_id,
        "merchant": merchant,
        "amountUsd": amount_usd,
        "cartMandate": {
            "contents": {
                "merchant_name": merchant,
                "payment_request": {
                    "details": {
                        "total": {"amount": {"currency": "USD", "value": amount_usd}},
                    },
                },
            },
        },
        "paymentMandate": {
            "payment_mandate_contents": {
                "merchant_agent": merchant,
                "payment_details_total": {
                    "amount": {"currency": "USD", "value": amount_usd},
                },
                "payment_response": {
                    "details": {"merchant": merchant, "memo": "offline contract"},
                },
            },
        },
    }


class ContractHelperTests(unittest.TestCase):
    def test_canonical_hash_is_order_independent(self) -> None:
        self.assertEqual(canonical_hash({"b": 2, "a": 1}), canonical_hash({"a": 1, "b": 2}))

    def test_settlement_contract_errors_accept_matching_shell_fields(self) -> None:
        self.assertEqual(
            settlement_contract_errors(
                {"merchant": "merchant-a", "amountUsd": 1.234},
                "merchant-a",
                1.23,
            ),
            [],
        )
        self.assertTrue(rounded_usd_equal(1.235, 1.24))

    def test_settlement_contract_errors_report_mismatches(self) -> None:
        self.assertEqual(
            settlement_contract_errors(
                {"merchant": "merchant-a", "amountUsd": 1.20},
                "merchant-b",
                1.21,
            ),
            ["merchant mismatch", "amount mismatch"],
        )

    def test_settlement_contract_errors_treat_bad_amount_as_mismatch(self) -> None:
        self.assertEqual(
            settlement_contract_errors(
                {"merchant": "merchant-a", "amountUsd": "bad"},
                "merchant-a",
                1.21,
            ),
            ["amount mismatch"],
        )

    def test_settlement_semantics_accept_matching_nested_mandates(self) -> None:
        self.assertEqual(
            settlement_semantic_errors(
                settlement_credential(amount_usd=12.345),
                actor_id="agent-1",
                merchant="merchant-a",
                amount_usd=12.35,
            ),
            [],
        )

    def test_settlement_semantics_bind_actor_and_nested_merchants(self) -> None:
        credential = settlement_credential(actor_id="agent-1", merchant="merchant-a")
        credential["cartMandate"]["contents"]["merchant_name"] = "merchant-b"
        credential["paymentMandate"]["payment_mandate_contents"]["merchant_agent"] = "merchant-b"
        credential["paymentMandate"]["payment_mandate_contents"]["payment_response"]["details"][
            "merchant"
        ] = "merchant-b"

        self.assertEqual(
            settlement_semantic_errors(
                credential,
                actor_id="agent-2",
                merchant="merchant-a",
                amount_usd=12.34,
            ),
            [
                "actor mismatch",
                "cart merchant mismatch",
                "payment merchant mismatch",
                "payment response merchant mismatch",
            ],
        )

    def test_settlement_semantics_bind_cart_and_payment_amounts(self) -> None:
        credential = settlement_credential(amount_usd=12.34)
        credential["cartMandate"]["contents"]["payment_request"]["details"]["total"]["amount"][
            "value"
        ] = 12.30
        credential["paymentMandate"]["payment_mandate_contents"]["payment_details_total"][
            "amount"
        ]["value"] = "bad"

        self.assertEqual(
            settlement_semantic_errors(
                credential,
                actor_id="agent-1",
                merchant="merchant-a",
                amount_usd=12.34,
            ),
            ["cart total amount mismatch", "payment total amount mismatch"],
        )

    def test_settlement_semantics_require_mandate_payloads(self) -> None:
        self.assertEqual(
            settlement_semantic_errors(
                {"actorId": "agent-1", "merchant": "merchant-a", "amountUsd": 12.34},
                actor_id="agent-1",
                merchant="merchant-a",
                amount_usd=12.34,
            ),
            [
                "cart mandate missing",
                "payment mandate missing",
                "cart merchant mismatch",
                "payment merchant mismatch",
                "payment response merchant mismatch",
                "cart total amount mismatch",
                "payment total amount mismatch",
            ],
        )
