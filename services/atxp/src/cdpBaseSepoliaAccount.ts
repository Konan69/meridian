import { BigNumber } from "bignumber.js";
import {
  type Account,
  type AccountId,
  type AuthorizeParams,
  type AuthorizeResult,
  type Currency,
  type Destination,
  type PaymentIdentifier,
  type PaymentMaker,
  type Source,
} from "@atxp/common";
import { UnsupportedCurrencyError } from "@atxp/client";
import { encodeFunctionData } from "viem";

const USDC_DECIMALS = 6;
const ERC20_ABI = [
  {
    constant: false,
    inputs: [
      { name: "_to", type: "address" },
      { name: "_value", type: "uint256" },
    ],
    name: "transfer",
    outputs: [{ name: "", type: "bool" }],
    type: "function",
  },
] as const;

type CdpAccountResponse = {
  address: `0x${string}`;
  name: string;
};

type CdpTransactionResponse = {
  transactionHash: `0x${string}`;
};

type CdpBalancesResponse = {
  balances: Array<{
    contractAddress: string;
    amount: string;
  }>;
};

type CdpSignatureResponse = {
  signature: `0x${string}`;
};

const USDC_CONTRACT_ADDRESS_BASE_SEPOLIA =
  "0x036CbD53842c5426634e7929541eC2318f3dCF7e";
const USDC_CONTRACT_ADDRESS_BASE_SEPOLIA_LOWER =
  USDC_CONTRACT_ADDRESS_BASE_SEPOLIA.toLowerCase();

function toBase64Url(data: string): string {
  return Buffer.from(data)
    .toString("base64")
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

class CdpBaseSepoliaPaymentMaker implements PaymentMaker {
  constructor(
    private readonly serviceUrl: string,
    private readonly getAddress: () => Promise<`0x${string}`>,
  ) {}

  private async ensureFunded(minAmountUnits: bigint): Promise<void> {
    const address = await this.getAddress();
    let lastSeenUsdc = 0n;

    const balancesResponse = await fetch(
      `${this.serviceUrl}/evm/token-balances/${address}`,
    );
    const balancesBody = (await balancesResponse.json()) as CdpBalancesResponse & {
      error?: string;
    };
    if (
      balancesResponse.ok &&
      balancesBody.balances.some(
        (balance) =>
          balance.contractAddress.toLowerCase() ===
            USDC_CONTRACT_ADDRESS_BASE_SEPOLIA_LOWER &&
          BigInt(balance.amount) >= minAmountUnits,
      )
    ) {
      return;
    }
    const existingUsdc = balancesBody.balances.find(
      (balance) =>
        balance.contractAddress.toLowerCase() === USDC_CONTRACT_ADDRESS_BASE_SEPOLIA_LOWER,
    );
    if (existingUsdc) {
      lastSeenUsdc = BigInt(existingUsdc.amount);
    }

    for (const token of ["eth", "usdc"] as const) {
      await fetch(`${this.serviceUrl}/evm/request-faucet`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
        },
        body: JSON.stringify({
          address,
          token,
        }),
      });
    }

    for (let attempt = 0; attempt < 15; attempt += 1) {
      const response = await fetch(`${this.serviceUrl}/evm/token-balances/${address}`);
      const body = (await response.json()) as CdpBalancesResponse & {
        error?: string;
      };
      if (
        response.ok &&
        body.balances.some(
          (balance) =>
            balance.contractAddress.toLowerCase() ===
              USDC_CONTRACT_ADDRESS_BASE_SEPOLIA_LOWER &&
            BigInt(balance.amount) >= minAmountUnits,
        )
      ) {
        return;
      }
      const usdcBalance = body.balances.find(
        (balance) =>
          balance.contractAddress.toLowerCase() === USDC_CONTRACT_ADDRESS_BASE_SEPOLIA_LOWER,
      );
      if (usdcBalance) {
        lastSeenUsdc = BigInt(usdcBalance.amount);
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }

    throw new Error(
      `CDP Base payer still underfunded after faucet requests: ${lastSeenUsdc.toString()} < ${minAmountUnits.toString()}`,
    );
  }

  async getSourceAddress(_params: {
    amount: BigNumber;
    currency: Currency;
    receiver: string;
    memo: string;
  }): Promise<string> {
    return this.getAddress();
  }

  async generateJWT(params: {
    paymentRequestId: string;
    codeChallenge: string;
    accountId?: AccountId | null;
  }): Promise<string> {
    const header = toBase64Url(JSON.stringify({ alg: "ES256K" }));
    const payload = toBase64Url(
      JSON.stringify({
        sub: await this.getAddress(),
        iss: "accounts.atxp.ai",
        aud: "https://auth.atxp.ai",
        iat: Math.floor(Date.now() / 1000),
        exp: Math.floor(Date.now() / 1000) + 60 * 60,
        code_challenge: params.codeChallenge,
        payment_request_id: params.paymentRequestId,
        ...(params.accountId ? { account_id: params.accountId } : {}),
      }),
    );
    const message = `${header}.${payload}`;
    const response = await fetch(`${this.serviceUrl}/evm/sign-message`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify({
        address: await this.getAddress(),
        message,
      }),
    });
    const body = (await response.json()) as Partial<CdpSignatureResponse> & {
      error?: string;
    };
    if (!response.ok || !body.signature) {
      throw new Error(body.error ?? "CDP sign message failed");
    }
    const signature = toBase64Url(body.signature);
    return `${header}.${payload}.${signature}`;
  }

  async makePayment(
    destinations: Destination[],
    _memo: string,
    _paymentRequestId?: string,
  ): Promise<PaymentIdentifier | null> {
    const destination = destinations.find((d) => d.chain === "base");
    if (!destination) {
      return null;
    }
    if (destination.currency.toUpperCase() !== "USDC") {
      throw new UnsupportedCurrencyError(destination.currency, "base_sepolia", ["USDC"]);
    }

    const amountInUnits = BigInt(
      destination.amount.multipliedBy(10 ** USDC_DECIMALS).toFixed(0),
    );
    await this.ensureFunded(amountInUnits);
    const sourceAddress = await this.getAddress();
    const response = await fetch(`${this.serviceUrl}/evm/send-transaction`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify({
        address: sourceAddress,
        network: "base-sepolia",
        transaction: {
          to: USDC_CONTRACT_ADDRESS_BASE_SEPOLIA,
          data: encodeFunctionData({
            abi: ERC20_ABI,
            functionName: "transfer",
            args: [destination.address as `0x${string}`, amountInUnits],
          }),
          value: "0",
        },
      }),
    });
    const body = (await response.json()) as Partial<CdpTransactionResponse> & {
      error?: string;
    };
    if (!response.ok || !body.transactionHash) {
      throw new Error(body.error ?? "CDP send transaction failed");
    }

    return {
      transactionId: body.transactionHash,
      chain: "base",
      currency: "USDC",
    };
  }
}

