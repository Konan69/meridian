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

const { asRecord, requiredAddress, requiredNonEmptyString } = makeRequestValidator(
  (message) => new SignMessageRequestError(message),
);

export function normalizeSignMessageRequest(body: unknown): SignMessageOptions {
  const record = asRecord(body, "request body");

  return {
    address: requiredAddress(record.address, "address"),
    message: requiredNonEmptyString(record.message, "message", {
      preserveWhitespace: true,
    }),
  };
}
