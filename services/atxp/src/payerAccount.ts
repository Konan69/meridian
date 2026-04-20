import { ATXPAccount, type Account } from "@atxp/common";
import { BaseSepoliaAccount } from "./baseSepoliaAccount.js";
import { CdpBaseSepoliaAccount } from "./cdpBaseSepoliaAccount.js";
import { PolygonAmoyAccount } from "./polygonAmoyAccount.js";

export type PayerMode = "atxp" | "base" | "polygon" | "cdp-base";

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export function getPayerModeFromEnv(): PayerMode {
  const mode = (process.env.ATXP_PAYER_MODE ?? "atxp").toLowerCase();
  if (mode === "atxp" || mode === "base" || mode === "polygon" || mode === "cdp-base") {
    return mode;
  }
  throw new Error(
    `Unsupported ATXP_PAYER_MODE: ${mode}. Expected one of: atxp, base, polygon, cdp-base`,
  );
}

function buildCdpAccountName(actorId?: string): string {
  const baseName = process.env.ATXP_CDP_ACCOUNT_NAME ?? "meridian-atxp-payer";
  if (!actorId) {
    const suffix =
      process.env.ATXP_CDP_ACCOUNT_UNIQUE === "false"
        ? ""
        : `-${Date.now().toString(36)}`;
    return `${baseName}${suffix}`.slice(0, 36);
  }

  const normalizedActorId = actorId
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const suffix = normalizedActorId || "actor";
  return `${baseName}-${suffix}`.slice(0, 36);
}

export function createPayerAccountFromEnvForActor(actorId?: string): Account {
  const mode = getPayerModeFromEnv();

  switch (mode) {
    case "atxp":
      return new ATXPAccount(requireEnv("ATXP_PAYER_CONNECTION_STRING"));
    case "base":
      return new BaseSepoliaAccount(
        requireEnv("ATXP_BASE_RPC_URL"),
        requireEnv("ATXP_BASE_PRIVATE_KEY"),
      );
    case "polygon":
      return new PolygonAmoyAccount(
        requireEnv("ATXP_POLYGON_RPC_URL"),
        requireEnv("ATXP_POLYGON_PRIVATE_KEY"),
        process.env.ATXP_POLYGON_CHAIN_ID
          ? Number.parseInt(process.env.ATXP_POLYGON_CHAIN_ID, 10)
          : 80002,
      );
    case "cdp-base":
      return new CdpBaseSepoliaAccount(
        requireEnv("CDP_SERVICE_URL"),
        buildCdpAccountName(actorId),
      );
  }
}

export function createPayerAccountFromEnv(): Account {
  return createPayerAccountFromEnvForActor();
}
