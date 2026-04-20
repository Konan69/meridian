import { BigNumber } from "bignumber.js";
import {
  ConsoleLogger,
  type Account,
  type AccountId,
  type AuthorizeParams,
  type AuthorizeResult,
  type Currency,
  type Destination,
  type Logger,
  type PaymentIdentifier,
  type PaymentMaker,
  type Source,
} from "@atxp/common";
import { UnsupportedCurrencyError, getPolygonUSDCAddress } from "@atxp/client";
import { createWalletClient, encodeFunctionData, http, publicActions } from "viem";
import { polygon, polygonAmoy } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";
import type { PrivateKeyAccount } from "viem/accounts";

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
  {
    constant: true,
    inputs: [
      {
        name: "_owner",
        type: "address",
      },
    ],
    name: "balanceOf",
    outputs: [
      {
        name: "balance",
        type: "uint256",
      },
    ],
    payable: false,
    stateMutability: "view",
    type: "function",
  },
] as const;

function toBase64Url(data: string): string {
  const base64 =
    typeof Buffer !== "undefined" ? Buffer.from(data).toString("base64") : btoa(data);
  return base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

class PolygonCompatPaymentMaker implements PaymentMaker {
  private readonly signingClient: ReturnType<typeof createWalletClient> &
    ReturnType<typeof publicActions>;
  private readonly logger: Logger;
  private readonly networkName: "polygon" | "polygon_amoy";

  constructor(
    private readonly walletClient: ReturnType<typeof createWalletClient>,
    private readonly account: PrivateKeyAccount,
    private readonly chainId: number,
    logger?: Logger,
  ) {
    this.signingClient = this.walletClient.extend(publicActions);
    this.logger = logger ?? new ConsoleLogger();
    this.networkName = this.chainId === 137 ? "polygon" : "polygon_amoy";
  }

  getSourceAddress(_params: {
    amount: BigNumber;
    currency: Currency;
    receiver: string;
    memo: string;
  }): string {
    return this.account.address;
  }

  async generateJWT(params: {
    paymentRequestId: string;
    codeChallenge: string;
    accountId?: AccountId | null;
  }): Promise<string> {
    const headerObj = { alg: "ES256K" };
    const payloadObj = {
      sub: this.account.address,
      iss: "accounts.atxp.ai",
      aud: "https://auth.atxp.ai",
      iat: Math.floor(Date.now() / 1000),
      exp: Math.floor(Date.now() / 1000) + 60 * 60,
      ...(params.codeChallenge ? { code_challenge: params.codeChallenge } : {}),
      ...(params.paymentRequestId ? { payment_request_id: params.paymentRequestId } : {}),
      ...(params.accountId ? { account_id: params.accountId } : {}),
    };
    const header = toBase64Url(JSON.stringify(headerObj));
    const payload = toBase64Url(JSON.stringify(payloadObj));
    const message = `${header}.${payload}`;
    const messageBytes =
      typeof Buffer !== "undefined"
        ? Buffer.from(message, "utf8")
        : new TextEncoder().encode(message);
    const signResult = await this.signingClient.signMessage({
      account: this.account,
      message: { raw: messageBytes },
    });
    const signature = toBase64Url(signResult);
    return `${header}.${payload}.${signature}`;
  }

  async makePayment(
    destinations: Destination[],
    _memo: string,
    _paymentRequestId?: string,
  ): Promise<PaymentIdentifier | null> {
    this.logger.info(`Making payment with ${destinations.length} destination(s)`);
    const polygonDestinations = destinations.filter(
      (destination) =>
        destination.chain === this.networkName ||
        (this.networkName === "polygon_amoy" && destination.chain === "polygon"),
    );
    if (polygonDestinations.length === 0) {
      this.logger.debug(
        `PolygonCompatPaymentMaker: No ${this.networkName} destinations found, cannot handle payment`,
      );
      return null;
    }

    const destination = polygonDestinations[0];
    if (destination.currency !== "USDC") {
      throw new UnsupportedCurrencyError(destination.currency, this.networkName, ["USDC"]);
    }

    const usdcAddress = getPolygonUSDCAddress(this.chainId) as `0x${string}`;
    const amountInSmallestUnit = destination.amount.multipliedBy(10 ** USDC_DECIMALS);
    this.logger.info(`Transferring ${destination.amount.toString()} USDC to ${destination.address}`);
    this.logger.info(`Amount in smallest unit: ${amountInSmallestUnit.toString()}`);

    const balance = await this.signingClient.readContract({
      address: usdcAddress,
      abi: ERC20_ABI,
      functionName: "balanceOf",
      args: [this.account.address],
    }) as bigint;
    this.logger.info(`Current USDC balance: ${balance.toString()}`);
    if (balance < BigInt(amountInSmallestUnit.toFixed(0))) {
      throw new Error(
        `Insufficient USDC balance. Have: ${balance.toString()}, Need: ${amountInSmallestUnit.toString()}`,
      );
    }

    const data = encodeFunctionData({
      abi: ERC20_ABI,
      functionName: "transfer",
      args: [destination.address as `0x${string}`, BigInt(amountInSmallestUnit.toFixed(0))],
    });

    const hash = await this.signingClient.sendTransaction({
      account: this.account,
      to: usdcAddress,
      data,
      chain: this.walletClient.chain,
    });
    this.logger.info(`Transaction sent: ${hash}`);

    const receipt = await this.signingClient.waitForTransactionReceipt({ hash });
    if (receipt.status !== "success") {
      throw new Error(`Transaction failed: ${hash}`);
    }

    this.logger.info(`Payment successful! Transaction: ${hash}`);
    return {
      transactionId: hash,
      chain: "polygon",
      currency: "USDC",
    };
  }
}

export class PolygonAmoyAccount implements Account {
  readonly paymentMakers: PaymentMaker[];
  private readonly account: PrivateKeyAccount;
  private readonly walletClient: ReturnType<typeof createWalletClient>;
  private readonly networkName: "polygon" | "polygon_amoy";

  constructor(
    polygonRpcUrl: string,
    privateKey: string,
    private readonly chainId: number = 80002,
    logger?: Logger,
  ) {
    if (!polygonRpcUrl) throw new Error("Polygon RPC URL is required");
    if (!privateKey) throw new Error("Polygon private key is required");

    this.account = privateKeyToAccount(privateKey as `0x${string}`);
    const chain = this.chainId === 137 ? polygon : polygonAmoy;
    this.walletClient = createWalletClient({
      account: this.account,
      chain,
      transport: http(polygonRpcUrl),
    });
    this.networkName = this.chainId === 137 ? "polygon" : "polygon_amoy";
    this.paymentMakers = [
      new PolygonCompatPaymentMaker(this.walletClient, this.account, this.chainId, logger),
    ];
  }

  async getAccountId(): Promise<AccountId> {
    return `polygon:${this.account.address}` as AccountId;
  }

  async getSources(): Promise<Source[]> {
    return [
      {
        address: this.account.address,
        chain: this.networkName,
        walletType: "eoa",
      },
    ];
  }

  async createSpendPermission(_resourceUrl: string): Promise<string | null> {
    return null;
  }

  async authorize(params: AuthorizeParams): Promise<AuthorizeResult> {
    if (!params.protocols?.length) {
      throw new Error("PolygonAmoyAccount: protocols array must not be empty");
    }
    const protocol = params.protocols.find((candidate) => candidate === "atxp");
    if (!protocol) {
      throw new Error(
        `PolygonAmoyAccount only supports atxp payments, got: ${params.protocols.join(", ")}`,
      );
    }
    if (!params.amount) throw new Error("PolygonAmoyAccount: amount is required");
    if (!params.destination) throw new Error("PolygonAmoyAccount: destination is required");

    const destination: Destination = {
      chain: this.networkName,
      currency: "USDC",
      address: params.destination,
      amount: new BigNumber(params.amount),
    };

    const result = await this.paymentMakers[0].makePayment(
      [destination],
      params.memo ?? "",
    );
    if (!result) {
      throw new Error("PolygonAmoyAccount: payment execution returned no result");
    }

    return {
      protocol,
      credential: JSON.stringify(result),
    };
  }
}
