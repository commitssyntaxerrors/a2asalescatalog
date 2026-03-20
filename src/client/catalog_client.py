# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""A2A Sales Catalog — lightweight client SDK.

Allows any agent orchestrator to query the catalog with a single function call.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


class CatalogClient:
    """Minimal A2A client for the Sales Catalog server."""

    def __init__(self, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    # ------------------------------------------------------------------
    # Public SDK methods
    # ------------------------------------------------------------------

    def agent_card(self) -> dict[str, Any]:
        """Fetch the server's A2A Agent Card."""
        return self._get("/.well-known/agent.json")

    def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        category: str | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        sort: str = "relevance",
        vendor: str | None = None,
    ) -> dict[str, Any]:
        """Search the catalog — returns compact tuple response."""
        data: dict[str, Any] = {"skill": "catalog.search", "q": query, "max": max_results}
        if category:
            data["cat"] = category
        if price_min is not None:
            data["price_min"] = price_min
        if price_max is not None:
            data["price_max"] = price_max
        if sort != "relevance":
            data["sort"] = sort
        if vendor:
            data["vendor"] = vendor
        return self._send_task(data)

    def lookup(self, item_id: str) -> dict[str, Any]:
        """Get full details for a single item."""
        return self._send_task({"skill": "catalog.lookup", "id": item_id})

    def categories(self, parent: str | None = None) -> dict[str, Any]:
        """List categories."""
        data: dict[str, Any] = {"skill": "catalog.categories"}
        if parent is not None:
            data["parent"] = parent
        return self._send_task(data)

    def compare(self, ids: list[str]) -> dict[str, Any]:
        """Compare items side by side."""
        return self._send_task({"skill": "catalog.compare", "ids": ids})

    def negotiate(
        self,
        item_id: str,
        offer_cents: int,
        session_id: str | None = None,
        message: str = "",
    ) -> dict[str, Any]:
        """Negotiate a price for an item."""
        data: dict[str, Any] = {
            "skill": "catalog.negotiate",
            "item_id": item_id,
            "offer_cents": offer_cents,
        }
        if session_id:
            data["session_id"] = session_id
        if message:
            data["message"] = message
        return self._send_task(data)

    def purchase(
        self,
        item_id: str,
        payment_token: str,
        *,
        quantity: int = 1,
        negotiate_session_id: str | None = None,
        shipping_method: str = "standard",
        address_token: str = "",
    ) -> dict[str, Any]:
        """Complete a purchase."""
        data: dict[str, Any] = {
            "skill": "catalog.purchase",
            "item_id": item_id,
            "quantity": quantity,
            "payment_token": payment_token,
        }
        if negotiate_session_id:
            data["negotiate_session_id"] = negotiate_session_id
        if shipping_method or address_token:
            data["shipping"] = {"method": shipping_method, "address_token": address_token}
        return self._send_task(data)

    def agent_profile(self) -> dict[str, Any]:
        """Get the authenticated agent's profile and interest scores."""
        return self._send_task({"skill": "catalog.agent_profile"})

    def reputation(self) -> dict[str, Any]:
        """Get the authenticated agent's reputation score and tier."""
        return self._send_task({"skill": "catalog.reputation"})

    def embed(
        self,
        ids: list[str] | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        """Get semantic embeddings for items or a query."""
        data: dict[str, Any] = {"skill": "catalog.embed"}
        if ids:
            data["ids"] = ids
        if query:
            data["query"] = query
        return self._send_task(data)

    def peers(self) -> dict[str, Any]:
        """List federated catalog peers."""
        return self._send_task({"skill": "catalog.peers"})

    def vendor_analytics(self, vendor_id: str, period: str = "7d") -> dict[str, Any]:
        """Get vendor analytics report."""
        return self._send_task({
            "skill": "catalog.vendor_analytics",
            "vendor_id": vendor_id,
            "period": period,
        })

    def retarget(self, *, max_offers: int = 5) -> dict[str, Any]:
        """Get retargeting offers for items you viewed but didn't buy."""
        return self._send_task({"skill": "catalog.retarget", "max": max_offers})

    def affiliate(self, *, action: str = "status",
                  vendor_id: str = "") -> dict[str, Any]:
        """Manage affiliate referrals. action: 'status' or 'create'."""
        data: dict[str, Any] = {"skill": "catalog.affiliate", "action": action}
        if vendor_id:
            data["vendor_id"] = vendor_id
        return self._send_task(data)

    def auction(self, query: str, *, slots: int = 2,
                intent_tier: str = "browse") -> dict[str, Any]:
        """Run a real-time bidding auction for ad slots."""
        return self._send_task({
            "skill": "catalog.auction",
            "q": query, "slots": slots, "intent_tier": intent_tier,
        })

    def promotions(self, *, vendor_id: str = "",
                   item_id: str = "") -> dict[str, Any]:
        """Discover active promotions and deals."""
        data: dict[str, Any] = {"skill": "catalog.promotions"}
        if vendor_id:
            data["vendor_id"] = vendor_id
        if item_id:
            data["item_id"] = item_id
        return self._send_task(data)

    def validate_promo(self, code: str, item_id: str,
                       price_cents: int) -> dict[str, Any]:
        """Validate a promo code for a specific item and price."""
        return self._send_task({
            "skill": "catalog.promotions",
            "action": "validate",
            "code": code,
            "item_id": item_id,
            "price_cents": price_cents,
        })

    def audience(self, *, action: str = "classify") -> dict[str, Any]:
        """Get or classify agent audience segments."""
        return self._send_task({"skill": "catalog.audience", "action": action})

    def attribution(self, *, campaign_id: str = "",
                    agent_id: str = "",
                    item_id: str = "") -> dict[str, Any]:
        """Get conversion attribution data."""
        data: dict[str, Any] = {"skill": "catalog.attribution"}
        if campaign_id:
            data["action"] = "campaign"
            data["campaign_id"] = campaign_id
        elif agent_id:
            data["action"] = "journey"
            data["agent_id"] = agent_id
            if item_id:
                data["item_id"] = item_id
        return self._send_task(data)

    def cross_sell(self, item_id: str, *, max_recs: int = 3) -> dict[str, Any]:
        """Get cross-sell/upsell recommendations for an item."""
        return self._send_task({
            "skill": "catalog.cross_sell", "item_id": item_id, "max": max_recs,
        })

    def display_ads(self, *, category: str = "",
                    item_id: str = "", max_ads: int = 2) -> dict[str, Any]:
        """Get display/banner ads for a category or item context."""
        data: dict[str, Any] = {"skill": "catalog.display_ads", "max": max_ads}
        if category:
            data["cat"] = category
        if item_id:
            data["item_id"] = item_id
        return self._send_task(data)

    def ab_results(self, ab_group: str) -> dict[str, Any]:
        """Get A/B test results for a test group."""
        return self._send_task({"skill": "catalog.ab_results", "ab_group": ab_group})

    # ------------------------------------------------------------------
    # Helpers to decode compact responses
    # ------------------------------------------------------------------

    @staticmethod
    def tuples_to_dicts(fields: list[str], rows: list[list]) -> list[dict[str, Any]]:
        """Convert compact [fields, items/rows] to a list of dicts."""
        return [dict(zip(fields, row)) for row in rows]

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _send_task(self, skill_data: dict[str, Any]) -> dict[str, Any]:
        """Send a tasks/send JSON-RPC request."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "id": str(uuid.uuid4()),
                "message": {
                    "role": "user",
                    "parts": [{"type": "data", "data": skill_data}],
                },
            },
        }
        resp = self._post("/a2a", payload)
        # Extract result data from A2A response
        result = resp.get("result", {})
        status = result.get("status", {})
        if status.get("state") == "failed":
            raise RuntimeError(f"Catalog error: {status.get('message', 'unknown')}")
        artifacts = result.get("artifacts", [])
        if artifacts:
            parts = artifacts[0].get("parts", [])
            if parts:
                return parts[0].get("data", {})
        return {}

    def _post(self, path: str, body: dict) -> dict[str, Any]:
        data = json.dumps(body).encode()
        req = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=self._headers("application/json"),
            method="POST",
        )
        with urlopen(req) as resp:  # noqa: S310 — URL is constructed from user-provided base_url
            return json.loads(resp.read())

    def _get(self, path: str) -> dict[str, Any]:
        req = Request(
            f"{self.base_url}{path}",
            headers=self._headers(),
            method="GET",
        )
        with urlopen(req) as resp:  # noqa: S310
            return json.loads(resp.read())

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        h: dict[str, str] = {}
        if content_type:
            h["Content-Type"] = content_type
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h
