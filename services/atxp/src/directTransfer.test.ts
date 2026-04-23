import assert from "node:assert/strict";
import test from "node:test";
import {
  DirectTransferRequestError,
  expectedUsdcUnits,
  normalizeDirectTransferRequest,
  parseAtxpCredential,
  parseRawTxCredential,
} from "./directTransfer.js";

test("ATXP direct-transfer parser accepts supported raw transaction credentials", () => {
  assert.deepEqual(
    parseRawTxCredential(
      JSON.stringify({
        transactionId: `0x${"a".repeat(64)}`,
        chain: "base_sepolia",
        currency: "USDC",
      }),
    ),
    {
      transactionId: `0x${"a".repeat(64)}`,
      chain: "base_sepolia",
      currency: "USDC",
    },
  );
});

test("ATXP direct-transfer parser rejects malformed raw transaction credentials", () => {
  assert.equal(parseRawTxCredential("not-json"), null);
  assert.equal(
    parseRawTxCredential(
      JSON.stringify({
        transactionId: "0x123",
        chain: "base_sepolia",
        currency: "USDC",
      }),
    ),
    null,
  );
  assert.equal(
    parseRawTxCredential(
      JSON.stringify({
        transactionId: `0x${"a".repeat(64)}`,
        chain: "unsupported",
        currency: "USDC",
      }),
    ),
    null,
  );
});

test("ATXP direct-transfer parser keeps official ATXP credentials object-shaped", () => {
  assert.deepEqual(
    parseAtxpCredential(
      JSON.stringify({
        sourceAccountId: "base:0xabc",
        sourceAccountToken: "token",
        options: [],
      }),
    ),
    {
      sourceAccountId: "base:0xabc",
      sourceAccountToken: "token",
      options: [],
    },
  );
  assert.equal(parseAtxpCredential("[]"), null);
  assert.equal(parseAtxpCredential("not-json"), null);
});

test("ATXP direct-transfer expected amount rounds up to USDC units", () => {
  assert.equal(expectedUsdcUnits(0.01), 10_000n);
  assert.equal(expectedUsdcUnits(0.010001), 10_001n);
  assert.equal(expectedUsdcUnits(1.2345671), 1_234_568n);
});

test("ATXP direct-transfer request normalizer requires own settlement fields", () => {
  assert.deepEqual(
    normalizeDirectTransferRequest({
      merchant: " merchant-a ",
      amountUsd: 1.2345671,
      memo: "invoice-1",
    }),
    {
      merchant: "merchant-a",
      amountUsd: 1.2345671,
      memo: "invoice-1",
    },
  );

  const inheritedMerchant = Object.create({ merchant: "merchant-a" });
  inheritedMerchant.amountUsd = 1;
  assert.throws(
    () => normalizeDirectTransferRequest(inheritedMerchant),
    new DirectTransferRequestError("merchant must be a non-empty string"),
  );

  const inheritedAmount = Object.create({ amountUsd: 1 });
  inheritedAmount.merchant = "merchant-a";
  assert.throws(
    () => normalizeDirectTransferRequest(inheritedAmount),
    new DirectTransferRequestError("amountUsd must be a positive finite number"),
  );
});

test("ATXP direct-transfer request normalizer rejects unsafe amount boundaries", () => {
  for (const amountUsd of [0, -0.01, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.throws(
      () => normalizeDirectTransferRequest({ merchant: "merchant-a", amountUsd }),
      new DirectTransferRequestError("amountUsd must be a positive finite number"),
    );
    assert.throws(
      () => expectedUsdcUnits(amountUsd),
      new DirectTransferRequestError("amountUsd must be a positive finite number"),
    );
  }
});
