import { makeRequestValidator } from "./requestValidation.js";

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

export class SendTransactionRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SendTransactionRequestError";
  }
}

const { asRecord, ownValue, optionalOwnValue, requiredAddress } = makeRequestValidator(
  (message) => new SendTransactionRequestError(message),
);

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
  const transaction = asRecord(ownValue(record, "transaction", "transaction"), "transaction");

  return {
    address: requiredAddress(ownValue(record, "address", "address"), "address"),
    network: normalizeNetwork(ownValue(record, "network", "network")),
    transaction: {
      to: requiredAddress(ownValue(transaction, "to", "transaction.to"), "transaction.to"),
      data: optionalHexData(optionalOwnValue(transaction, "data")),
      value: unsignedBigInt(optionalOwnValue(transaction, "value") ?? "0", "transaction.value"),
      gas: optionalUnsignedBigInt(optionalOwnValue(transaction, "gas"), "transaction.gas"),
      maxFeePerGas: optionalUnsignedBigInt(
        optionalOwnValue(transaction, "maxFeePerGas"),
        "transaction.maxFeePerGas",
      ),
      maxPriorityFeePerGas: optionalUnsignedBigInt(
        optionalOwnValue(transaction, "maxPriorityFeePerGas"),
        "transaction.maxPriorityFeePerGas",
      ),
      nonce: optionalNonce(optionalOwnValue(transaction, "nonce")),
    },
  };
}
