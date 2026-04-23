export const PROTOCOL_COLORS: Record<string, string> = {
  acp: "#3b82f6",
  ap2: "#ef4444",
  cdp: "#10b981",
  x402: "#10b981",
  mpp: "#8b5cf6",
  stripe: "#8b5cf6",
  stripe_mpp: "#8b5cf6",
  atxp: "#f59e0b",
};

export const PROTOCOL_DISPLAY_LABELS = {
  acp: "ACP",
  ap2: "AP2",
  cdp: "CDP",
  x402: "x402",
  mpp: "Stripe MPP",
  stripe: "Stripe MPP",
  stripe_mpp: "Stripe MPP",
  atxp: "ATXP",
} as const;

export const SERVICE_PROTOCOL_LABEL_CONTRACT = [
  { service: "ap2", payloadProtocol: "ap2", displayLabel: "AP2" },
  { service: "cdp", payloadProtocol: "cdp", displayLabel: "CDP" },
  { service: "stripe", payloadProtocol: "mpp", displayLabel: "Stripe MPP" },
  { service: "atxp", payloadProtocol: "atxp", displayLabel: "ATXP" },
] as const satisfies readonly {
  service: "ap2" | "cdp" | "stripe" | "atxp";
  payloadProtocol: "ap2" | "cdp" | "mpp" | "atxp";
  displayLabel: "AP2" | "CDP" | "Stripe MPP" | "ATXP";
}[];

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2
  ? true
  : false;
type Expect<T extends true> = T;
type _ServiceProtocolLabelContract = [
  Expect<Equal<(typeof PROTOCOL_DISPLAY_LABELS)["ap2"], "AP2">>,
  Expect<Equal<(typeof PROTOCOL_DISPLAY_LABELS)["cdp"], "CDP">>,
  Expect<Equal<(typeof PROTOCOL_DISPLAY_LABELS)["mpp"], "Stripe MPP">>,
  Expect<Equal<(typeof PROTOCOL_DISPLAY_LABELS)["stripe"], "Stripe MPP">>,
  Expect<Equal<(typeof PROTOCOL_DISPLAY_LABELS)["atxp"], "ATXP">>,
];

export const AVATAR_COLORS = [
  "#3b82f6",
  "#ef4444",
  "#10b981",
  "#8b5cf6",
  "#f59e0b",
  "#ec4899",
  "#06b6d4",
  "#f97316",
];

export const TYPE_COLORS: Record<string, string> = {
  Buyer: "#3b82f6",
  Merchant: "#10b981",
  Product: "#f59e0b",
  Brand: "#8b5cf6",
  Transaction: "#ef4444",
};

export function normalizeProtocolKey(protocol: string | null | undefined): string {
  return String(protocol ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
}

export function getProtocolDisplayLabel(protocol: string | null | undefined): string {
  const key = normalizeProtocolKey(protocol);
  return PROTOCOL_DISPLAY_LABELS[key as keyof typeof PROTOCOL_DISPLAY_LABELS] ?? (key || "unknown").toUpperCase();
}

export function getProtocolColor(protocol: string | null | undefined): string {
  return PROTOCOL_COLORS[normalizeProtocolKey(protocol)] ?? "#6b7280";
}

export function getAvatarColor(name: string): string {
  if (!name) return AVATAR_COLORS[0];
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

export function getEntityColor(type: string): string {
  return TYPE_COLORS[type] ?? "#71717a";
}

export const MAX_EVENTS = 500;
export const MAX_PURCHASES = 100;
