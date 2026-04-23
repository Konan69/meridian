import { makeRequestValidator } from "./requestValidation.js";

export type SignMessageOptions = {
  address: `0x${string}`;
  message: string;
};

export class SignMessageRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SignMessageRequestError";
  }
}

const { asRecord, requiredAddress } = makeRequestValidator(
  (message) => new SignMessageRequestError(message),
);

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
