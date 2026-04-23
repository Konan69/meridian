import assert from "node:assert/strict";
import test from "node:test";
import {
  amountUsdFromRequest,
  isHexAddress,
  merchantFromRequest,
  paidResourcePayloadForMppSettlement,
  paidResourceUrlForMppExecute,
  settlementResponseForMppExecute,
  validateMppAuthorizeRequest,
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

test("MPP authorize helper normalizes payment session semantics offline", () => {
  assert.deepEqual(
    validateMppAuthorizeRequest({
      actorId: " buyer-7 ",
      merchant: " coffee-cart ",
      amountUsd: 2.5,
    }),
    {
      actorId: "buyer-7",
      merchant: "coffee-cart",
      amountUsd: 2.5,
      memo: "meridian-mpp:buyer-7:coffee-cart",
    },
  );

  assert.deepEqual(
    validateMppAuthorizeRequest({
      actorId: "buyer-7",
      merchant: "coffee-cart",
      amountUsd: 2.5,
      memo: " morning run ",
    }),
    {
      actorId: "buyer-7",
      merchant: "coffee-cart",
      amountUsd: 2.5,
      memo: "morning run",
    },
  );

  assert.throws(() =>
    validateMppAuthorizeRequest({
      actorId: "buyer-7",
      merchant: "coffee-cart",
      amountUsd: Number.NaN,
    }),
  );
});

test("MPP execute helper builds a paid-resource URL with encoded merchant and rounded amount", () => {
  assert.equal(
    paidResourceUrlForMppExecute("http://localhost:3020", {
      actorId: "buyer-7",
      merchant: "coffee cart/北",
      amountUsd: 1.235,
    }),
    "http://localhost:3020/mpp/paid?merchant=coffee+cart%2F%E5%8C%97&amountUsd=1.24",
  );
});

test("MPP settlement helpers bind paid resource and execute response semantics", () => {
  const paidRequest = new Request(
    "http://localhost:3020/mpp/paid?merchant=%20coffee-cart%20&amountUsd=3.455",
  );
  const recipient = "0x1111111111111111111111111111111111111111";
  const paidPayload = paidResourcePayloadForMppSettlement(paidRequest, recipient);

  assert.deepEqual(paidPayload, {
    ok: true,
    message: "MPP payment accepted",
    recipient,
    merchant: "coffee-cart",
    amountUsd: 3.46,
  });

  assert.deepEqual(
    settlementResponseForMppExecute(
      { actorId: "buyer-7", merchant: "coffee-cart", amountUsd: 3.46 },
      { reference: "mpp_receipt_123" },
      paidPayload,
    ),
    {
      ok: true,
      actorId: "buyer-7",
      merchant: "coffee-cart",
      amountUsd: 3.46,
      receipt: { reference: "mpp_receipt_123" },
      paymentId: "mpp_receipt_123",
      response: paidPayload,
    },
  );
});
