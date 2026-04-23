import { formatEther, formatUnits, getAddress, http, parseAbi } from "viem";
import { createPublicClient } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { baseSepolia, polygon, polygonAmoy } from "viem/chains";
import { USDC_CONTRACT_ADDRESS_BASE_SEPOLIA } from "@atxp/base";
import { getPolygonUSDCAddress } from "@atxp/client";
import type { PayerMode } from "./payerAccount.js";

const ERC20_BALANCE_OF_ABI = parseAbi(["function balanceOf(address) view returns (uint256)"]);
const DEFAULT_TRANSFER_GAS_UNITS = 35_000n;
const DEFAULT_MIN_ESTIMATED_TRANSFERS = 3;
const DEFAULT_MIN_USDC_UNITS = 10_000n;

export type RuntimeFundingStatus = {
  payerMode: PayerMode;
  supportsDirectSettle: boolean;
  reason: string;
  accountAddress?: string;
  network?: string;
  nativeSymbol?: string;
  nativeBalance?: string;
  usdcBalance?: string;
  gasPriceGwei?: string;
  estimatedTransferGasUnits?: number;
  estimatedNativeCost?: string;
  estimatedTransfersRemaining?: number;
  minEstimatedTransfersRequired?: number;
  minUsdcRequired?: string;
  recoveryActions: string[];
};

type ChainFundingConfig = {
  network: string;
  nativeSymbol: string;
  rpcUrl: string;
  privateKey: string;
  usdcAddress: `0x${string}`;
  chain: typeof polygon | typeof polygonAmoy | typeof baseSepolia;
};

type CdpAccountResponse = {
  address: `0x${string}`;
  name: string;
};

type CdpBalancesResponse = {
  balances: Array<{
    contractAddress: string;
    amount: string;
    symbol?: string | null;
    name?: string | null;
    decimals?: number;
  }>;
  error?: string;
};

function requiredEnvPresent(name: string): boolean {
  const value = process.env[name];
  return typeof value === "string" && value.trim().length > 0;
}

