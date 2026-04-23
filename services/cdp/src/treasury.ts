import type { SendTransactionOptions } from "./sendTransaction.js";

export const BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
const ERC20_TRANSFER_SELECTOR = "a9059cbb";

export type TreasuryTransferRequest = {
  fromAddress?: string;
  toAddress?: string;
  amount?: string | number;
  amountUnits?: string | number;
  network?: string;
};

export type NativeTransferRequest = TreasuryTransferRequest & {
  amountWei?: string | number;
};

export type TreasuryTransferKind = "native" | "usdc";

export type NormalizedTreasuryTransfer = {
  kind: TreasuryTransferKind;
  token: "ETH" | "USDC";
  network: "base-sepolia";
  fromAddress: `0x${string}`;
  toAddress: `0x${string}`;
  amountUnits: bigint;
  txOptions: SendTransactionOptions;
};

export class TreasuryTransferRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TreasuryTransferRequestError";
  }
}

function hasOwn(body: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(body, key);
}

export function isHexAddress(value: string): value is `0x${string}` {
  return /^0x[a-fA-F0-9]{40}$/.test(value);
}

export function parseDecimalUnits(value: string | number, decimals: number): bigint {
  const normalized = String(value).trim();
  if (!/^\d+(\.\d+)?$/.test(normalized)) {
    throw new TreasuryTransferRequestError("amount must be a non-negative decimal string");
  }

  const [whole, fraction = ""] = normalized.split(".");
  if (fraction.length > decimals) {
    throw new TreasuryTransferRequestError(`amount supports at most ${decimals} decimal places`);
  }

  const scale = 10n ** BigInt(decimals);
  return BigInt(whole || "0") * scale + BigInt(fraction.padEnd(decimals, "0") || "0");
}

export function amountUnitsFromRequest(
  body: TreasuryTransferRequest,
  decimals: number,
): bigint {
  if (hasOwn(body, "amountUnits") && hasOwn(body, "amount")) {
    throw new TreasuryTransferRequestError("use either amount or amountUnits, not both");
  }

  if (hasOwn(body, "amountUnits") && body.amountUnits !== undefined && body.amountUnits !== null) {
    const rawUnits = String(body.amountUnits).trim();
    if (!/^\d+$/.test(rawUnits)) {
      throw new TreasuryTransferRequestError("amountUnits must be a non-negative integer string");
    }
    return BigInt(rawUnits);
  }

  if (!hasOwn(body, "amount") || body.amount === undefined || body.amount === null) {
    throw new TreasuryTransferRequestError("amount or amountUnits is required");
  }

  return parseDecimalUnits(body.amount, decimals);
}

export function nativeValueWeiFromRequest(body: NativeTransferRequest): bigint {
  if (hasOwn(body, "amountWei") && (hasOwn(body, "amount") || hasOwn(body, "amountUnits"))) {
    throw new TreasuryTransferRequestError(
      "use either amountWei or decimal/unit amount fields, not both",
    );
  }

  if (hasOwn(body, "amountWei") && body.amountWei !== undefined && body.amountWei !== null) {
    const rawWei = String(body.amountWei).trim();
    if (!/^\d+$/.test(rawWei)) {
      throw new TreasuryTransferRequestError("amountWei must be a non-negative integer string");
    }
    return BigInt(rawWei);
  }

  return amountUnitsFromRequest(body, 18);
}

export function encodeErc20Transfer(
  toAddress: `0x${string}`,
  amountUnits: bigint,
): `0x${string}` {
  const addressArg = toAddress.slice(2).toLowerCase().padStart(64, "0");
  const amountArg = amountUnits.toString(16).padStart(64, "0");
  return `0x${ERC20_TRANSFER_SELECTOR}${addressArg}${amountArg}`;
}

function normalizeTreasuryNetwork(value: unknown, token: "native" | "USDC"): "base-sepolia" {
  if (value === undefined || value === null || value === "base-sepolia") {
    return "base-sepolia";
  }

  const label = token === "USDC" ? "USDC" : "native";
  throw new TreasuryTransferRequestError(
    `treasury ${label} transfers only support base-sepolia`,
  );
}

function asRecord(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TreasuryTransferRequestError(`${name} must be an object`);
  }
  return value as Record<string, unknown>;
}

function ownValue(record: Record<string, unknown>, key: string, name: string): unknown {
  if (!hasOwn(record, key)) {
    throw new TreasuryTransferRequestError(`${name} is required`);
  }
  return record[key];
}

function optionalOwnValue(record: Record<string, unknown>, key: string): unknown {
  return hasOwn(record, key) ? record[key] : undefined;
}

function requiredAddress(value: unknown, name: string): `0x${string}` {
  const address = typeof value === "string" ? value.trim() : "";
  if (!isHexAddress(address)) {
    throw new TreasuryTransferRequestError(`${name} must be an EVM address`);
  }
  return address;
}

function normalizeTreasuryTransferBase(body: unknown, token: "native" | "USDC") {
  const record = asRecord(body, "request body") as TreasuryTransferRequest;
  return {
    record,
    fromAddress: requiredAddress(ownValue(record, "fromAddress", "fromAddress"), "fromAddress"),
    toAddress: requiredAddress(ownValue(record, "toAddress", "toAddress"), "toAddress"),
    network: normalizeTreasuryNetwork(optionalOwnValue(record, "network"), token),
  };
}

export function normalizeUsdcTreasuryTransferRequest(body: unknown): NormalizedTreasuryTransfer {
  const base = normalizeTreasuryTransferBase(body, "USDC");
  const amountUnits = amountUnitsFromRequest(base.record, 6);
  if (amountUnits <= 0n) {
    throw new TreasuryTransferRequestError("amount must be greater than zero");
  }

  return {
    kind: "usdc",
    token: "USDC",
    network: base.network,
    fromAddress: base.fromAddress,
    toAddress: base.toAddress,
    amountUnits,
    txOptions: {
      address: base.fromAddress,
      network: base.network,
      transaction: {
        to: BASE_SEPOLIA_USDC,
        data: encodeErc20Transfer(base.toAddress, amountUnits),
        value: 0n,
      },
    },
  };
}

export function normalizeNativeTreasuryTransferRequest(
  body: unknown,
): NormalizedTreasuryTransfer {
  const base = normalizeTreasuryTransferBase(body, "native");
  const amountWei = nativeValueWeiFromRequest(base.record);
  if (amountWei <= 0n) {
    throw new TreasuryTransferRequestError("amount must be greater than zero");
  }

  return {
    kind: "native",
    token: "ETH",
    network: base.network,
    fromAddress: base.fromAddress,
    toAddress: base.toAddress,
    amountUnits: amountWei,
    txOptions: {
      address: base.fromAddress,
      network: base.network,
      transaction: {
        to: base.toAddress,
        value: amountWei,
      },
    },
  };
}

export function treasuryTransferResponse(
  transfer: NormalizedTreasuryTransfer,
  transaction: unknown,
): Record<string, unknown> {
  const common = {
    token: transfer.token,
    network: transfer.network,
    fromAddress: transfer.fromAddress,
    toAddress: transfer.toAddress,
    transaction,
  };

  if (transfer.kind === "usdc") {
    return {
      ...common,
      contractAddress: BASE_SEPOLIA_USDC,
      amountUnits: transfer.amountUnits.toString(),
    };
  }

  return {
    ...common,
    amountWei: transfer.amountUnits.toString(),
  };
}
