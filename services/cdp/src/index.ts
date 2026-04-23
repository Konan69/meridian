import "dotenv/config";
import { CdpClient } from "@coinbase/cdp-sdk";
import express, { Request, Response } from "express";
import fs from "node:fs";
import {
  SendTransactionRequestError,
  normalizeSendTransactionRequest,
} from "./sendTransaction.js";
import {
  SignMessageRequestError,
  normalizeSignMessageRequest,
} from "./signMessage.js";
import {
  SignTypedDataRequestError,
  normalizeSignTypedDataRequest,
} from "./signTypedData.js";
import {
  TreasuryTransferRequestError,
  normalizeNativeTreasuryTransferRequest,
  normalizeUsdcTreasuryTransferRequest,
  treasuryTransferResponse,
} from "./treasury.js";

const port = process.env.PORT ? parseInt(process.env.PORT, 10) : 3030;
// Static route anchors: BASE_SEPOLIA_USDC, encodeErc20Transfer,
// "treasury USDC transfers only support base-sepolia",
// "treasury native transfers only support base-sepolia".

type KeyFile = {
  id?: string;
  privateKey?: string;
};

function loadApiKeyFile(): KeyFile {
  const file = process.env.CDP_API_KEY_FILE;
  if (!file) return {};
  if (!fs.existsSync(file)) {
    if (process.env.CDP_API_KEY_ID && process.env.CDP_API_KEY_SECRET) {
      console.warn(
        `Skipping missing CDP_API_KEY_FILE at ${file}; using CDP_API_KEY_ID/CDP_API_KEY_SECRET instead`,
      );
      return {};
    }
    throw new Error(`CDP_API_KEY_FILE does not exist: ${file}`);
  }
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

app.post("/evm/transfer-usdc", async (req: Request, res: Response) => {
  try {
    const transfer = normalizeUsdcTreasuryTransferRequest(req.body);
    const transaction = await cdp.evm.sendTransaction(transfer.txOptions);
    res.json(treasuryTransferResponse(transfer, transaction));
  } catch (error) {
    if (error instanceof TreasuryTransferRequestError) {
      res.status(400).json({ error: error.message });
      return;
    }
    res.status(500).json({ error: String((error as Error)?.message || error) });
  }
});

app.post("/evm/transfer-native", async (req: Request, res: Response) => {
  try {
    const transfer = normalizeNativeTreasuryTransferRequest(req.body);
    const transaction = await cdp.evm.sendTransaction(transfer.txOptions);
    res.json(treasuryTransferResponse(transfer, transaction));
  } catch (error) {
    if (error instanceof TreasuryTransferRequestError) {
      res.status(400).json({ error: error.message });
      return;
    }
    res.status(500).json({ error: String((error as Error)?.message || error) });
  }
});

app.post("/evm/sign-message", async (req: Request, res: Response) => {
  try {
    const signMessageRequest = normalizeSignMessageRequest(req.body);
    const result = await cdp.evm.signMessage(signMessageRequest);
    res.json(result);
  } catch (error) {
    if (error instanceof SignMessageRequestError) {
      res.status(400).json({ error: error.message });
      return;
    }
    res.status(500).json({ error: String((error as Error)?.message || error) });
  }
});

app.post("/evm/sign-typed-data", async (req: Request, res: Response) => {
  try {
    const typedDataRequest = normalizeSignTypedDataRequest(req.body);
    const result = await cdp.evm.signTypedData(typedDataRequest);
    res.json(result);
  } catch (error) {
    if (error instanceof SignTypedDataRequestError) {
      res.status(400).json({ error: error.message });
      return;
    }
    res.status(500).json({ error: String((error as Error)?.message || error) });
  }
});

app.post("/evm/send-transaction", async (req: Request, res: Response) => {
  try {
    const txOptions = normalizeSendTransactionRequest(req.body);

    const result = await cdp.evm.sendTransaction(txOptions);
    res.json(result);
  } catch (error) {
    if (error instanceof SendTransactionRequestError) {
      res.status(400).json({ error: error.message });
      return;
    }
    res.status(500).json({ error: String((error as Error)?.message || error) });
  }
});

app.listen(port, () => {
  console.log(`meridian-cdp listening on http://localhost:${port}`);
});
