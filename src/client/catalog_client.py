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
