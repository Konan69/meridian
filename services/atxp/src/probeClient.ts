import "dotenv/config";
import { atxpClient } from "@atxp/client";
import { ATXPAccount } from "@atxp/common";
import { BigNumber } from "bignumber.js";
import { createPayerAccountFromEnv, getPayerModeFromEnv } from "./payerAccount.js";

const mcpServer = process.env.ATXP_MCP_SERVER ?? "http://localhost:3010/mcp";
const merchant = process.env.ATXP_TEST_MERCHANT ?? "demo-merchant";
const amountUsd = Number(process.env.ATXP_TEST_AMOUNT_USD ?? "0.25");

async function main() {
  if (process.env.ATXP_PROBE_MODE === "direct-atxp") {
    await probeDirectAtxpCredential();
    return;
  }

  const payerMode = getPayerModeFromEnv();
  const account = createPayerAccountFromEnv();

  const client = await atxpClient({
    mcpServer,
    account,
    approvePayment: async () => true,
    onPayment: async (data) => {
      console.log("payment", JSON.stringify(data));
    },
    onPaymentFailure: async (context) => {
      const message =
        context.error instanceof Error ? context.error.message : String(context.error);
      console.log("payment_failure", message);
    },
    onAuthorizeFailure: async ({ error }) => {
      console.log("auth_failure", error instanceof Error ? error.message : String(error));
    },
  });

  const result = await client.callTool({
    name: "stablecoin_transfer",
    arguments: {
      merchant,
      amountUsd,
    },
  });

  console.log(
    JSON.stringify({
      payerMode,
      merchant,
      amountUsd,
      result,
    }),
  );
}

main().catch((error) => {
  console.error(String((error as Error)?.stack ?? error));
  process.exit(1);
});

export async function probeDirectAtxpCredential() {
  const payerConnectionString = process.env.ATXP_PAYER_CONNECTION_STRING;
  if (!payerConnectionString) {
    throw new Error("ATXP_PAYER_CONNECTION_STRING is required for direct ATXP credential probing");
  }

  const payer = new ATXPAccount(payerConnectionString);
  const credential = await payer.authorize({
    protocols: ["atxp"],
    amount: new BigNumber(amountUsd),
    destination: "0xA97a86b47592e2C2d84cd6b2899c05753eCea50b",
    memo: "meridian-direct-atxp",
  });

  const response = await fetch("http://localhost:3010/atxp/direct-transfer", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-atxp-payment": credential.credential,
    },
    body: JSON.stringify({
      merchant,
      amountUsd,
      memo: "meridian-direct-atxp",
    }),
  });
  const body = await response.text();
  console.log(
    JSON.stringify({
      directAtxp: true,
      status: response.status,
      body,
    }),
  );
}