export class CdpBaseSepoliaAccount implements Account {
  readonly paymentMakers: PaymentMaker[];
  private addressPromise: Promise<`0x${string}`> | null = null;

  constructor(
    private readonly serviceUrl: string,
    private readonly accountName: string,
  ) {
    this.paymentMakers = [
      new CdpBaseSepoliaPaymentMaker(this.serviceUrl, async () => this.getAddress()),
    ];
  }

  private async getAddress(): Promise<`0x${string}`> {
    if (!this.addressPromise) {
      this.addressPromise = (async () => {
        const response = await fetch(`${this.serviceUrl}/evm/get-or-create-account`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
          },
          body: JSON.stringify({ name: this.accountName }),
        });
        const body = (await response.json()) as Partial<CdpAccountResponse> & {
          error?: string;
        };
        if (!response.ok || !body.address) {
          throw new Error(body.error ?? "CDP get-or-create-account failed");
        }
        return body.address;
      })();
    }
    return this.addressPromise;
  }

  async getAccountId(): Promise<AccountId> {
    return `base:${await this.getAddress()}`;
  }

  async getSources(): Promise<Source[]> {
    return [
      {
        address: await this.getAddress(),
        chain: "base",
        walletType: "eoa",
      },
    ];
  }

  async createSpendPermission(_resourceUrl: string): Promise<string | null> {
    return null;
  }

  async authorize(params: AuthorizeParams): Promise<AuthorizeResult> {
    if (!params.protocols.includes("atxp")) {
      throw new Error("CdpBaseSepoliaAccount only supports atxp authorization");
    }
    if (!params.amount) {
      throw new Error("CdpBaseSepoliaAccount: amount is required");
    }
    if (!params.destination) {
      throw new Error("CdpBaseSepoliaAccount: destination is required");
    }

    const paymentMaker = this.paymentMakers[0] as CdpBaseSepoliaPaymentMaker;
    const result = await paymentMaker.makePayment(
      [
        {
          chain: "base",
          currency: "USDC",
          address: params.destination,
          amount: new BigNumber(params.amount),
        },
      ],
      params.memo ?? "",
    );

    if (!result) {
      throw new Error("CdpBaseSepoliaAccount: payment execution returned no result");
    }

    return {
      protocol: "atxp",
      credential: JSON.stringify({
        transactionId: result.transactionId,
        chain: result.chain,
        currency: result.currency,
      }),
    };
  }
}
