import assert from "node:assert/strict";
import test from "node:test";
import {
  amountUnitsFromRequest,
  encodeErc20Transfer,
  isHexAddress,
  nativeValueWeiFromRequest,
  parseDecimalUnits,
} from "./treasury.js";

test("CDP treasury helpers parse decimal and unit amounts deterministically", () => {
  assert.equal(parseDecimalUnits("1.25", 6), 1_250_000n);
  assert.equal(amountUnitsFromRequest({ amount: "0.000001" }, 6), 1n);
  assert.equal(amountUnitsFromRequest({ amountUnits: "42" }, 6), 42n);
  assert.equal(nativeValueWeiFromRequest({ amount: "0.000000000000000001" }), 1n);
  assert.equal(nativeValueWeiFromRequest({ amountWei: "123" }), 123n);
});

test("CDP treasury helpers reject ambiguous amounts and malformed addresses", () => {
  assert.equal(isHexAddress("0x0000000000000000000000000000000000000001"), true);
  assert.equal(isHexAddress("0x1"), false);
  assert.throws(() => parseDecimalUnits("-1", 6), /non-negative decimal/);
  assert.throws(() => parseDecimalUnits("0.0000001", 6), /at most 6/);
  assert.throws(() => amountUnitsFromRequest({}, 6), /amount or amountUnits/);
  assert.throws(() => amountUnitsFromRequest({ amountUnits: "1.1" }, 6), /integer/);
});

test("CDP treasury USDC transfer encoding matches ERC-20 transfer calldata", () => {
  const data = encodeErc20Transfer(
    "0x1111111111111111111111111111111111111111",
    1_000_000n,
  );

  assert.equal(
    data,
    "0xa9059cbb000000000000000000000000111111111111111111111111111111111111111100000000000000000000000000000000000000000000000000000000000f4240",
  );
});
