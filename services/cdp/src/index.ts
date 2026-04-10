import "dotenv/config";
import { CdpClient } from "@coinbase/cdp-sdk";
import express, { Request, Response } from "express";
import fs from "node:fs";

const port = process.env.PORT ? parseInt(process.env.PORT, 10) : 3030;

type SignTypedDataRequest = {
  address: `0x${string}`;
  domain: Record<string, unknown>;
  types: Record<string, unknown>;
  primaryType: string;
  message: Record<string, unknown>;
};

type SendTransactionRequest = {
  address: `0x${string}`;
  network: "base-sepolia" | "base";
  transaction: {
    to: `0x${string}`;
    data?: `0x${string}`;
    value?: string;
    gas?: string;
    maxFeePerGas?: string;
    maxPriorityFeePerGas?: string;
    nonce?: number;
  };
};

type SendTransactionOptions = {
  address: `0x${string}`;
  network: "base-sepolia" | "base";
  transaction: {
    to: `0x${string}`;
    data?: `0x${string}`;
    value: bigint;
    gas?: bigint;
    maxFeePerGas?: bigint;
    maxPriorityFeePerGas?: bigint;
    nonce?: number;
  };
};

type KeyFile = {
  id?: string;
  privateKey?: string;
};

function loadApiKeyFile(): KeyFile {
  const file = process.env.CDP_API_KEY_FILE;
  if (!file) return {};
  const raw = fs.readFileSync(file, "utf8");
  return JSON.parse(raw) as KeyFile;
}

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env: ${name}`);
  if (
    value.startsWith("YOUR_") ||
    value.startsWith("SET_YOUR_") ||
    value.includes("EMBEDDED_WALLET")
  ) {
    throw new Error(
      `Invalid ${name}: Meridian x402 requires Coinbase Server Wallet credentials, not placeholders or Embedded Wallet credentials`,
    );
  }
  return value;
}

const keyFile = loadApiKeyFile();
const apiKeyId = process.env.CDP_API_KEY_ID || keyFile.id;
const apiKeySecret = process.env.CDP_API_KEY_SECRET || keyFile.privateKey;

const cdp = new CdpClient({
  apiKeyId: apiKeyId || requireEnv("CDP_API_KEY_ID"),
  apiKeySecret: apiKeySecret || requireEnv("CDP_API_KEY_SECRET"),
  walletSecret: requireEnv("CDP_WALLET_SECRET"),
});

const app = express();
app.use(express.json({ limit: "1mb" }));

app.get("/health", (_req: Request, res: Response) => {
  res.json({
    status: "ok",
    service: "meridian-cdp",
    wallet_product: "server_wallet_v2",
    timestamp: new Date().toISOString(),
  });
});

app.post("/evm/get-or-create-account", async (req: Request, res: Response) => {
  try {
    const name = String(req.body?.name || "").trim();
    if (!name) {
      res.status(400).json({ error: "name is required" });
      return;
    }

    const account = await cdp.evm.getOrCreateAccount({ name });
    res.json({
      address: account.address,
      name,
    });
  } catch (error) {
    res.status(500).json({ error: String((error as Error)?.message || error) });
  }
});

app.post("/evm/request-faucet", async (req: Request, res: Response) => {
  try {
    const address = String(req.body?.address || "").trim();
    const token = String(req.body?.token || "eth").trim() as "eth" | "usdc" | "eurc" | "cbbtc";
    if (!address) {
      res.status(400).json({ error: "address is required" });
      return;
    }

    const faucet = await cdp.evm.requestFaucet({
      address,
      network: "base-sepolia",
      token,
    });
    res.json(faucet);
  } catch (error) {
    res.status(500).json({ error: String((error as Error)?.message || error) });
  }
});

app.get("/evm/token-balances/:address", async (req: Request, res: Response) => {
  try {
    const address = String(req.params.address || "").trim();
    if (!address) {
      res.status(400).json({ error: "address is required" });
      return;
    }

    const result = await cdp.evm.listTokenBalances({
      address: address as `0x${string}`,
      network: "base-sepolia",
    });

    res.json({
      balances: result.balances.map((balance) => ({
        contractAddress: balance.token.contractAddress,
        symbol: balance.token.symbol ?? null,
        name: balance.token.name ?? null,
        amount: balance.amount.amount.toString(),
        decimals: balance.amount.decimals,
      })),
    });
  } catch (error) {
    res.status(500).json({ error: String((error as Error)?.message || error) });
  }
});

app.post("/evm/sign-message", async (req: Request, res: Response) => {
  try {
    const address = String(req.body?.address || "").trim();
    const message = String(req.body?.message || "");
    if (!address || !message) {
      res.status(400).json({ error: "address and message are required" });
      return;
    }
    const result = await cdp.evm.signMessage({ address: address as `0x${string}`, message });
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String((error as Error)?.message || error) });
  }
});

app.post("/evm/sign-typed-data", async (req: Request, res: Response) => {
  try {
    const { address, domain, types, primaryType, message } = req.body ?? {};
    if (!address || !domain || !types || !primaryType || !message) {
      res.status(400).json({
        error: "address, domain, types, primaryType, and message are required",
      });
      return;
    }
    const typedDataRequest: SignTypedDataRequest = {
      address,
      domain,
      types,
      primaryType,
      message,
    };
    const result = await cdp.evm.signTypedData(typedDataRequest);
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String((error as Error)?.message || error) });
  }
});

app.post("/evm/send-transaction", async (req: Request, res: Response) => {
  try {
    const { address, network, transaction } = (req.body ?? {}) as Partial<SendTransactionRequest>;
    if (!address || !network || !transaction?.to) {
      res.status(400).json({
        error: "address, network, and transaction.to are required",
      });
      return;
    }

    const txOptions: SendTransactionOptions = {
      address,
      network,
      transaction: {
        to: transaction.to,
        data: transaction.data,
        value: BigInt(transaction.value ?? "0"),
        gas: transaction.gas ? BigInt(transaction.gas) : undefined,
        maxFeePerGas: transaction.maxFeePerGas
          ? BigInt(transaction.maxFeePerGas)
          : undefined,
        maxPriorityFeePerGas: transaction.maxPriorityFeePerGas
          ? BigInt(transaction.maxPriorityFeePerGas)
          : undefined,
        nonce: transaction.nonce,
      },
    };

    const result = await cdp.evm.sendTransaction(txOptions);
    res.json(result);
  } catch (error) {
    res.status(500).json({ error: String((error as Error)?.message || error) });
  }
});

app.listen(port, () => {
  console.log(`meridian-cdp listening on http://localhost:${port}`);
});
