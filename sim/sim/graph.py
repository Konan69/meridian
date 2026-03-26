"""Knowledge graph builder using Graphiti + Kuzu (embedded, no server needed)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from graphiti_core import Graphiti
from graphiti_core.driver.kuzu_driver import KuzuDriver
from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client import LLMConfig, OpenAIClient
from graphiti_core.cross_encoder import OpenAIRerankerClient
from graphiti_core.nodes import EpisodeType

logger = logging.getLogger(__name__)

# LLM / embedding endpoint (OpenAI-compatible)
_BASE_URL = "https://opencode.ai/zen/v1"
_MODEL = "minimax-m2.5"


class CommerceGraphBuilder:
    """Builds a knowledge graph of commerce simulation events using Graphiti + Kuzu."""

    def __init__(self, db_path: str = "./meridian_graph"):
        self.db_path = db_path
        self.graphiti: Graphiti | None = None
        self.driver: KuzuDriver | None = None
        self._initialized = False

    async def initialize(self):
        """Set up the Graphiti client with Kuzu driver and configure the commerce ontology."""
        api_key = os.environ.get("OPENCODE_API_KEY", "")

        # Kuzu embedded driver — no Neo4j server needed
        self.driver = KuzuDriver(db=self.db_path)

        # LLM client for entity extraction
        llm_config = LLMConfig(
            api_key=api_key or "no-key",
            base_url=_BASE_URL,
            model=_MODEL,
            small_model=_MODEL,
        )
        llm_client = OpenAIClient(config=llm_config)

        # Embedder — use the same OpenAI-compatible endpoint
        embedder_config = OpenAIEmbedderConfig(
            api_key=api_key or "no-key",
            base_url=_BASE_URL,
        )
        embedder = OpenAIEmbedder(config=embedder_config)

        # Cross-encoder / reranker
        reranker = OpenAIRerankerClient(config=llm_config)

        self.graphiti = Graphiti(
            graph_driver=self.driver,
            llm_client=llm_client,
            embedder=embedder,
            cross_encoder=reranker,
            store_raw_episode_content=True,
        )

        # Build indices
        try:
            await self.driver.setup_schema()
            await self.graphiti.build_indices_and_constraints()
        except Exception as exc:
            logger.warning("Graph index setup failed (non-fatal): %s", exc)

        self._initialized = True
        logger.info("CommerceGraphBuilder initialized at %s", self.db_path)

    # ------------------------------------------------------------------
    # Entity helpers
    # ------------------------------------------------------------------

    async def add_product(self, product: dict):
        """Add a product entity to the graph."""
        name = product.get("name", "unknown")
        price_dollars = product.get("base_price", 0) / 100
        category = product.get("category", "general")
        body = (
            f"Product '{name}' is available for ${price_dollars:.2f}. "
            f"Category: {category}. ID: {product.get('id', '')}."
        )
        await self._add_episode(
            name=f"product_{product.get('id', name)}",
            body=body,
            source="product_catalog",
        )

    async def add_agent(self, agent_profile: dict):
        """Add a buyer agent entity to the graph."""
        agent_id = agent_profile.get("agent_id", "unknown")
        name = agent_profile.get("name", agent_id)
        budget_dollars = agent_profile.get("budget", 0) / 100
        categories = ", ".join(agent_profile.get("preferred_categories", [])) or "any"
        body = (
            f"Agent '{name}' (ID: {agent_id}) is a buyer with a budget of "
            f"${budget_dollars:.2f}. Price sensitivity: {agent_profile.get('price_sensitivity', 0.5):.1f}. "
            f"Preferred categories: {categories}."
        )
        await self._add_episode(
            name=f"agent_{agent_id}",
            body=body,
            source="agent_registry",
        )

    async def add_merchant(self, name: str, protocol: str):
        """Add a merchant entity to the graph."""
        body = f"Merchant '{name}' supports the {protocol} payment protocol."
        await self._add_episode(
            name=f"merchant_{name}_{protocol}",
            body=body,
            source="merchant_registry",
        )

    # ------------------------------------------------------------------
    # Transaction / round recording
    # ------------------------------------------------------------------

    async def record_transaction(self, tx: dict):
        """Record a purchase transaction as an episode in the graph.

        Creates edges: agent PURCHASED product, agent USED_PROTOCOL protocol,
        agent BOUGHT_FROM merchant.
        """
        agent = tx.get("agent_id", "unknown")
        product = tx.get("product_name", "unknown")
        protocol = tx.get("protocol", "unknown")
        amount_dollars = tx.get("amount_cents", 0) / 100
        fee_dollars = tx.get("fee_cents", 0) / 100
        round_num = tx.get("round_num", 0)
        success = tx.get("success", True)
        status = "successfully purchased" if success else "failed to purchase"

        body = (
            f"In round {round_num}, agent {agent} {status} '{product}' "
            f"for ${amount_dollars:.2f} (fee ${fee_dollars:.2f}) "
            f"using the {protocol} protocol."
        )
        await self._add_episode(
            name=f"tx_r{round_num}_{agent}_{protocol}",
            body=body,
            source="simulation_transactions",
            group_id=f"round_{round_num}",
        )

    async def record_round(self, round_summary: dict):
        """Record a round summary as an episode."""
        rn = round_summary.get("round_num", 0)
        volume_dollars = round_summary.get("total_volume", 0) / 100
        fees_dollars = round_summary.get("total_fees", 0) / 100
        success = round_summary.get("success_count", 0)
        fail = round_summary.get("fail_count", 0)
        active = round_summary.get("active_agents", 0)

        body = (
            f"Round {rn} completed: {active} active agents, "
            f"{success} successful and {fail} failed transactions, "
            f"total volume ${volume_dollars:.2f}, total fees ${fees_dollars:.2f}."
        )
        await self._add_episode(
            name=f"round_summary_{rn}",
            body=body,
            source="simulation_rounds",
            group_id=f"round_{rn}",
        )

    # ------------------------------------------------------------------
    # Search / query
    # ------------------------------------------------------------------

    async def search(self, query: str, limit: int = 10) -> list:
        """Search the graph for relevant facts."""
        if not self.graphiti:
            return []
        try:
            edges = await self.graphiti.search(query=query, num_results=limit)
            return [
                {
                    "fact": e.fact if hasattr(e, "fact") else str(e),
                    "source": getattr(e, "source_node_name", None),
                    "target": getattr(e, "target_node_name", None),
                    "relation": getattr(e, "name", None),
                    "created_at": str(getattr(e, "created_at", "")),
                }
                for e in edges
            ]
        except Exception as exc:
            logger.warning("Graph search failed: %s", exc)
            return []

    async def get_all_nodes(self) -> list[dict]:
        """Get all nodes for visualization (id, name, type)."""
        if not self.driver:
            return []
        try:
            results, _, _ = await self.driver.execute_query(
                "MATCH (n) RETURN n.uuid AS id, n.name AS name, label(n) AS type"
            )
            return [
                {"id": r.get("id", ""), "name": r.get("name", ""), "type": r.get("type", "")}
                for r in results
            ]
        except Exception as exc:
            logger.warning("get_all_nodes failed: %s", exc)
            return []

    async def get_all_edges(self) -> list[dict]:
        """Get all edges for visualization (source, target, label)."""
        if not self.driver:
            return []
        try:
            results, _, _ = await self.driver.execute_query(
                "MATCH (a)-[r]->(b) "
                "RETURN a.name AS source, b.name AS target, type(r) AS label"
            )
            return [
                {
                    "source": r.get("source", ""),
                    "target": r.get("target", ""),
                    "label": r.get("label", ""),
                }
                for r in results
            ]
        except Exception as exc:
            logger.warning("get_all_edges failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self):
        """Clean up."""
        if self.graphiti:
            try:
                await self.graphiti.close()
            except Exception as exc:
                logger.debug("Graphiti close error (ignored): %s", exc)
        self.graphiti = None
        self.driver = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _add_episode(
        self,
        name: str,
        body: str,
        source: str,
        group_id: str | None = None,
    ):
        """Add an episode to the graph, handling LLM API failures gracefully."""
        if not self.graphiti:
            return
        try:
            await self.graphiti.add_episode(
                name=name,
                episode_body=body,
                source_description=source,
                reference_time=datetime.now(timezone.utc),
                source=EpisodeType.text,
                group_id=group_id or "meridian_sim",
            )
        except Exception as exc:
            # LLM API may be unavailable — log but don't crash the simulation
            logger.warning("Failed to add episode '%s': %s", name, exc)
