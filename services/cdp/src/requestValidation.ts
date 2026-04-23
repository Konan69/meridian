import { isHexAddress } from "./treasury.js";

export type JsonRecord = Record<string, unknown>;

type RequestErrorFactory = (message: string) => Error;

export function makeRequestValidator(makeError: RequestErrorFactory) {
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
  };
}
