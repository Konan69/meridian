import unittest

from meridian_ap2_direct.contracts import (
    canonical_hash,
    rounded_usd_equal,
    settlement_contract_errors,
)


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
