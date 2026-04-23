import assert from "node:assert/strict";
import test from "node:test";
import {
  amountUsdFromRequest,
  isHexAddress,
  merchantFromRequest,
  validateMppExecuteRequest,
} from "./mppRequest.js";

test("MPP request helpers normalize merchant and amount from query params", () => {
  const request = new Request(
    "http://localhost:3020/mpp/paid?merchant=%20corner-store%20&amountUsd=1.235",
  );

  assert.equal(merchantFromRequest(request), "corner-store");
  assert.equal(amountUsdFromRequest(request), "1.24");
});

test("MPP request helpers fall back to safe defaults", () => {
  const request = new Request("http://localhost:3020/mpp/paid?amountUsd=-3");

  assert.equal(merchantFromRequest(request), "meridian-mpp-merchant");
  assert.equal(amountUsdFromRequest(request), "0.01");
});

test("MPP execute validation trims ids and rejects invalid payment requests", () => {
  assert.deepEqual(
    validateMppExecuteRequest({
      actorId: " actor-1 ",
      merchant: " market-1 ",
      amountUsd: 0.5,
    }),
    {
      actorId: "actor-1",
      merchant: "market-1",
      amountUsd: 0.5,
    },
  );
  assert.throws(() => validateMppExecuteRequest({ actorId: "a", merchant: "m", amountUsd: 0 }));
  assert.equal(isHexAddress("0x0000000000000000000000000000000000000000"), true);
  assert.equal(isHexAddress("not-an-address"), false);
});
