import path from "node:path";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import BigNumber from "bignumber.js";
import {
  createPublicClient,
  decodeEventLog,
  getAddress,
  http,
  isAddressEqual,
  type Address,
  type Hex,
} from "viem";
import { base, baseSepolia, polygon, polygonAmoy } from "viem/chains";
import type {
  AccountId,
  AuthorizationServerUrl,
  Logger,
  Source,
} from "@atxp/common";
import { ProtocolSettlement } from "@atxp/server";
import {
  USDC_CONTRACT_ADDRESS_BASE,
  USDC_CONTRACT_ADDRESS_BASE_SEPOLIA,
} from "@atxp/base";
import { getPolygonUSDCAddress } from "@atxp/client";
import type { PayerMode } from "./payerAccount.js";

const ERC20_TRANSFER_ABI = [
  {
    anonymous: false,
    inputs: [
      { indexed: true, name: "from", type: "address" },
      { indexed: true, name: "to", type: "address" },
      { indexed: false, name: "value", type: "uint256" },
    ],
    name: "Transfer",
    type: "event",
  },
] as const;

type DirectTransferRequest = {
  merchant: string;
  amountUsd: number;
  memo?: string;
};

type DirectTransferSuccess = {
  ok: true;
  txHash: string;
  settledAmount: string;
  verificationMode: "atxp-auth" | "raw-evm";
  alreadySettled?: boolean;
};

type AtxpCredential = {
  sourceAccountId?: string;
  sourceAccountToken?: string;
  options?: unknown[];
};

export type RawTxCredential = {
  transactionId: Hex;
  chain: "polygon" | "polygon_amoy" | "base" | "base_sepolia";
  currency: string;
};

type RawSettlementRecord = {
  txHash: string;
  chain: string;
  recipient: string;
  settledAmount: string;
  merchant: string;
  memo?: string;
  settledAt: string;
};

type EvmVerifierConfig = {
  chainName: RawTxCredential["chain"];
  chain: typeof base | typeof baseSepolia | typeof polygon | typeof polygonAmoy;
  rpcUrl: string;
  usdcAddress: Address;
};

export class DirectTransferRejectedError extends Error {
  constructor(message: string, readonly status: number = 402) {
    super(message);
    this.name = "DirectTransferRejectedError";
  }
}

class RawSettlementStore {
  private loaded = false;
  private readonly records = new Map<string, RawSettlementRecord>();
  private writeQueue: Promise<void> = Promise.resolve();

  constructor(
    private readonly filePath = path.resolve(
      process.cwd(),
      ".runtime",
      "atxp-raw-settlements.json",
    ),
  ) {}

  async get(txHash: string): Promise<RawSettlementRecord | undefined> {
    await this.load();
    return this.records.get(txHash.toLowerCase());
  }

  async put(record: RawSettlementRecord): Promise<void> {
    const key = record.txHash.toLowerCase();
    this.writeQueue = this.writeQueue.then(async () => {
      await this.load();
      this.records.set(key, record);
      await mkdir(path.dirname(this.filePath), { recursive: true });
      await writeFile(
        this.filePath,
        JSON.stringify(Object.fromEntries(this.records.entries()), null, 2),
        "utf8",
      );
    });
    await this.writeQueue;
  }

  private async load(): Promise<void> {
    if (this.loaded) {
      return;
    }
    this.loaded = true;
    try {
      const raw = await readFile(this.filePath, "utf8");
      const parsed = JSON.parse(raw) as Record<string, RawSettlementRecord>;
      for (const [txHash, record] of Object.entries(parsed)) {
        this.records.set(txHash.toLowerCase(), record);
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        throw error;
      }
    }
  }
}

const settlementStore = new RawSettlementStore();

function requiredEnvPresent(name: string): boolean {
  const value = process.env[name];
  return typeof value === "string" && value.trim().length > 0;
}

