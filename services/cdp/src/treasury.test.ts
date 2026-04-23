import assert from "node:assert/strict";
import test from "node:test";
import {
  amountUnitsFromRequest,
  encodeErc20Transfer,
  isHexAddress,
  nativeValueWeiFromRequest,
  normalizeNativeTreasuryTransferRequest,
  normalizeUsdcTreasuryTransferRequest,
  parseDecimalUnits,
  treasuryTransferResponse,
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
  assert.throws(
    () => amountUnitsFromRequest({ amount: "1", amountUnits: "1" }, 6),
    /either amount or amountUnits/,
  );
  assert.throws(
    () => nativeValueWeiFromRequest({ amount: "1", amountWei: "1" }),
    /either amountWei/,
  );
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

test("CDP treasury USDC transfer normalizer builds request and response contract offline", () => {
  const transfer = normalizeUsdcTreasuryTransferRequest({
    fromAddress: "0x0000000000000000000000000000000000000001",
    toAddress: "0x1111111111111111111111111111111111111111",
    amount: "1.5",
  });

  assert.equal(transfer.kind, "usdc");
  assert.equal(transfer.token, "USDC");
  assert.equal(transfer.network, "base-sepolia");
  assert.equal(transfer.txOptions.address, "0x0000000000000000000000000000000000000001");
  assert.equal(transfer.txOptions.network, "base-sepolia");
  assert.equal(transfer.txOptions.transaction.to, "0x036CbD53842c5426634e7929541eC2318f3dCF7e");
  assert.equal(transfer.txOptions.transaction.value, 0n);
  assert.equal(
    transfer.txOptions.transaction.data,
    "0xa9059cbb0000000000000000000000001111111111111111111111111111111111111111000000000000000000000000000000000000000000000000000000000016e360",
  );

  assert.deepEqual(treasuryTransferResponse(transfer, { transactionHash: "0xabc" }), {
    token: "USDC",
    network: "base-sepolia",
    contractAddress: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    fromAddress: "0x0000000000000000000000000000000000000001",
    toAddress: "0x1111111111111111111111111111111111111111",
    amountUnits: "1500000",
    transaction: { transactionHash: "0xabc" },
  });
});

test("CDP treasury native transfer normalizer builds request and response contract offline", () => {
  const transfer = normalizeNativeTreasuryTransferRequest({
    fromAddress: "0x0000000000000000000000000000000000000001",
    toAddress: "0x1111111111111111111111111111111111111111",
    amountWei: "123",
    network: "base-sepolia",
  });

  assert.equal(transfer.kind, "native");
  assert.equal(transfer.token, "ETH");
  assert.equal(transfer.amountUnits, 123n);
  assert.equal(transfer.txOptions.address, "0x0000000000000000000000000000000000000001");
  assert.equal(transfer.txOptions.transaction.to, "0x1111111111111111111111111111111111111111");
  assert.equal(transfer.txOptions.transaction.value, 123n);
  assert.equal(transfer.txOptions.transaction.data, undefined);

  assert.deepEqual(treasuryTransferResponse(transfer, { hash: "0xdef" }), {
    token: "ETH",
    network: "base-sepolia",
    fromAddress: "0x0000000000000000000000000000000000000001",
    toAddress: "0x1111111111111111111111111111111111111111",
    amountWei: "123",
    transaction: { hash: "0xdef" },
  });
});

test("CDP treasury transfer normalizers require own request fields", () => {
  const inherited = Object.create({
    fromAddress: "0x0000000000000000000000000000000000000001",
    toAddress: "0x1111111111111111111111111111111111111111",
    amountUnits: "1",
  }) as Record<string, unknown>;

  assert.throws(() => normalizeUsdcTreasuryTransferRequest(inherited), /fromAddress is required/);
  assert.throws(
    () =>
      normalizeNativeTreasuryTransferRequest({
        fromAddress: "0x0000000000000000000000000000000000000001",
        toAddress: "0x1111111111111111111111111111111111111111",
        amountWei: "0",
      }),
    /greater than zero/,
  );
  assert.throws(
    () =>
      normalizeUsdcTreasuryTransferRequest({
        fromAddress: "0x0000000000000000000000000000000000000001",
        toAddress: "0x1111111111111111111111111111111111111111",
        amountUnits: "1",
        network: "base",
      }),
    /only support base-sepolia/,
  );
});
