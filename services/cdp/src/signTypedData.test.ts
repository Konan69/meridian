import assert from "node:assert/strict";
import test from "node:test";
import {
  SignTypedDataRequestError,
  normalizeSignTypedDataRequest,
} from "./signTypedData.js";

const address = "0x1111111111111111111111111111111111111111";
const verifyingContract = "0x2222222222222222222222222222222222222222";

test("CDP sign-typed-data normalizer builds SDK options offline", () => {
  assert.deepEqual(
    normalizeSignTypedDataRequest({
      address: ` ${address} `,
      domain: {
        name: "Meridian",
        version: "1",
        chainId: "84532",
        verifyingContract: ` ${verifyingContract} `,
        salt: "0x0000000000000000000000000000000000000000000000000000000000000001",
      },
      types: {
        TransferIntent: [
          { name: "merchant", type: "address" },
          { name: "amount", type: "uint256" },
        ],
      },
      primaryType: "TransferIntent",
      message: {
        merchant: verifyingContract,
        amount: "250000",
      },
      idempotencyKey: " typed-data-1 ",
    }),
    {
      address,
      domain: {
        name: "Meridian",
        version: "1",
        chainId: 84532,
        verifyingContract,
        salt: "0x0000000000000000000000000000000000000000000000000000000000000001",
      },
      types: {
        TransferIntent: [
          { name: "merchant", type: "address" },
          { name: "amount", type: "uint256" },
        ],
      },
      primaryType: "TransferIntent",
      message: {
        merchant: verifyingContract,
        amount: "250000",
      },
      idempotencyKey: "typed-data-1",
    },
  );
});

test("CDP sign-typed-data normalizer preserves minimal typed data", () => {
  const options = normalizeSignTypedDataRequest({
    address,
    domain: {},
    types: {
      Ping: [{ name: "nonce", type: "uint256" }],
    },
    primaryType: "Ping",
    message: { nonce: 1 },
  });

  assert.deepEqual(options.domain, {
    name: undefined,
    version: undefined,
    chainId: undefined,
    verifyingContract: undefined,
    salt: undefined,
  });
  assert.equal(options.idempotencyKey, undefined);
});

test("CDP sign-typed-data normalizer rejects malformed request shape", () => {
  assert.throws(
    () => normalizeSignTypedDataRequest(null),
    new SignTypedDataRequestError("request body must be an object"),
  );
  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address: "0x1",
        domain: {},
        types: { Ping: [{ name: "nonce", type: "uint256" }] },
        primaryType: "Ping",
        message: { nonce: 1 },
      }),
    /address must be an EVM address/,
  );
  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: [],
        types: { Ping: [{ name: "nonce", type: "uint256" }] },
        primaryType: "Ping",
        message: { nonce: 1 },
      }),
    /domain must be an object/,
  );
});

test("CDP sign-typed-data normalizer rejects ambiguous typed data", () => {
  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: { verifyingContract: "0x1" },
        types: { Ping: [{ name: "nonce", type: "uint256" }] },
        primaryType: "Ping",
        message: { nonce: 1 },
      }),
    /domain.verifyingContract must be an EVM address/,
  );
  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: { salt: "0x1234" },
        types: { Ping: [{ name: "nonce", type: "uint256" }] },
        primaryType: "Ping",
        message: { nonce: 1 },
      }),
    /domain.salt must be a 32-byte 0x-prefixed hex string/,
  );
  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: { chainId: Number.MAX_SAFE_INTEGER + 1 },
        types: { Ping: [{ name: "nonce", type: "uint256" }] },
        primaryType: "Ping",
        message: { nonce: 1 },
      }),
    /domain.chainId must be a non-negative safe integer/,
  );
  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: {},
        types: { Ping: [] },
        primaryType: "Ping",
        message: { nonce: 1 },
      }),
    /types.Ping must be a non-empty array/,
  );
  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: {},
        types: { Ping: [{ name: "nonce", type: "uint256" }] },
        primaryType: "Pong",
        message: { nonce: 1 },
      }),
    /primaryType must be defined in types/,
  );
});
