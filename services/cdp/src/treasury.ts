export const BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
const ERC20_TRANSFER_SELECTOR = "a9059cbb";

export type TreasuryTransferRequest = {
  fromAddress?: string;
  toAddress?: string;
  amount?: string | number;
  amountUnits?: string | number;
  network?: string;
};

export type NativeTransferRequest = TreasuryTransferRequest & {
  amountWei?: string | number;
};

export function isHexAddress(value: string): value is `0x${string}` {
  return /^0x[a-fA-F0-9]{40}$/.test(value);
}

export function parseDecimalUnits(value: string | number, decimals: number): bigint {
  const normalized = String(value).trim();
  if (!/^\d+(\.\d+)?$/.test(normalized)) {
    throw new Error("amount must be a non-negative decimal string");
  }

  const [whole, fraction = ""] = normalized.split(".");
  if (fraction.length > decimals) {
    throw new Error(`amount supports at most ${decimals} decimal places`);
  }

  const scale = 10n ** BigInt(decimals);
  return BigInt(whole || "0") * scale + BigInt(fraction.padEnd(decimals, "0") || "0");
}

export function amountUnitsFromRequest(
  body: TreasuryTransferRequest,
  decimals: number,
): bigint {
  if (body.amountUnits !== undefined && body.amountUnits !== null) {
    const rawUnits = String(body.amountUnits).trim();
    if (!/^\d+$/.test(rawUnits)) {
      throw new Error("amountUnits must be a non-negative integer string");
    }
    return BigInt(rawUnits);
  }

  if (body.amount === undefined || body.amount === null) {
    throw new Error("amount or amountUnits is required");
  }

  return parseDecimalUnits(body.amount, decimals);
}

export function nativeValueWeiFromRequest(body: NativeTransferRequest): bigint {
  if (body.amountWei !== undefined && body.amountWei !== null) {
    const rawWei = String(body.amountWei).trim();
    if (!/^\d+$/.test(rawWei)) {
      throw new Error("amountWei must be a non-negative integer string");
    }
    return BigInt(rawWei);
  }

  return amountUnitsFromRequest(body, 18);
}

export function encodeErc20Transfer(
  toAddress: `0x${string}`,
  amountUnits: bigint,
): `0x${string}` {
  const addressArg = toAddress.slice(2).toLowerCase().padStart(64, "0");
  const amountArg = amountUnits.toString(16).padStart(64, "0");
  return `0x${ERC20_TRANSFER_SELECTOR}${addressArg}${amountArg}`;
}