export function runtimeReadyForPayerMode(payerMode: PayerMode): {
  supportsDirectSettle: boolean;
  reason: string;
} {
  switch (payerMode) {
    case "atxp":
      return requiredEnvPresent("ATXP_PAYER_CONNECTION_STRING")
        ? {
            supportsDirectSettle: true,
            reason:
              "ATXP payer mode supports Meridian's direct verify/settle runtime path",
          }
        : {
            supportsDirectSettle: false,
            reason: "ATXP payer mode selected but ATXP_PAYER_CONNECTION_STRING is missing",
          };
    case "polygon":
      return requiredEnvPresent("ATXP_POLYGON_RPC_URL") &&
        requiredEnvPresent("ATXP_POLYGON_PRIVATE_KEY")
        ? {
            supportsDirectSettle: true,
            reason:
              "Polygon payer mode uses Meridian's raw onchain verification path for direct settle",
          }
        : {
            supportsDirectSettle: false,
            reason:
              "Polygon payer mode selected but ATXP_POLYGON_RPC_URL or ATXP_POLYGON_PRIVATE_KEY is missing",
          };
    case "base":
      return requiredEnvPresent("ATXP_BASE_RPC_URL") &&
        requiredEnvPresent("ATXP_BASE_PRIVATE_KEY")
        ? {
            supportsDirectSettle: true,
            reason:
              "Base payer mode uses Meridian's raw onchain verification path for direct settle",
          }
        : {
            supportsDirectSettle: false,
            reason:
              "Base payer mode selected but ATXP_BASE_RPC_URL or ATXP_BASE_PRIVATE_KEY is missing",
          };
    case "cdp-base":
      return requiredEnvPresent("CDP_SERVICE_URL") &&
        (requiredEnvPresent("ATXP_BASE_RPC_URL") || requiredEnvPresent("X402_RPC_URL"))
        ? {
            supportsDirectSettle: true,
            reason:
              "cdp-base uses Meridian's CDP wallet plus Base Sepolia raw verification path",
          }
        : {
            supportsDirectSettle: false,
            reason:
              "cdp-base payer mode selected but CDP_SERVICE_URL or a Base Sepolia RPC URL is missing",
          };
  }
}

export async function settleDirectTransfer(args: {
  authServer: AuthorizationServerUrl;
  logger: Logger;
  destinationAccountId: AccountId;
  payerMode: PayerMode;
  payeeSources: Source[];
  request: DirectTransferRequest;
  credential: string;
}): Promise<DirectTransferSuccess> {
  const atxpCredential = parseAtxpCredential(args.credential);
  if (atxpCredential?.sourceAccountToken) {
    return settleOfficialAtxpCredential({
      authServer: args.authServer,
      logger: args.logger,
      destinationAccountId: args.destinationAccountId,
      credential: args.credential,
      parsedCredential: atxpCredential,
    });
  }

  const rawCredential = parseRawTxCredential(args.credential);
  if (!rawCredential) {
    throw new DirectTransferRejectedError("Unsupported ATXP credential format");
  }

  return verifyAndRecordRawTransfer({
    logger: args.logger,
    payerMode: args.payerMode,
    payeeSources: args.payeeSources,
    request: args.request,
    credential: rawCredential,
  });
}

async function settleOfficialAtxpCredential(args: {
  authServer: AuthorizationServerUrl;
  logger: Logger;
  destinationAccountId: AccountId;
  credential: string;
  parsedCredential: AtxpCredential;
}): Promise<DirectTransferSuccess> {
  const settlement = new ProtocolSettlement(
    args.authServer,
    args.logger,
    fetch.bind(globalThis),
    args.destinationAccountId,
  );
  const context = {
    destinationAccountId: args.destinationAccountId,
    ...(args.parsedCredential.sourceAccountId
      ? { sourceAccountId: args.parsedCredential.sourceAccountId }
      : {}),
    ...(Array.isArray(args.parsedCredential.options)
      ? { options: args.parsedCredential.options }
      : {}),
  };
  const valid = await settlement.verify("atxp", args.credential, context);
  if (!valid.valid) {
    throw new DirectTransferRejectedError("ATXP credential verification failed");
  }

  const settled = await settlement.settle("atxp", args.credential, context);
  return {
    ok: true,
    txHash: settled.txHash ?? "atxp-already-settled",
    settledAmount: String(settled.settledAmount),
    verificationMode: "atxp-auth",
    alreadySettled: settled.txHash === null,
  };
}

