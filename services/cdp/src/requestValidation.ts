import { isHexAddress } from "./treasury.js";

export type JsonRecord = Record<string, unknown>;

type RequestErrorFactory = (message: string) => Error;

type NonEmptyStringOptions = {
  preserveWhitespace?: boolean;
};

export function makeRequestValidator(makeError: RequestErrorFactory) {
  function requiredNonEmptyString(
    value: unknown,
    name: string,
    options: NonEmptyStringOptions = {},
  ): string {
    if (typeof value !== "string") {
      throw makeError(`${name} must be a non-empty string`);
    }
    const text = options.preserveWhitespace ? value : value.trim();
    if (text.length === 0) {
      throw makeError(`${name} must be a non-empty string`);
    }
    return text;
  }

  return {
    asRecord(value: unknown, name: string): JsonRecord {
      if (typeof value !== "object" || value === null || Array.isArray(value)) {
        throw makeError(`${name} must be an object`);
      }
      return value as JsonRecord;
    },

    requiredAddress(value: unknown, name: string): `0x${string}` {
      const address = typeof value === "string" ? value.trim() : "";
      if (!isHexAddress(address)) {
        throw makeError(`${name} must be an EVM address`);
      }
      return address;
    },

    requiredNonEmptyString,

    optionalNonEmptyString(value: unknown, name: string): string | undefined {
      if (value === undefined || value === null) {
        return undefined;
      }
      return requiredNonEmptyString(value, name);
    },
  };
}
