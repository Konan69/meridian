import assert from "node:assert/strict";
import test from "node:test";
import { createHmac } from "node:crypto";
import { deriveMppPrivateKey } from "./mppKeys.js";

test("MPP key derivation is deterministic for a seed, scope, and id", () => {
  const expectedDigest = createHmac("sha256", "seed-a")
    .update("mpp-actor:agent-1")
    .digest("hex");

  assert.equal(deriveMppPrivateKey("mpp-actor", "agent-1", "seed-a"), `0x${expectedDigest}`);
  assert.equal(deriveMppPrivateKey("mpp-actor", "agent-1", "seed-a").length, 66);
});

test("MPP key derivation separates actor and merchant scopes", () => {
  assert.notEqual(
    deriveMppPrivateKey("mpp-actor", "same-id", "seed-a"),
    deriveMppPrivateKey("mpp-merchant", "same-id", "seed-a"),
  );
});

test("MPP key derivation fails before runtime execution when seed is missing", () => {
  assert.throws(
    () => deriveMppPrivateKey("mpp-actor", "agent-1", ""),
    /MPP_MASTER_SEED is required/,
  );
});
