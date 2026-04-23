import { createHmac } from "node:crypto";

export type MppKeyScope = "mpp-actor" | "mpp-merchant";

export function deriveMppPrivateKey(
  scope: MppKeyScope,
  id: string,
  masterSeed = process.env.MPP_MASTER_SEED,
): `0x${string}` {
  if (!masterSeed) {
    throw new Error("MPP_MASTER_SEED is required for runtime MPP execution");
  }
  const digest = createHmac("sha256", masterSeed).update(`${scope}:${id}`).digest("hex");
  return `0x${digest}` as `0x${string}`;
}
