export type MppExecuteRequest = {
  actorId: string;
  merchant: string;
  amountUsd: number;
};

export type MppAuthorizeRequest = MppExecuteRequest & {
  memo?: string;
};

export type ValidatedMppExecuteRequest = {
  actorId: string;
  merchant: string;
  amountUsd: number;
};

export type ValidatedMppAuthorizeRequest = ValidatedMppExecuteRequest & {
  memo: string;
};

export type MppPaidResourcePayload = {
  ok: true;
  message: "MPP payment accepted";
  recipient: `0x${string}`;
  merchant: string;
  amountUsd: number;
};

export type MppSettlementReceipt = {
  reference: string;
};

export type MppSettlementResponse = {
  ok: true;
  actorId: string;
  merchant: string;
  amountUsd: number;
  receipt: MppSettlementReceipt;
  paymentId: string;
  response: unknown;
};

const REQUIRED_PAYMENT_FIELDS_MESSAGE = "actorId, merchant, and amountUsd are required";

export function isHexAddress(value: string): value is `0x${string}` {
  return /^0x[a-fA-F0-9]{40}$/.test(value);
}

export function amountUsdFromRequest(request: Request): string {
  const url = new URL(request.url);
  const requested = Number(url.searchParams.get("amountUsd") ?? "0.01");
  return requested > 0 ? requested.toFixed(2) : "0.01";
}

export function merchantFromRequest(request: Request): string {
  const url = new URL(request.url);
  return url.searchParams.get("merchant")?.trim() || "meridian-mpp-merchant";
}

export function validateMppExecuteRequest(
  body: Partial<MppExecuteRequest>,
): ValidatedMppExecuteRequest {
  const actorId = String(body.actorId ?? "").trim();
  const merchant = String(body.merchant ?? "").trim();
  const amountUsd = Number(body.amountUsd ?? 0);
  if (!actorId || !merchant || !(amountUsd > 0)) {
    throw new Error(REQUIRED_PAYMENT_FIELDS_MESSAGE);
  }
  return { actorId, merchant, amountUsd };
}

export function validateMppAuthorizeRequest(
  body: Partial<MppAuthorizeRequest>,
): ValidatedMppAuthorizeRequest {
  const request = validateMppExecuteRequest(body);
  const memo = String(body.memo ?? `meridian-mpp:${request.actorId}:${request.merchant}`).trim();
  return {
    ...request,
    memo: memo || `meridian-mpp:${request.actorId}:${request.merchant}`,
  };
}

export function paidResourceUrlForMppExecute(
  baseUrl: string,
  request: ValidatedMppExecuteRequest,
): string {
  const url = new URL("/mpp/paid", baseUrl);
  url.searchParams.set("merchant", request.merchant);
  url.searchParams.set("amountUsd", request.amountUsd.toFixed(2));
  return url.toString();
}

export function paidResourcePayloadForMppSettlement(
  request: Request,
  recipient: `0x${string}`,
): MppPaidResourcePayload {
  const amountUsd = amountUsdFromRequest(request);
  return {
    ok: true,
    message: "MPP payment accepted",
    recipient,
    merchant: merchantFromRequest(request),
    amountUsd: Number(amountUsd),
  };
}

export function settlementResponseForMppExecute(
  request: ValidatedMppExecuteRequest,
  receipt: MppSettlementReceipt,
  response: unknown,
): MppSettlementResponse {
  return {
    ok: true,
    actorId: request.actorId,
    merchant: request.merchant,
    amountUsd: request.amountUsd,
    receipt,
    paymentId: receipt.reference,
    response,
  };
}