async function verifyAndRecordRawTransfer(args: {
  logger: Logger;
  payerMode: PayerMode;
  payeeSources: Source[];
  request: DirectTransferRequest;
  credential: RawTxCredential;
}): Promise<DirectTransferSuccess> {
  if (args.credential.currency.toUpperCase() !== "USDC") {
    throw new DirectTransferRejectedError(
      `Unsupported raw credential currency: ${args.credential.currency}`,
    );
  }

  const verifier = evmVerifierForCredential(args.credential, args.payerMode);
  const recipient = expectedRecipientForChain(args.credential.chain, args.payeeSources);
  const expectedAmountUnits = expectedUsdcUnits(args.request.amountUsd);
  const txHash = args.credential.transactionId.toLowerCase();

  const priorSettlement = await settlementStore.get(txHash);
  if (priorSettlement) {
    if (
      priorSettlement.chain !== args.credential.chain ||
      !isAddressEqual(priorSettlement.recipient as Address, recipient) ||
      BigInt(priorSettlement.settledAmount) < expectedAmountUnits
    ) {
      throw new DirectTransferRejectedError(
        `transaction ${txHash} was already consumed for a different payment`,
        409,
      );
    }
    return {
      ok: true,
      txHash,
      settledAmount: priorSettlement.settledAmount,
      verificationMode: "raw-evm",
      alreadySettled: true,
    };
  }

  const publicClient = createPublicClient({
    chain: verifier.chain,
    transport: http(verifier.rpcUrl),
  });
  const receipt = await publicClient.waitForTransactionReceipt({
    hash: args.credential.transactionId,
    timeout: 45_000,
  });

  if (receipt.status !== "success") {
    throw new DirectTransferRejectedError(
      `transaction ${args.credential.transactionId} did not succeed on ${args.credential.chain}`,
    );
  }

  const settledAmount = receipt.logs
    .filter((log) => isAddressEqual(log.address, verifier.usdcAddress))
    .reduce((sum, log) => {
      try {
        const decoded = decodeEventLog({
          abi: ERC20_TRANSFER_ABI,
          data: log.data,
          topics: log.topics,
        });
        if (decoded.eventName !== "Transfer") {
          return sum;
        }
        const { to, value } = decoded.args as {
          from: Address;
          to: Address;
          value: bigint;
        };
        return isAddressEqual(to, recipient) ? sum + value : sum;
      } catch {
        return sum;
      }
    }, 0n);

  if (settledAmount < expectedAmountUnits) {
    throw new DirectTransferRejectedError(
      `transaction ${args.credential.transactionId} transferred ${settledAmount.toString()} units; expected at least ${expectedAmountUnits.toString()}`,
    );
  }

  await settlementStore.put({
    txHash,
    chain: args.credential.chain,
    recipient,
    settledAmount: settledAmount.toString(),
    merchant: args.request.merchant,
    memo: args.request.memo,
    settledAt: new Date().toISOString(),
  });

  args.logger.info(
    `Verified raw ${args.credential.chain} USDC transfer ${txHash} for ${settledAmount.toString()} units`,
  );

  return {
    ok: true,
    txHash,
    settledAmount: settledAmount.toString(),
    verificationMode: "raw-evm",
  };
}

