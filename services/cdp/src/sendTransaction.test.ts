import assert from "node:assert/strict";
import test from "node:test";
import {
  SendTransactionRequestError,
  normalizeSendTransactionRequest,
} from "./sendTransaction.js";

const from = "0x1111111111111111111111111111111111111111";
const to = "0x2222222222222222222222222222222222222222";

test("CDP send-transaction normalizer builds SDK options offline", () => {
  assert.deepEqual(
    normalizeSendTransactionRequest({
      address: ` ${from} `,
      network: "base-sepolia",
      transaction: {
        to,
        data: "0xA0",
        value: "123",
        gas: "21000",
        maxFeePerGas: 42,
        maxPriorityFeePerGas: 1n,
        nonce: "7",
      },
    }),
    {
      address: from,
      network: "base-sepolia",
      transaction: {
        to,
        data: "0xA0",
        value: 123n,
        gas: 21000n,
        maxFeePerGas: 42n,
        maxPriorityFeePerGas: 1n,
        nonce: 7,
      },
    },
  );
});

test("CDP send-transaction normalizer defaults value to zero and preserves base", () => {
  const txOptions = normalizeSendTransactionRequest({
    address: from,
    network: "base",
    transaction: { to },
  });

  assert.equal(txOptions.network, "base");
  assert.equal(txOptions.transaction.value, 0n);
  assert.equal(txOptions.transaction.gas, undefined);
});

test("CDP send-transaction normalizer rejects malformed shape and network", () => {
  assert.throws(
    () => normalizeSendTransactionRequest(null),
    new SendTransactionRequestError("request body must be an object"),
  );
  assert.throws(
    () => normalizeSendTransactionRequest({ address: from, network: "solana", transaction: { to } }),
    /network must be base-sepolia or base/,
  );
  assert.throws(
    () => normalizeSendTransactionRequest({ address: "0x1", network: "base", transaction: { to } }),
    /address must be an EVM address/,
  );
});

test("CDP send-transaction normalizer rejects ambiguous transaction fields", () => {
  assert.throws(
    () => normalizeSendTransactionRequest({ address: from, network: "base", transaction: { to, value: "-1" } }),
    /transaction.value must be a non-negative integer string/,
  );
  assert.throws(
    () => normalizeSendTransactionRequest({ address: from, network: "base", transaction: { to, gas: 1.2 } }),
    /transaction.gas must be a non-negative integer/,
  );
  assert.throws(
    () => normalizeSendTransactionRequest({ address: from, network: "base", transaction: { to, data: "0x123" } }),
    /transaction.data must be 0x-prefixed hex bytes/,
  );
  assert.throws(
    () =>
      normalizeSendTransactionRequest({
        address: from,
        network: "base",
        transaction: { to, nonce: Number.MAX_SAFE_INTEGER + 1 },
      }),
    /transaction.nonce must be a non-negative integer/,
  );
});
