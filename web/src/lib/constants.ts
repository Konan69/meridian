export const PROTOCOL_COLORS: Record<string, string> = {
  acp: "#3b82f6",
  ap2: "#ef4444",
  x402: "#10b981",
  mpp: "#8b5cf6",
  atxp: "#f59e0b",
};

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

export function getProtocolColor(protocol: string): string {
  return PROTOCOL_COLORS[protocol?.toLowerCase()] ?? "#6b7280";
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
