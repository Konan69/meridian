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
const TYPE_FIELD_KEYS = new Set(["name", "type"]);

export class SignTypedDataRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SignTypedDataRequestError";
  }
}

const {
  asRecord,
  ownValue,
  optionalOwnValue,
  requiredAddress,
  requiredNonEmptyString,
  optionalNonEmptyString,
} =
  makeRequestValidator(
    (message) => new SignTypedDataRequestError(message),
  );

function requiredExactNonEmptyString(value: unknown, name: string): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new SignTypedDataRequestError(`${name} must be a non-empty string`);
  }
  return value;
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
    name: optionalNonEmptyString(optionalOwnValue(domain, "name"), "domain.name"),
    version: optionalNonEmptyString(optionalOwnValue(domain, "version"), "domain.version"),
    chainId: optionalSafeInteger(optionalOwnValue(domain, "chainId"), "domain.chainId"),
    verifyingContract:
      optionalOwnValue(domain, "verifyingContract") === undefined ||
      optionalOwnValue(domain, "verifyingContract") === null
        ? undefined
        : requiredAddress(
            optionalOwnValue(domain, "verifyingContract"),
            "domain.verifyingContract",
          ),
    salt: optionalHex32(optionalOwnValue(domain, "salt"), "domain.salt"),
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
    const fieldNames = new Set<string>();
    normalized[typeName] = fields.map((field, index) => {
      const fieldRecord = asRecord(field, `types.${typeName}[${index}]`);
      for (const key of Object.keys(fieldRecord)) {
        if (!TYPE_FIELD_KEYS.has(key)) {
          throw new SignTypedDataRequestError(`types.${typeName}[${index}].${key} is not supported`);
        }
      }
      const normalizedField = {
        name: requiredExactNonEmptyString(
          ownValue(fieldRecord, "name", `types.${typeName}[${index}].name`),
          `types.${typeName}[${index}].name`,
        ),
        type: requiredExactNonEmptyString(
          ownValue(fieldRecord, "type", `types.${typeName}[${index}].type`),
          `types.${typeName}[${index}].type`,
        ),
      };
      if (fieldNames.has(normalizedField.name)) {
        throw new SignTypedDataRequestError(`types.${typeName} contains duplicate field ${normalizedField.name}`);
      }
      fieldNames.add(normalizedField.name);
      return normalizedField;
    });
  }

  return normalized;
}

function normalizeMessage(
  value: unknown,
  primaryType: string,
  fields: { name: string; type: string }[],
): SignTypedDataOptions["message"] {
  const message = asRecord(value, "message");
  for (const field of fields) {
    if (!Object.hasOwn(message, field.name)) {
      throw new SignTypedDataRequestError(`message.${field.name} is required by primaryType ${primaryType}`);
    }
  }
  return message;
}

export function normalizeSignTypedDataRequest(body: unknown): SignTypedDataOptions {
  const record = asRecord(body, "request body");
  const types = normalizeTypes(ownValue(record, "types", "types"));
  const primaryType = requiredExactNonEmptyString(
    ownValue(record, "primaryType", "primaryType"),
    "primaryType",
  );
  if (!Object.hasOwn(types, primaryType)) {
    throw new SignTypedDataRequestError("primaryType must be defined in types");
  }

  const options: SignTypedDataOptions = {
    address: requiredAddress(ownValue(record, "address", "address"), "address"),
    domain: normalizeDomain(ownValue(record, "domain", "domain")),
    types,
    primaryType,
    message: normalizeMessage(ownValue(record, "message", "message"), primaryType, types[primaryType]),
  };

  const idempotencyKey = optionalNonEmptyString(
    optionalOwnValue(record, "idempotencyKey"),
    "idempotencyKey",
  );
  if (idempotencyKey !== undefined) {
    options.idempotencyKey = idempotencyKey;
  }

  return options;
}
