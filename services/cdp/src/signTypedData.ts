import { makeRequestValidator } from "./requestValidation.js";

export type SignTypedDataOptions = {
  address: `0x${string}`;
  domain: {
    name?: string;
    version?: string;
    chainId?: number;
    verifyingContract?: `0x${string}`;
    salt?: `0x${string}`;
  };
  types: Record<string, { name: string; type: string }[]>;
  primaryType: string;
  message: Record<string, unknown>;
  idempotencyKey?: string;
};

const DOMAIN_FIELDS = new Set([
  "name",
  "version",
  "chainId",
  "verifyingContract",
  "salt",
]);

export class SignTypedDataRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SignTypedDataRequestError";
  }
}

const { asRecord, requiredAddress } = makeRequestValidator(
  (message) => new SignTypedDataRequestError(message),
);

function requiredNonEmptyString(value: unknown, name: string): string {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) {
    throw new SignTypedDataRequestError(`${name} must be a non-empty string`);
  }
  return text;
}

function optionalString(value: unknown, name: string): string | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  return requiredNonEmptyString(value, name);
}

function optionalSafeInteger(value: unknown, name: string): number | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value === "number" && Number.isSafeInteger(value) && value >= 0) {
    return value;
  }
  if (typeof value === "string" && /^\d+$/.test(value.trim())) {
    const parsed = Number(value.trim());
    if (Number.isSafeInteger(parsed)) {
      return parsed;
    }
  }
  throw new SignTypedDataRequestError(`${name} must be a non-negative safe integer`);
}

function optionalHex32(value: unknown, name: string): `0x${string}` | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value !== "string" || !/^0x[a-fA-F0-9]{64}$/.test(value.trim())) {
    throw new SignTypedDataRequestError(`${name} must be a 32-byte 0x-prefixed hex string`);
  }
  return value.trim() as `0x${string}`;
}

function normalizeDomain(value: unknown): SignTypedDataOptions["domain"] {
  const domain = asRecord(value, "domain");
  for (const key of Object.keys(domain)) {
    if (!DOMAIN_FIELDS.has(key)) {
      throw new SignTypedDataRequestError(`domain.${key} is not supported`);
    }
  }

  return {
    name: optionalString(domain.name, "domain.name"),
    version: optionalString(domain.version, "domain.version"),
    chainId: optionalSafeInteger(domain.chainId, "domain.chainId"),
    verifyingContract:
      domain.verifyingContract === undefined || domain.verifyingContract === null
        ? undefined
        : requiredAddress(domain.verifyingContract, "domain.verifyingContract"),
    salt: optionalHex32(domain.salt, "domain.salt"),
  };
}

function normalizeTypes(value: unknown): SignTypedDataOptions["types"] {
  const types = asRecord(value, "types");
  const normalized: SignTypedDataOptions["types"] = {};

  for (const [typeName, fields] of Object.entries(types)) {
    if (!typeName.trim()) {
      throw new SignTypedDataRequestError("types keys must be non-empty strings");
    }
    if (!Array.isArray(fields) || fields.length === 0) {
      throw new SignTypedDataRequestError(`types.${typeName} must be a non-empty array`);
    }
    normalized[typeName] = fields.map((field, index) => {
      const fieldRecord = asRecord(field, `types.${typeName}[${index}]`);
      return {
        name: requiredNonEmptyString(fieldRecord.name, `types.${typeName}[${index}].name`),
        type: requiredNonEmptyString(fieldRecord.type, `types.${typeName}[${index}].type`),
      };
    });
  }

  return normalized;
}

export function normalizeSignTypedDataRequest(body: unknown): SignTypedDataOptions {
  const record = asRecord(body, "request body");
  const types = normalizeTypes(record.types);
  const primaryType = requiredNonEmptyString(record.primaryType, "primaryType");
  if (!Object.hasOwn(types, primaryType)) {
    throw new SignTypedDataRequestError("primaryType must be defined in types");
  }

  const options: SignTypedDataOptions = {
    address: requiredAddress(record.address, "address"),
    domain: normalizeDomain(record.domain),
    types,
    primaryType,
    message: asRecord(record.message, "message"),
  };

  const idempotencyKey = optionalString(record.idempotencyKey, "idempotencyKey");
  if (idempotencyKey !== undefined) {
    options.idempotencyKey = idempotencyKey;
  }

  return options;
}
