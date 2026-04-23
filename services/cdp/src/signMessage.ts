import { isHexAddress } from "./treasury.js";

export type SignMessageOptions = {
  address: `0x${string}`;
  message: string;
};

type JsonRecord = Record<string, unknown>;

export class SignMessageRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SignMessageRequestError";
  }
}

function asRecord(value: unknown, name: string): JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new SignMessageRequestError(`${name} must be an object`);
  }
  return value as JsonRecord;
}

function requiredAddress(value: unknown, name: string): `0x${string}` {
  const address = typeof value === "string" ? value.trim() : "";
  if (!isHexAddress(address)) {
    throw new SignMessageRequestError(`${name} must be an EVM address`);
  }
  return address;
}

function requiredMessage(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new SignMessageRequestError("message must be a non-empty string");
  }
  return value;
}

export function normalizeSignMessageRequest(body: unknown): SignMessageOptions {
  const record = asRecord(body, "request body");

  return {
    address: requiredAddress(record.address, "address"),
    message: requiredMessage(record.message),
  };
}