function envOrThrow(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function envBigInt(name: string, fallback: bigint): bigint {
  const value = process.env[name];
  if (!value) {
    return fallback;
  }
  try {
    return BigInt(value);
  } catch {
    return fallback;
  }
}

function envNumber(name: string, fallback: number): number {
  const value = process.env[name];
  if (!value) {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function baseSepoliaRpcUrl(): string {
  return process.env.ATXP_BASE_RPC_URL ?? envOrThrow("X402_RPC_URL");
}

function cdpFundingProbeAccountName(): string {
  const explicit = process.env.ATXP_FUNDING_PROBE_ACCOUNT_NAME?.trim();
  if (explicit) {
    return explicit;
  }
  const baseName = process.env.ATXP_CDP_ACCOUNT_NAME ?? "meridian-atxp-payer";
  if (process.env.ATXP_CDP_ACCOUNT_UNIQUE === "false") {
    return baseName.slice(0, 36);
  }
  return `${baseName}-funding-probe`.slice(0, 36);
}

function staticRuntimeStatus(payerMode: PayerMode): RuntimeFundingStatus {
  switch (payerMode) {
    case "atxp":
      return requiredEnvPresent("ATXP_PAYER_CONNECTION_STRING")
        ? {
            payerMode,
            supportsDirectSettle: true,
            reason:
              "ATXP payer mode supports Meridian's direct verify/settle runtime path",
            recoveryActions: [],
          }
        : {
            payerMode,
            supportsDirectSettle: false,
            reason: "ATXP payer mode selected but ATXP_PAYER_CONNECTION_STRING is missing",
            recoveryActions: ["Set ATXP_PAYER_CONNECTION_STRING to a funded ATXP payer account."],
          };
    case "polygon":
      return requiredEnvPresent("ATXP_POLYGON_RPC_URL") &&
        requiredEnvPresent("ATXP_POLYGON_PRIVATE_KEY")
        ? {
            payerMode,
            supportsDirectSettle: true,
            reason:
              "Polygon payer mode uses Meridian's raw onchain verification path for direct settle",
            recoveryActions: [],
          }
        : {
            payerMode,
            supportsDirectSettle: false,
            reason:
              "Polygon payer mode selected but ATXP_POLYGON_RPC_URL or ATXP_POLYGON_PRIVATE_KEY is missing",
            recoveryActions: [
              "Set ATXP_POLYGON_RPC_URL and ATXP_POLYGON_PRIVATE_KEY for the Polygon payer wallet.",
            ],
          };
    case "base":
      return requiredEnvPresent("ATXP_BASE_RPC_URL") &&
        requiredEnvPresent("ATXP_BASE_PRIVATE_KEY")
        ? {
            payerMode,
            supportsDirectSettle: true,
            reason:
              "Base payer mode uses Meridian's raw onchain verification path for direct settle",
            recoveryActions: [],
          }
        : {
            payerMode,
            supportsDirectSettle: false,
            reason:
              "Base payer mode selected but ATXP_BASE_RPC_URL or ATXP_BASE_PRIVATE_KEY is missing",
            recoveryActions: [
              "Set ATXP_BASE_RPC_URL and ATXP_BASE_PRIVATE_KEY for the Base payer wallet.",
            ],
          };
    case "cdp-base":
      return requiredEnvPresent("CDP_SERVICE_URL") &&
        (requiredEnvPresent("ATXP_BASE_RPC_URL") || requiredEnvPresent("X402_RPC_URL"))
        ? {
            payerMode,
            supportsDirectSettle: true,
            reason:
              "cdp-base uses Meridian's CDP wallet plus Base Sepolia raw verification path",
            recoveryActions: [],
          }
        : {
            payerMode,
            supportsDirectSettle: false,
            reason:
              "cdp-base payer mode selected but CDP_SERVICE_URL or a Base Sepolia RPC URL is missing",
            recoveryActions: [
              "Set CDP_SERVICE_URL and either ATXP_BASE_RPC_URL or X402_RPC_URL.",
            ],
          };
  }
}

function chainConfigForPayerMode(payerMode: PayerMode): ChainFundingConfig | null {
  switch (payerMode) {
    case "polygon": {
      const chainId = Number.parseInt(process.env.ATXP_POLYGON_CHAIN_ID ?? "80002", 10);
      return {
        network: chainId === 137 ? "polygon" : "polygon_amoy",
        nativeSymbol: "POL",
        rpcUrl: envOrThrow("ATXP_POLYGON_RPC_URL"),
        privateKey: envOrThrow("ATXP_POLYGON_PRIVATE_KEY"),
        usdcAddress: getAddress(getPolygonUSDCAddress(chainId)),
        chain: chainId === 137 ? polygon : polygonAmoy,
      };
    }
    case "base":
      return {
        network: "base_sepolia",
        nativeSymbol: "ETH",
        rpcUrl: envOrThrow("ATXP_BASE_RPC_URL"),
        privateKey: envOrThrow("ATXP_BASE_PRIVATE_KEY"),
        usdcAddress: getAddress(USDC_CONTRACT_ADDRESS_BASE_SEPOLIA),
        chain: baseSepolia,
      };
    default:
      return null;
  }
}

function recoveryActionsForChainFunding(args: {
  network: string;
  lowNative: boolean;
  lowUsdc: boolean;
}): string[] {
  const actions: string[] = [];

  if (args.lowNative) {
    if (args.network === "polygon_amoy") {
      actions.push(
        "Top up the Polygon Amoy payer wallet with POL from a faucet or another Amoy wallet.",
      );
    } else if (args.network === "base_sepolia") {
      actions.push(
        "Top up the Base Sepolia payer wallet with ETH from a faucet or another Base Sepolia wallet.",
      );
    } else {
      actions.push(`Top up the ${args.network} payer wallet with native gas.`);
    }
  }

  if (args.lowUsdc) {
    actions.push(`Top up the ${args.network} payer wallet with test USDC.`);
  }

  if (actions.length === 0) {
    actions.push("Funding looks healthy.");
  }

  return actions;
}

function recoveryActionsForCdpFunding(args: {
  serviceUrl: string;
  lowNative: boolean;
  lowUsdc: boolean;
}): string[] {
  const actions: string[] = [];

  if (args.lowNative) {
    actions.push(
      `Request Base Sepolia ETH via ${args.serviceUrl}/evm/request-faucet or fund the CDP probe wallet directly.`,
    );
  }

  if (args.lowUsdc) {
    actions.push(
      `Request Base Sepolia USDC via ${args.serviceUrl}/evm/request-faucet or rotate to a better-funded CDP account.`,
    );
  }

  if (args.lowNative || args.lowUsdc) {
    actions.push(
      "If the CDP faucet reports a project limit, wait for the faucet window to reset or switch to a different funded payer.",
    );
  } else {
    actions.push("Funding looks healthy.");
  }

  return actions;
}

async function chainFundingStatus(payerMode: PayerMode): Promise<RuntimeFundingStatus> {
  const config = chainConfigForPayerMode(payerMode);
  if (!config) {
    return staticRuntimeStatus(payerMode);
  }

  const account = privateKeyToAccount(config.privateKey as `0x${string}`);
  const publicClient = createPublicClient({
    chain: config.chain,
    transport: http(config.rpcUrl),
  });

  const estimatedTransferGasUnits = envBigInt(
    "ATXP_ESTIMATED_ERC20_TRANSFER_GAS",
    DEFAULT_TRANSFER_GAS_UNITS,
  );
  const minEstimatedTransfersRequired = envNumber(
    "ATXP_MIN_ESTIMATED_TRANSFERS",
    DEFAULT_MIN_ESTIMATED_TRANSFERS,
  );
  const minUsdcUnits = envBigInt("ATXP_MIN_USDC_UNITS", DEFAULT_MIN_USDC_UNITS);

  const [nativeBalance, gasPrice, usdcBalance] = await Promise.all([
    publicClient.getBalance({ address: account.address }),
    publicClient.getGasPrice(),
    publicClient.readContract({
      address: config.usdcAddress,
      abi: ERC20_BALANCE_OF_ABI,
      functionName: "balanceOf",
      args: [account.address],
    }),
  ]);

  const estimatedNativeCost =
    estimatedTransferGasUnits > 0n ? estimatedTransferGasUnits * gasPrice : 0n;
  const estimatedTransfersRemaining =
    estimatedNativeCost > 0n ? Number(nativeBalance / estimatedNativeCost) : 0;
  const lowNative = estimatedTransfersRemaining < minEstimatedTransfersRequired;
  const lowUsdc = usdcBalance < minUsdcUnits;

  return {
    payerMode,
    supportsDirectSettle: !(lowNative || lowUsdc),
    reason:
      lowNative || lowUsdc
        ? `${config.network} payer underfunded: ~${estimatedTransfersRemaining} transfer(s) of gas runway and ${formatUnits(usdcBalance, 6)} USDC available`
        : `${config.network} payer funded with ~${estimatedTransfersRemaining} transfer(s) of gas runway and ${formatUnits(usdcBalance, 6)} USDC`,
    accountAddress: account.address,
    network: config.network,
    nativeSymbol: config.nativeSymbol,
    nativeBalance: formatEther(nativeBalance),
    usdcBalance: formatUnits(usdcBalance, 6),
    gasPriceGwei: (Number(gasPrice) / 1e9).toFixed(4),
    estimatedTransferGasUnits: Number(estimatedTransferGasUnits),
    estimatedNativeCost: formatEther(estimatedNativeCost),
    estimatedTransfersRemaining,
    minEstimatedTransfersRequired,
    minUsdcRequired: formatUnits(minUsdcUnits, 6),
    recoveryActions: recoveryActionsForChainFunding({
      network: config.network,
      lowNative,
      lowUsdc,
    }),
  };
}

async function cdpBaseFundingStatus(): Promise<RuntimeFundingStatus> {
  const serviceUrl = envOrThrow("CDP_SERVICE_URL").replace(/\/$/, "");
  const probeAccountName = cdpFundingProbeAccountName();
  const accountResponse = await fetch(`${serviceUrl}/evm/get-or-create-account`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify({ name: probeAccountName }),
  });
  const accountBody = (await accountResponse.json()) as Partial<CdpAccountResponse> & {
    error?: string;
  };
  if (!accountResponse.ok || !accountBody.address) {
    throw new Error(accountBody.error ?? "CDP funding target account lookup failed");
  }

  const balancesResponse = await fetch(
    `${serviceUrl}/evm/token-balances/${accountBody.address}`,
  );
  const balancesBody = (await balancesResponse.json()) as CdpBalancesResponse;
  if (!balancesResponse.ok || !Array.isArray(balancesBody.balances)) {
    throw new Error(balancesBody.error ?? "CDP funding target balance lookup failed");
  }

  const publicClient = createPublicClient({
    chain: baseSepolia,
    transport: http(baseSepoliaRpcUrl()),
  });
  const estimatedTransferGasUnits = envBigInt(
    "ATXP_ESTIMATED_ERC20_TRANSFER_GAS",
    DEFAULT_TRANSFER_GAS_UNITS,
  );
  const minEstimatedTransfersRequired = envNumber(
    "ATXP_MIN_ESTIMATED_TRANSFERS",
    DEFAULT_MIN_ESTIMATED_TRANSFERS,
  );
  const minUsdcUnits = envBigInt("ATXP_MIN_USDC_UNITS", DEFAULT_MIN_USDC_UNITS);
  const [nativeBalance, gasPrice] = await Promise.all([
    publicClient.getBalance({ address: accountBody.address }),
    publicClient.getGasPrice(),
  ]);

  const usdcBalance = balancesBody.balances
    .filter(
      (balance) =>
        balance.contractAddress.toLowerCase() ===
        USDC_CONTRACT_ADDRESS_BASE_SEPOLIA.toLowerCase(),
    )
    .reduce((sum, balance) => sum + BigInt(balance.amount), 0n);

  const estimatedNativeCost =
    estimatedTransferGasUnits > 0n ? estimatedTransferGasUnits * gasPrice : 0n;
  const estimatedTransfersRemaining =
    estimatedNativeCost > 0n ? Number(nativeBalance / estimatedNativeCost) : 0;
  const lowNative = estimatedTransfersRemaining < minEstimatedTransfersRequired;
  const lowUsdc = usdcBalance < minUsdcUnits;

  return {
    payerMode: "cdp-base",
    supportsDirectSettle: !(lowNative || lowUsdc),
    reason:
      lowNative || lowUsdc
        ? `cdp-base payer underfunded: ~${estimatedTransfersRemaining} transfer(s) of gas runway and ${formatUnits(usdcBalance, 6)} USDC available`
        : `cdp-base payer funded with ~${estimatedTransfersRemaining} transfer(s) of gas runway and ${formatUnits(usdcBalance, 6)} USDC`,
    accountAddress: accountBody.address,
    network: "base_sepolia",
    nativeSymbol: "ETH",
    nativeBalance: formatEther(nativeBalance),
    usdcBalance: formatUnits(usdcBalance, 6),
    gasPriceGwei: (Number(gasPrice) / 1e9).toFixed(4),
    estimatedTransferGasUnits: Number(estimatedTransferGasUnits),
    estimatedNativeCost: formatEther(estimatedNativeCost),
    estimatedTransfersRemaining,
    minEstimatedTransfersRequired,
    minUsdcRequired: formatUnits(minUsdcUnits, 6),
    recoveryActions: recoveryActionsForCdpFunding({
      serviceUrl,
      lowNative,
      lowUsdc,
    }),
  };
}

export async function runtimeStatusForPayerMode(
  payerMode: PayerMode,
): Promise<RuntimeFundingStatus> {
  const baseStatus = staticRuntimeStatus(payerMode);
  if (!baseStatus.supportsDirectSettle) {
    return baseStatus;
  }
  if (payerMode === "polygon" || payerMode === "base") {
    try {
      return await chainFundingStatus(payerMode);
    } catch (error) {
      return {
        payerMode,
        supportsDirectSettle: false,
        reason: `Failed to inspect payer funding: ${error instanceof Error ? error.message : String(error)}`,
        recoveryActions: ["Verify the payer RPC URL and wallet configuration."],
      };
    }
  }
  if (payerMode === "cdp-base") {
    try {
      return await cdpBaseFundingStatus();
    } catch (error) {
      return {
        payerMode,
        supportsDirectSettle: false,
        reason: `Failed to inspect cdp-base funding: ${error instanceof Error ? error.message : String(error)}`,
        recoveryActions: ["Verify CDP_SERVICE_URL and Base Sepolia RPC configuration."],
      };
    }
  }
  return baseStatus;
}
