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

test("CDP sign-typed-data normalizer preserves exact type-key semantics", () => {
  const options = normalizeSignTypedDataRequest({
    address,
    domain: {},
    types: {
      "Ping Intent": [{ name: "nonce", type: "uint256" }],
    },
    primaryType: "Ping Intent",
    message: { nonce: 1 },
  });

  assert.equal(options.primaryType, "Ping Intent");
  assert.deepEqual(Object.keys(options.types), ["Ping Intent"]);

  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: {},
        types: { Ping: [{ name: "nonce", type: "uint256" }] },
        primaryType: " Ping ",
        message: { nonce: 1 },
      }),
    /primaryType must be defined in types/,
  );
});

test("CDP sign-typed-data normalizer requires own nested typed-data keys", () => {
  const inheritedDomain = Object.create({
    name: "Inherited Meridian",
    chainId: "84532",
  }) as Record<string, unknown>;
  const inheritedTypeField = Object.create({
    name: "nonce",
    type: "uint256",
  }) as Record<string, unknown>;
  const inheritedIdempotencyKey = Object.create({
    idempotencyKey: "inherited-key",
  }) as Record<string, unknown>;
  Object.assign(inheritedIdempotencyKey, {
    address,
    domain: {},
    types: { Ping: [{ name: "nonce", type: "uint256" }] },
    primaryType: "Ping",
    message: { nonce: 1 },
  });

  const options = normalizeSignTypedDataRequest({
    address,
    domain: inheritedDomain,
    types: { Ping: [{ name: "nonce", type: "uint256" }] },
    primaryType: "Ping",
    message: { nonce: 1 },
  });

  assert.equal(options.domain.name, undefined);
  assert.equal(options.domain.chainId, undefined);
  assert.equal(normalizeSignTypedDataRequest(inheritedIdempotencyKey).idempotencyKey, undefined);
  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: {},
        types: { Ping: [inheritedTypeField] },
        primaryType: "Ping",
        message: { nonce: 1 },
      }),
    /types.Ping\[0\].name is required/,
  );
  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: {},
        types: { Ping: [{ name: "nonce", type: "uint256", label: "Nonce" }] },
        primaryType: "Ping",
        message: { nonce: 1 },
      }),
    /types.Ping\[0\].label is not supported/,
  );
});

test("CDP sign-typed-data normalizer requires primary message own fields", () => {
  const inheritedMessage = Object.create({ nonce: 1 }) as Record<string, unknown>;

  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: {},
        types: { Ping: [{ name: "nonce", type: "uint256" }] },
        primaryType: "Ping",
        message: inheritedMessage,
      }),
    /message.nonce is required by primaryType Ping/,
  );
  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: {},
        types: {
          Ping: [
            { name: "nonce", type: "uint256" },
            { name: "nonce", type: "uint256" },
          ],
        },
        primaryType: "Ping",
        message: { nonce: 1 },
      }),
    /types.Ping contains duplicate field nonce/,
  );
  assert.throws(
    () =>
      normalizeSignTypedDataRequest({
        address,
        domain: {},
        types: { Ping: [{ name: "nonce ", type: "uint256" }] },
        primaryType: "Ping",
        message: { nonce: 1 },
      }),
    /message\.nonce\s+is required by primaryType Ping/,
  );
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
  assert.throws(
    () => {
      const request = Object.create({
        address,
        domain: {},
        types: { Ping: [{ name: "nonce", type: "uint256" }] },
        primaryType: "Ping",
        message: { nonce: 1 },
      }) as Record<string, unknown>;
      return normalizeSignTypedDataRequest(request);
    },
    /types is required/,
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
        domain: { name: "   " },
        types: { Ping: [{ name: "nonce", type: "uint256" }] },
        primaryType: "Ping",
        message: { nonce: 1 },
      }),
    /domain.name must be a non-empty string/,
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
