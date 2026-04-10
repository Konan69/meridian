import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";
import { ATXPAccount, getErrorRecoveryHint } from "@atxp/common";
import { BigNumber } from "bignumber.js";
import { createPayerAccountFromEnvForActor, getPayerModeFromEnv } from "./payerAccount.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
dotenv.config({ path: path.resolve(__dirname, "../../.env") });
dotenv.config({ path: path.resolve(__dirname, "../../../.env"), override: false });

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function parseAtxpConnectionString(connectionString: string): {
  accountId: string;
  token: string;
} {
  const url = new URL(connectionString);
  const token = url.searchParams.get("connection_token");
  const accountId = url.searchParams.get("account_id");
  if (!token || !accountId) {
    throw new Error("ATXP connection string must include connection_token and account_id");
  }
  return { token, accountId };
}

function safeCli(args: string[], env: NodeJS.ProcessEnv): string | null {
  try {
    return execFileSync("npx", ["atxp", ...args], {
      env,
      cwd: process.cwd(),
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch (error) {
    return String((error as Error)?.message || error);
  }
}

function recoveryFromMessage(message: string): { title: string; actions: string[] } | null {
  if (message.includes("DESTINATION_NOT_ALLOWED") || message.includes("IOU conversion is not allowed")) {
    return {
      title: "Destination Conversion Blocked",
      actions: [
        "Fund the payer account with real USDC on a supported network, not mostly IOU.",
        "Run `npx atxp fund --amount 10` and send USDC to one of the returned addresses.",
        "Prefer Base or Tempo USDC for the current direct-settle path.",
      ],
    };
  }

  if (message.toLowerCase().includes("insufficient")) {
    return {
      title: "Insufficient Funds",
      actions: [
        "Fund the payer account before retrying.",
        "For ATXP payer mode, use `npx atxp fund --amount 10`.",
        "For onchain payer modes, fund the account on the underlying chain and asset.",
      ],
    };
  }

  return null;
}

async function main() {
  const payerMode = getPayerModeFromEnv();
  const payeeConnectionString = requireEnv("ATXP_CONNECTION_STRING");
  const payee = new ATXPAccount(payeeConnectionString);
  const payeeProfile = await payee.getProfile().catch((error) => ({ error: String(error) }));
  const payeeSources = await payee.getSources().catch((error) => ({ error: String(error) }));
  const payeeAccountId = parseAtxpConnectionString(payeeConnectionString).accountId;

  const payer = createPayerAccountFromEnvForActor("atxp_recover_probe");
  const payerAccountId = await payer.getAccountId().catch((error) => `error:${String(error)}`);
  const payerSources = await payer.getSources().catch((error) => ({ error: String(error) }));

  const cliEnv = {
    ...process.env,
    ATXP_CONNECTION: process.env.ATXP_PAYER_CONNECTION_STRING ?? process.env.ATXP_CONNECTION_STRING,
  };
  const balance = payerMode === "atxp" ? safeCli(["balance"], cliEnv) : null;
  const funding = payerMode === "atxp" ? safeCli(["fund", "--amount", "10"], cliEnv) : null;

  const authorizeDestination =
    payerMode === "atxp" ? payeeAccountId : Array.isArray(payeeSources) && payeeSources.length > 0
      ? payeeSources.find((source: { chain?: string }) => source.chain === "base")?.address ?? payeeSources[0].address
      : null;

  const probeAmounts = [0.01, 5.0];
  const probes: Array<Record<string, unknown>> = [];

  for (const amount of probeAmounts) {
    if (!authorizeDestination) {
      probes.push({
        amountUsd: amount,
        ok: false,
        error: "No usable payee destination found",
      });
      continue;
    }

    try {
      const result = await payer.authorize({
        protocols: ["atxp"],
        amount: new BigNumber(amount),
        destination: authorizeDestination,
        memo: `atxp-recover:${amount}`,
      });

      let directTransfer: Record<string, unknown> | null = null;
      try {
        const response = await fetch("http://localhost:3010/health");
        if (response.ok) {
          const health = (await response.json()) as { supportsDirectSettle?: boolean };
          if (health.supportsDirectSettle) {
            const settle = await fetch("http://localhost:3010/atxp/direct-transfer", {
              method: "POST",
              headers: {
                "content-type": "application/json",
                "x-atxp-payment": result.credential,
              },
              body: JSON.stringify({
                merchant: "atxp-recover-merchant",
                amountUsd: amount,
                memo: `atxp-recover:${amount}`,
              }),
            });
            directTransfer = {
              status: settle.status,
              body: await settle.text(),
            };
          }
        }
      } catch (error) {
        directTransfer = { error: String(error) };
      }

      probes.push({
        amountUsd: amount,
        ok: true,
        protocol: result.protocol,
        directTransfer,
      });
    } catch (error) {
      const message = String(error);
      const recovery = recoveryFromMessage(message);
      const generic = getErrorRecoveryHint(error as Error);
      probes.push({
        amountUsd: amount,
        ok: false,
        error: message,
        recovery: recovery ?? generic,
      });
    }
  }

  console.log(
    JSON.stringify(
      {
        payerMode,
        payerAccountId,
        payerSources,
        payeeProfile,
        payeeSources,
        payeeAccountId,
        cliBalance: balance,
        cliFundingOptions: funding,
        probes,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(String((error as Error)?.stack ?? error));
  process.exit(1);
});
