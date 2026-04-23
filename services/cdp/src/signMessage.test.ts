import assert from "node:assert/strict";
import test from "node:test";
import {
  SignMessageRequestError,
  normalizeSignMessageRequest,
} from "./signMessage.js";

const address = "0x1111111111111111111111111111111111111111";

test("CDP sign-message normalizer builds SDK options offline", () => {
  assert.deepEqual(
    normalizeSignMessageRequest({
      address: ` ${address} `,
      message: "Authorize Meridian payment intent #42",
    }),
    {
      address,
      message: "Authorize Meridian payment intent #42",
    },
  );
});

test("CDP sign-message normalizer preserves exact message bytes", () => {
  const message = "  pay merchant\namount=12.50  ";
  assert.equal(
    normalizeSignMessageRequest({
      address,
      message,
    }).message,
    message,
  );
});

test("CDP sign-message normalizer accepts whitespace-only signed bytes", () => {
  const message = " \n\t ";
  assert.equal(normalizeSignMessageRequest({ address, message }).message, message);
});

test("CDP sign-message normalizer rejects malformed request shape", () => {
  assert.throws(
    () => normalizeSignMessageRequest(null),
    new SignMessageRequestError("request body must be an object"),
  );
  assert.throws(
    () => normalizeSignMessageRequest([]),
    /request body must be an object/,
  );
});

test("CDP sign-message normalizer rejects ambiguous message fields", () => {
  assert.throws(
    () => normalizeSignMessageRequest({ address, message: "" }),
    /message must be a non-empty string/,
  );
  assert.throws(
    () => normalizeSignMessageRequest({ address, message: 123 }),
    /message must be a non-empty string/,
  );
  assert.throws(
    () => normalizeSignMessageRequest({ address: "0x1", message: "hello" }),
    /address must be an EVM address/,
  );
});

test("CDP sign-message normalizer requires own request fields", () => {
  const inheritedMessage = Object.create({ address, message: "hello" });
  assert.throws(
    () => normalizeSignMessageRequest(inheritedMessage),
    /address is required/,
  );

  const inheritedAddress = Object.create({ address });
  inheritedAddress.message = "hello";
  assert.throws(
    () => normalizeSignMessageRequest(inheritedAddress),
    /address is required/,
  );

  const ownAddressInheritedMessage = Object.create({ message: "hello" });
  ownAddressInheritedMessage.address = address;
  assert.throws(
    () => normalizeSignMessageRequest(ownAddressInheritedMessage),
    /message is required/,
  );
});
