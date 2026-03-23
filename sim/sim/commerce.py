"""Commerce actions — agents interact with the Rust engine over HTTP."""

import json
import aiohttp
from typing import Optional
from .types import TransactionRecord, PROTOCOL_FEE_FORMULAS, Protocol


class CommerceClient:
    """HTTP client for the Meridian Rust commerce engine."""

    def __init__(self, engine_url: str = "http://localhost:4080"):
        self.engine_url = engine_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def health(self) -> bool:
        try:
            session = await self._get_session()
            async with session.get(f"{self.engine_url}/health") as resp:
                return resp.status == 200
        except Exception:
            return False

    async def get_products(self) -> list[dict]:
        session = await self._get_session()
        async with session.get(f"{self.engine_url}/products") as resp:
            return await resp.json()

    async def get_metrics(self) -> dict:
        session = await self._get_session()
        async with session.get(f"{self.engine_url}/metrics") as resp:
            return await resp.json()

    async def create_checkout(self, items: list[dict], protocol: str, agent_id: str) -> dict:
        session = await self._get_session()
        async with session.post(
            f"{self.engine_url}/checkout_sessions",
            json={"items": items, "protocol": protocol, "agent_id": agent_id},
        ) as resp:
            return await resp.json()

    async def update_checkout(
        self,
        session_id: str,
        fulfillment_address: Optional[dict] = None,
        selected_fulfillment_option_id: Optional[str] = None,
    ) -> dict:
        session = await self._get_session()
        body: dict = {}
        if fulfillment_address:
            body["fulfillment_address"] = fulfillment_address
        if selected_fulfillment_option_id:
            body["selected_fulfillment_option_id"] = selected_fulfillment_option_id
        async with session.post(
            f"{self.engine_url}/checkout_sessions/{session_id}",
            json=body,
        ) as resp:
            return await resp.json()

    async def complete_checkout(self, session_id: str, payment_token: str, protocol: str) -> dict:
        session = await self._get_session()
        async with session.post(
            f"{self.engine_url}/checkout_sessions/{session_id}/complete",
            json={"payment_token": payment_token, "protocol": protocol},
        ) as resp:
            data = await resp.json()
            data["_status"] = resp.status
            return data

    async def full_purchase(
        self,
        agent_id: str,
        product_id: str,
        quantity: int,
        protocol: str,
        round_num: int,
        product_name: str = "",
        needs_shipping: bool = True,
        agent_address: Optional[dict] = None,
    ) -> TransactionRecord:
        """Execute a full checkout flow and return a transaction record."""
        try:
            # 1. Create session
            checkout = await self.create_checkout(
                items=[{"id": product_id, "quantity": quantity}],
                protocol=protocol,
                agent_id=agent_id,
            )

            if "id" not in checkout:
                return TransactionRecord(
                    round_num=round_num, agent_id=agent_id, protocol=protocol,
                    product_id=product_id, product_name=product_name,
                    amount=0, fee=0, settlement_ms=0, success=False,
                    error=checkout.get("message", str(checkout)),
                )

            session_id = checkout["id"]

            # 2. Update with address if shipping needed
            if needs_shipping and agent_address:
                await self.update_checkout(
                    session_id=session_id,
                    fulfillment_address=agent_address,
                    selected_fulfillment_option_id="ship_standard",
                )

            # 3. Complete checkout
            token = f"token_{protocol}_{agent_id}_{round_num}"
            result = await self.complete_checkout(session_id, token, protocol)

            if result.get("status") == "completed":
                # Extract total
                total = 0
                for t in result.get("totals", []):
                    if t.get("type") == "total":
                        total = t["amount"]

                # Extract fee and settlement from payment_result message
                fee = 0
                settlement_ms = 0.0
                for msg in result.get("messages", []):
                    if msg.get("type") == "payment_result":
                        try:
                            payment_data = json.loads(msg["content"])
                            fee = payment_data.get("fee_cents", 0)
                            # execution_us is REAL measured time from the engine
                            settlement_ms = payment_data.get("execution_us", 0) / 1000.0
                        except (json.JSONDecodeError, KeyError):
                            proto_enum = Protocol(protocol)
                            fee = PROTOCOL_FEE_FORMULAS.get(proto_enum, lambda a: 0)(total)

                return TransactionRecord(
                    round_num=round_num, agent_id=agent_id, protocol=protocol,
                    product_id=product_id, product_name=product_name,
                    amount=total, fee=fee, settlement_ms=settlement_ms,
                    success=True, session_id=session_id,
                    order_id=result.get("order", {}).get("id"),
                )
            else:
                return TransactionRecord(
                    round_num=round_num, agent_id=agent_id, protocol=protocol,
                    product_id=product_id, product_name=product_name,
                    amount=0, fee=0, settlement_ms=0, success=False,
                    error=result.get("message", "checkout failed"),
                )

        except Exception as e:
            return TransactionRecord(
                round_num=round_num, agent_id=agent_id, protocol=protocol,
                product_id=product_id, product_name=product_name,
                amount=0, fee=0, settlement_ms=0, success=False,
                error=str(e),
            )
