"""Live memory updater — records simulation events to the knowledge graph in real-time."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .graph import CommerceGraphBuilder

logger = logging.getLogger(__name__)


class MemoryUpdater:
    """Buffers simulation events and flushes them to the knowledge graph in batches."""

    BATCH_SIZE = 5

    def __init__(self, graph: CommerceGraphBuilder):
        self.graph = graph
        self.buffer: list[dict] = []

    async def record_purchase(
        self,
        agent_id: str,
        product_name: str,
        protocol: str,
        amount_cents: int,
        round_num: int,
    ):
        """Buffer a purchase event. Flush to graph when BATCH_SIZE reached."""
        self.buffer.append({
            "kind": "purchase",
            "agent_id": agent_id,
            "product_name": product_name,
            "protocol": protocol,
            "amount_cents": amount_cents,
            "fee_cents": 0,
            "round_num": round_num,
            "success": True,
        })
        if len(self.buffer) >= self.BATCH_SIZE:
            await self.flush()

    async def record_failure(
        self,
        agent_id: str,
        protocol: str,
        error: str,
        round_num: int,
    ):
        """Record a failed transaction."""
        self.buffer.append({
            "kind": "failure",
            "agent_id": agent_id,
            "product_name": "",
            "protocol": protocol,
            "amount_cents": 0,
            "fee_cents": 0,
            "round_num": round_num,
            "success": False,
            "error": error,
        })
        if len(self.buffer) >= self.BATCH_SIZE:
            await self.flush()

    async def flush(self):
        """Flush all buffered events to the graph as episodes."""
        if not self.buffer:
            return

        to_flush = self.buffer[:]
        self.buffer.clear()

        for event in to_flush:
            try:
                if event["kind"] == "purchase":
                    await self.graph.record_transaction(event)
                elif event["kind"] == "failure":
                    await self.graph.record_transaction(event)
            except Exception as exc:
                logger.warning(
                    "Memory flush failed for %s/%s: %s",
                    event.get("agent_id"),
                    event.get("kind"),
                    exc,
                )

    async def close(self):
        """Flush remaining and close."""
        await self.flush()
