import { spawn } from "node:child_process";
import type { RequestHandler } from "./$types";
import { resolve } from "node:path";

export const POST: RequestHandler = async ({ request }) => {
  const {
    agents = 50,
    rounds = 10,
    protocols,
    merchantsPerCategory = 3,
    flowMix,
    stableUniverse = "usdc_centric",
  } = await request.json();

  // Path to the Python simulation
  const simDir = resolve(process.cwd(), "..", "sim");
  const pythonPath = resolve(simDir, ".venv", "bin", "python");

  const child = spawn(pythonPath, ["-m", "sim.engine"], {
    cwd: simDir,
    env: {
      ...process.env,
      MERIDIAN_AGENTS: String(agents),
      MERIDIAN_ROUNDS: String(rounds),
      MERIDIAN_MERCHANTS_PER_CATEGORY: String(merchantsPerCategory),
      MERIDIAN_STABLE_UNIVERSE: String(stableUniverse),
      ...(Array.isArray(protocols) && protocols.length > 0
        ? { MERIDIAN_PROTOCOLS: protocols.join(",") }
        : {}),
      ...(flowMix ? { MERIDIAN_FLOW_MIX: JSON.stringify(flowMix) } : {}),
    },
  });

  const stream = new ReadableStream({
    start(controller) {
      child.stdout.on("data", (data: Uint8Array) => {
        controller.enqueue(data);
      });

      child.stderr.on("data", (data: Uint8Array) => {
        console.error("[sim stderr]", data.toString());
      });

      child.on("close", () => {
        controller.close();
      });

      child.on("error", (err: Error) => {
        console.error("[sim error]", err);
        controller.close();
      });
    },
    cancel() {
      child.kill();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "application/x-ndjson",
      "Transfer-Encoding": "chunked",
    },
  });
};
