import "dotenv/config";
import { randomBytes } from "node:crypto";
import { serve } from "@hono/node-server";
import { Hono } from "hono";
import { Mppx as ClientMppx, tempo as tempoClient } from "mppx/client";
import { Credential, Receipt } from "mppx";
import { Mppx as ServerMppx, tempo } from "mppx/server";
import Stripe from "stripe";
import { createClient, http } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { tempoModerato } from "viem/chains";
import { Actions } from "viem/tempo";
import {
  amountUsdFromRequest,
  isHexAddress,
  merchantFromRequest,
  validateMppExecuteRequest,
  type MppExecuteRequest,
} from "./mppRequest.js";
import { deriveMppPrivateKey } from "./mppKeys.js";

const app = new Hono();
const port = process.env.PORT ? parseInt(process.env.PORT, 10) : 3020;
const stripeSecretKey = process.env.STRIPE_SECRET_KEY;
const mppMasterSeed = process.env.MPP_MASTER_SEED;

if (!stripeSecretKey) {
  throw new Error("Missing STRIPE_SECRET_KEY");
}

const stripe = new Stripe(stripeSecretKey, {
  apiVersion: "2026-03-04.preview" as never,
});

const tempoCurrency =
  process.env.TEMPO_TEST_CURRENCY || "0x20c0000000000000000000000000000000000000";
const fundedActors = new Set<string>();
const mppSecretKey = process.env.MPP_CHALLENGE_SECRET ?? randomBytes(32).toString("base64");

type MppAuthorizeRequest = {
  actorId: string;
  merchant: string;
  amountUsd: number;
  memo?: string;
};

function recipientForRequest(request: Request): `0x${string}` {
  const authHeader = request.headers.get("authorization");
  if (authHeader && Credential.extractPaymentScheme(authHeader)) {
    const credential = Credential.fromRequest(request);
    const recipient = credential.challenge.request.recipient;
    if (typeof recipient === "string" && isHexAddress(recipient)) {
      return recipient;
    }
    throw new Error("Invalid MPP recipient address");
  }
  const merchant = merchantFromRequest(request);
  return privateKeyToAccount(deriveMppPrivateKey("mpp-merchant", merchant, mppMasterSeed)).address;
}

async function ensureActorFunded(actorId: string) {
  const privateKey = deriveMppPrivateKey("mpp-actor", actorId, mppMasterSeed);
  const account = privateKeyToAccount(privateKey);
  if (fundedActors.has(account.address.toLowerCase())) {
    return account;
  }
  const client = createClient({
    chain: tempoModerato,
    transport: http(tempoModerato.rpcUrls.default.http[0]),
  });
  await Actions.faucet.fundSync(client, { account });
  fundedActors.add(account.address.toLowerCase());
  return account;
}

app.get("/health", (c) =>
  c.json({
    status: "ok",
    service: "meridian-stripe",
    hasStripe: Boolean(stripe),
    supportsEngineRuntime: Boolean(mppMasterSeed),
    runtimeReadyReason: mppMasterSeed
      ? "MPP challenge generation and official mppx client payment flow are enabled with deterministic actor and merchant accounts"
      : "MPP challenge generation is live, but MPP_MASTER_SEED is not configured for runtime payer execution",
    timestamp: new Date().toISOString(),
  }),
);

app.post("/mpp/authorize", async (c) => {
  const body = (await c.req.json()) as Partial<MppAuthorizeRequest>;
  if (!body.actorId || !body.merchant || typeof body.amountUsd !== "number") {
    return c.json({ error: "actorId, merchant, and amountUsd are required" }, 400);
  }
  return c.json({
    ok: true,
    actorId: body.actorId,
    merchant: body.merchant,
    amountUsd: body.amountUsd,
    memo: body.memo ?? `meridian-mpp:${body.actorId}:${body.merchant}`,
  });
});

app.get("/mpp/paid", async (c, next) => {
  const payToAddress = recipientForRequest(c.req.raw);
  const amountUsd = amountUsdFromRequest(c.req.raw);
  const server = ServerMppx.create({
    methods: [
      tempo.charge({
        amount: amountUsd,
        currency: tempoCurrency as `0x${string}`,
        decimals: 6,
        recipient: payToAddress,
        testnet: true,
      }),
    ],
    secretKey: mppSecretKey,
  });
  const result = await server.charge({})(c.req.raw);
  if (result.status === 402) {
    return result.challenge;
  }
  return result.withReceipt(
    Response.json({
      ok: true,
      message: "MPP payment accepted",
      recipient: payToAddress,
      merchant: merchantFromRequest(c.req.raw),
      amountUsd: Number(amountUsd),
    }),
  );
});

app.post("/mpp/execute", async (c) => {
  try {
    const { actorId, merchant, amountUsd } = validateMppExecuteRequest(
      (await c.req.json()) as Partial<MppExecuteRequest>,
    );

    const account = await ensureActorFunded(actorId);
    const client = createClient({
      chain: tempoModerato,
      transport: http(tempoModerato.rpcUrls.default.http[0]),
    });
    const payer = ClientMppx.create({
      methods: [
        tempoClient({
          account,
          getClient: () => client,
        }),
      ],
      polyfill: false,
    });

    const response = await payer.fetch(
      `http://localhost:${port}/mpp/paid?merchant=${encodeURIComponent(merchant)}&amountUsd=${encodeURIComponent(amountUsd.toFixed(2))}`,
    );
    if (!response.ok) {
      const text = await response.text();
      return c.json({ error: `MPP execute failed: ${response.status} ${text}` }, 502);
    }

    const receipt = Receipt.fromResponse(response);
    const payload = await response.json();
    return c.json({
      ok: true,
      actorId,
      merchant,
      amountUsd,
      receipt,
      paymentId: receipt.reference,
      response: payload,
    });
  } catch (error) {
    if (
      error instanceof Error &&
      error.message === "actorId, merchant, and amountUsd are required"
    ) {
      return c.json({ error: error.message }, 400);
    }
    return c.json(
      {
        error: error instanceof Error ? error.message : String(error),
      },
      500,
    );
  }
});

serve(
  {
    fetch: app.fetch,
    port,
  },
  (info) => {
    console.log(`meridian-stripe listening on http://localhost:${info.port}`);
  },
);