function evmVerifierForCredential(
  credential: RawTxCredential,
  payerMode: PayerMode,
): EvmVerifierConfig {
  switch (credential.chain) {
    case "polygon":
      return {
        chainName: credential.chain,
        chain: polygon,
        rpcUrl: requireEnv("ATXP_POLYGON_RPC_URL"),
        usdcAddress: getAddress(getPolygonUSDCAddress(137)),
      };
    case "polygon_amoy":
      return {
        chainName: credential.chain,
        chain: polygonAmoy,
        rpcUrl: requireEnv("ATXP_POLYGON_RPC_URL"),
        usdcAddress: getAddress(getPolygonUSDCAddress(80002)),
      };
    case "base":
      if (payerMode === "cdp-base") {
        return {
          chainName: credential.chain,
          chain: baseSepolia,
          rpcUrl: requireBaseSepoliaRpcUrl(),
          usdcAddress: getAddress(USDC_CONTRACT_ADDRESS_BASE_SEPOLIA),
        };
      }
      return {
        chainName: credential.chain,
        chain: base,
        rpcUrl: requireEnv("ATXP_BASE_RPC_URL"),
        usdcAddress: getAddress(USDC_CONTRACT_ADDRESS_BASE),
      };
    case "base_sepolia":
      return {
        chainName: credential.chain,
        chain: baseSepolia,
        rpcUrl: requireEnv("ATXP_BASE_RPC_URL"),
        usdcAddress: getAddress(USDC_CONTRACT_ADDRESS_BASE_SEPOLIA),
      };
  }
}

function requireBaseSepoliaRpcUrl(): string {
  return (
    process.env.ATXP_BASE_RPC_URL ??
    process.env.X402_RPC_URL ??
    (() => {
      throw new DirectTransferRejectedError(
        "Missing Base Sepolia RPC URL for direct settle verification",
        500,
      );
    })()
  );
}

function expectedRecipientForChain(
  chain: RawTxCredential["chain"],
  payeeSources: Source[],
): Address {
  const exact = payeeSources.find((source) => source.chain === chain);
  if (exact) {
    return getAddress(exact.address as Address);
  }

  if (chain === "polygon_amoy") {
    const polygonSource = payeeSources.find((source) => source.chain === "polygon");
    if (polygonSource) {
      return getAddress(polygonSource.address as Address);
    }
  }
  if (chain === "base_sepolia") {
    const baseSource = payeeSources.find((source) => source.chain === "base");
    if (baseSource) {
      return getAddress(baseSource.address as Address);
    }
  }

  const fallback = payeeSources[0];
  if (!fallback) {
    throw new DirectTransferRejectedError("ATXP payee account has no usable destination sources");
  }
  return getAddress(fallback.address as Address);
}

export function expectedUsdcUnits(amountUsd: number): bigint {
  return BigInt(
    new BigNumber(amountUsd.toString())
      .multipliedBy(10 ** 6)
      .integerValue(BigNumber.ROUND_CEIL)
      .toFixed(0),
  );
}

export function parseAtxpCredential(credential: string): AtxpCredential | null {
  try {
    const parsed = JSON.parse(credential) as AtxpCredential;
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? parsed
      : null;
  } catch {
    return null;
  }
}

export function parseRawTxCredential(credential: string): RawTxCredential | null {
  try {
    const parsed = JSON.parse(credential) as Partial<RawTxCredential>;
    if (
      typeof parsed.transactionId === "string" &&
      /^0x[a-fA-F0-9]{64}$/.test(parsed.transactionId) &&
      typeof parsed.chain === "string" &&
      typeof parsed.currency === "string" &&
      (parsed.chain === "polygon" ||
        parsed.chain === "polygon_amoy" ||
        parsed.chain === "base" ||
        parsed.chain === "base_sepolia")
    ) {
      return {
        transactionId: parsed.transactionId as Hex,
        chain: parsed.chain,
        currency: parsed.currency,
      };
    }
    return null;
  } catch {
    return null;
  }
}

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new DirectTransferRejectedError(
      `Missing required environment variable for direct settle: ${name}`,
      500,
    );
  }
  return value;
}
