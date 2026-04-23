import { isHexAddress } from "./treasury.js";

export type CdpNetwork = "base-sepolia" | "base";

export type SendTransactionOptions = {
  address: `0x${string}`;
  network: CdpNetwork;
  transaction: {
    to: `0x${string}`;
    data?: `0x${string}`;
    value: bigint;
    gas?: bigint;
    maxFeePerGas?: bigint;
    maxPriorityFeePerGas?: bigint;
    nonce?: number;
  };
};

type JsonRecord = Record<string, unknown>;

export class SendTransactionRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SendTransactionRequestError";
  }
}

function asRecord(value: unknown, name: string): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new SendTransactionRequestError(`${name} must be an object`);
  }
  return value as JsonRecord;
}

function requiredAddress(value: unknown, name: string): `0x${string}` {
  const address = typeof value === "string" ? value.trim() : "";
  if (!isHexAddress(address)) {
    throw new SendTransactionRequestError(`${name} must be an EVM address`);
  }
  return address;
}

function normalizeNetwork(value: unknown): CdpNetwork {
  if (value === "base-sepolia" || value === "base") {
    return value;
  }
  throw new SendTransactionRequestError("network must be base-sepolia or base");
}

function unsignedBigInt(value: unknown, name: string): bigint {
  if (typeof value === "bigint") {
    if (value < 0n) {
      throw new SendTransactionRequestError(`${name} must be a non-negative integer`);
    }
    return value;
  }

  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || value < 0) {
      throw new SendTransactionRequestError(`${name} must be a non-negative integer`);
    }
    return BigInt(value);
  }

  if (typeof value === "string") {
    const normalized = value.trim();
    if (!/^\d+$/.test(normalized)) {
      throw new SendTransactionRequestError(`${name} must be a non-negative integer string`);
    }
    return BigInt(normalized);
  }

  throw new SendTransactionRequestError(`${name} must be a non-negative integer string`);
}

function optionalUnsignedBigInt(value: unknown, name: string): bigint | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  return unsignedBigInt(value, name);
}

function optionalHexData(value: unknown): `0x${string}` | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value !== "string" || !/^0x(?:[a-fA-F0-9]{2})*$/.test(value.trim())) {
    throw new SendTransactionRequestError("transaction.data must be 0x-prefixed hex bytes");
  }
  return value.trim() as `0x${string}`;
}

function optionalNonce(value: unknown): number | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  const nonce = unsignedBigInt(value, "transaction.nonce");
  if (nonce > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new SendTransactionRequestError("transaction.nonce must be a safe integer");
  }
  return Number(nonce);
}

export function normalizeSendTransactionRequest(body: unknown): SendTransactionOptions {
  const record = asRecord(body, "request body");
  const transaction = asRecord(record.transaction, "transaction");

  return {
    address: requiredAddress(record.address, "address"),
    network: normalizeNetwork(record.network),
    transaction: {
      to: requiredAddress(transaction.to, "transaction.to"),
      data: optionalHexData(transaction.data),
      value: unsignedBigInt(transaction.value ?? "0", "transaction.value"),
      gas: optionalUnsignedBigInt(transaction.gas, "transaction.gas"),
      maxFeePerGas: optionalUnsignedBigInt(
        transaction.maxFeePerGas,
        "transaction.maxFeePerGas",
      ),
      maxPriorityFeePerGas: optionalUnsignedBigInt(
        transaction.maxPriorityFeePerGas,
        "transaction.maxPriorityFeePerGas",
      ),
      nonce: optionalNonce(transaction.nonce),
    },
  };
}
