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
import { USDC_CONTRACT_ADDRESS_BASE_SEPOLIA } from "@atxp/base";
import { createWalletClient, encodeFunctionData, http, parseEther, publicActions } from "viem";
import { baseSepolia } from "viem/chains";
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
] as const;

class BaseSepoliaPaymentMaker implements PaymentMaker {
  constructor(
    private readonly walletClient: ReturnType<typeof createWalletClient>,
    private readonly account: PrivateKeyAccount,
  ) {}

  getSourceAddress(_params: {
    amount: BigNumber;
    currency: Currency;
    receiver: string;
    memo: string;
  }): string {
    return this.account.address;
  }

  async generateJWT(): Promise<string> {
    throw new Error("BaseSepoliaPaymentMaker does not implement ATXP JWT generation");
  }

  async makePayment(
    destinations: Destination[],
    _memo: string,
    _paymentRequestId?: string,
  ): Promise<PaymentIdentifier | null> {
    const baseDestinations = destinations.filter((d) => d.chain === "base_sepolia");
    if (baseDestinations.length === 0) {
      return null;
    }

    const destination = baseDestinations[0];
    if (destination.currency.toUpperCase() !== "USDC") {
      throw new UnsupportedCurrencyError(destination.currency, "base_sepolia", ["USDC"]);
    }

    const amountInUnits = BigInt(
      destination.amount.multipliedBy(10 ** USDC_DECIMALS).toFixed(0),
    );

    const hash = await this.walletClient
      .extend(publicActions)
      .sendTransaction({
        chain: baseSepolia,
        account: this.account,
        to: USDC_CONTRACT_ADDRESS_BASE_SEPOLIA,
        data: encodeFunctionData({
          abi: ERC20_ABI,
          functionName: "transfer",
          args: [destination.address as `0x${string}`, amountInUnits],
        }),
        value: parseEther("0"),
      });

    return {
      transactionId: hash,
      chain: "base_sepolia",
      currency: "USDC",
    };
  }
}

export class BaseSepoliaAccount implements Account {
  readonly usesAccountsAuthorize = false;
  private readonly account: PrivateKeyAccount;
  private readonly walletClient: ReturnType<typeof createWalletClient>;
  readonly paymentMakers: PaymentMaker[];
  private readonly accountId: AccountId;

  constructor(baseRpcUrl: string, sourceSecretKey: string) {
    if (!baseRpcUrl) {
      throw new Error("Base Sepolia RPC URL is required");
    }
    if (!sourceSecretKey) {
      throw new Error("Base Sepolia private key is required");
    }

    this.account = privateKeyToAccount(sourceSecretKey as `0x${string}`);
    this.walletClient = createWalletClient({
      account: this.account,
      chain: baseSepolia,
      transport: http(baseRpcUrl),
    });
    this.accountId = `base_sepolia:${this.account.address}`;
    this.paymentMakers = [new BaseSepoliaPaymentMaker(this.walletClient, this.account)];
  }

  async getAccountId(): Promise<AccountId> {
    return this.accountId;
  }

  async getSources(): Promise<Source[]> {
    return [
      {
        address: this.account.address,
        chain: "base_sepolia",
        walletType: "eoa",
      },
    ];
  }

  async createSpendPermission(_resourceUrl: string): Promise<string | null> {
    return null;
  }

  async authorize(params: AuthorizeParams): Promise<AuthorizeResult> {
    if (!params.protocols || params.protocols.length === 0) {
      throw new Error("BaseSepoliaAccount: protocols array must not be empty");
    }

    const protocol = params.protocols.find((candidate) => candidate === "atxp");
    if (!protocol) {
      throw new Error(
        `BaseSepoliaAccount only supports atxp payments, got: ${params.protocols.join(", ")}`,
      );
    }
    if (!params.amount) {
      throw new Error("BaseSepoliaAccount: amount is required for ATXP authorize");
    }
    if (!params.destination) {
      throw new Error("BaseSepoliaAccount: destination is required for ATXP authorize");
    }

    const destination: Destination = {
      chain: "base_sepolia",
      currency: "USDC",
      address: params.destination,
      amount: new BigNumber(params.amount),
    };

    const result = await this.paymentMakers[0].makePayment(
      [destination],
      params.memo ?? "",
    );
    if (!result) {
      throw new Error("BaseSepoliaAccount: payment execution returned no result");
    }

    return {
      protocol,
      credential: JSON.stringify({
        transactionId: result.transactionId,
        chain: result.chain,
        currency: result.currency,
      }),
    };
  }
}
