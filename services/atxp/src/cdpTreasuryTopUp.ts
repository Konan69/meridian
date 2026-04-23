export const DEFAULT_TREASURY_NATIVE_TOPUP_ETH = "0.00002";
export const DEFAULT_TREASURY_USDC_TOPUP_UNITS = 1_000_000n;

export type CdpTreasuryTopUpPlan = {
  fromAddress: string;
  nativeAmount: string;
  usdcAmountUnits: bigint;
};

function envBigInt(
  env: Record<string, string | undefined>,
  name: string,
  fallback: bigint,
): bigint {
  const value = env[name]?.trim();
  if (!value) {
    return fallback;
  }
  try {
    const parsed = BigInt(value);
    return parsed >= 0n ? parsed : fallback;
  } catch {
    return fallback;
  }
}

function envPositiveDecimal(
  env: Record<string, string | undefined>,
  name: string,
  fallback: string,
): string {
  const value = env[name]?.trim();
  if (!value) {
    return fallback;
  }
  if (!/^\d+(\.\d+)?$/.test(value) || !/[1-9]/.test(value)) {
    return fallback;
  }
  return value;
}

export function planCdpBaseTreasuryTopUp(
  minAmountUnits: bigint,
  env: Record<string, string | undefined> = process.env,
): CdpTreasuryTopUpPlan | null {
  if (minAmountUnits < 0n) {
    throw new RangeError("minAmountUnits must be non-negative");
  }

  const fromAddress = env.ATXP_CDP_TREASURY_ADDRESS?.trim();
  if (!fromAddress) {
    return null;
  }

  const configuredUsdc = envBigInt(
    env,
    "ATXP_CDP_TREASURY_USDC_TOPUP_UNITS",
    DEFAULT_TREASURY_USDC_TOPUP_UNITS,
  );
  const nativeAmount = envPositiveDecimal(
    env,
    "ATXP_CDP_TREASURY_NATIVE_TOPUP",
    DEFAULT_TREASURY_NATIVE_TOPUP_ETH,
  );

  return {
    fromAddress,
    nativeAmount,
    usdcAmountUnits: minAmountUnits > configuredUsdc ? minAmountUnits : configuredUsdc,
  };
}
