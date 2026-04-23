export type MppExecuteRequest = {
  actorId: string;
  merchant: string;
  amountUsd: number;
};

export type ValidatedMppExecuteRequest = {
  actorId: string;
  merchant: string;
  amountUsd: number;
};

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
    throw new Error("actorId, merchant, and amountUsd are required");
  }
  return { actorId, merchant, amountUsd };
}
