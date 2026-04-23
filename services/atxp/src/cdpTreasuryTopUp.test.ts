import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_TREASURY_NATIVE_TOPUP_ETH,
  DEFAULT_TREASURY_USDC_TOPUP_UNITS,
  planCdpBaseTreasuryTopUp,
} from "./cdpTreasuryTopUp.js";

test("cdp-base treasury top-up planning is disabled without a treasury address", () => {
  assert.equal(planCdpBaseTreasuryTopUp(1n, {}), null);
});

test("cdp-base treasury top-up planning uses safe defaults", () => {
  const plan = planCdpBaseTreasuryTopUp(50n, {
    ATXP_CDP_TREASURY_ADDRESS: "0x0000000000000000000000000000000000000001",
  });

  assert.deepEqual(plan, {
    fromAddress: "0x0000000000000000000000000000000000000001",
    nativeAmount: DEFAULT_TREASURY_NATIVE_TOPUP_ETH,
    usdcAmountUnits: DEFAULT_TREASURY_USDC_TOPUP_UNITS,
  });
});

test("cdp-base treasury top-up planning covers the requested USDC minimum", () => {
  const plan = planCdpBaseTreasuryTopUp(2_500_000n, {
    ATXP_CDP_TREASURY_ADDRESS: " 0x0000000000000000000000000000000000000002 ",
    ATXP_CDP_TREASURY_NATIVE_TOPUP: "0.123",
    ATXP_CDP_TREASURY_USDC_TOPUP_UNITS: "1000000",
  });

  assert.deepEqual(plan, {
    fromAddress: "0x0000000000000000000000000000000000000002",
    nativeAmount: "0.123",
    usdcAmountUnits: 2_500_000n,
  });
});
