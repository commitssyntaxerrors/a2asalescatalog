# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Federated catalog network — peer discovery and cross-catalog search.

Multiple catalog servers can peer with each other and cross-list inventory.
Like DNS for product catalogs: no single point of failure, no centralized
chokepoint.
"""

from __future__ import annotations

import json
from typing import Any

from src.server.store import CatalogStore


class FederationManager:
    """Manages federation peers and cross-catalog fan-out."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def add_peer(self, url: str, name: str, categories: list[str],
                 items_count: int = 0) -> None:
        """Register a federation peer."""
        self._store.upsert_peer(url, name, categories, items_count)

    def list_peers(self) -> dict[str, Any]:
        """Return compact-encoded peer list."""
        peers = self._store.list_peers()
        rows = []
        for p in peers:
            cats = json.loads(p["categories"]) if isinstance(p["categories"], str) else p["categories"]
            rows.append([p["url"], p["name"], cats, p["items_count"], p["status"]])
        return {
            "fields": ["url", "name", "categories", "items_count", "status"],
            "peers": rows,
        }

    def fan_out_search(self, query: str, category: str | None = None) -> list[dict[str, Any]]:
        """Fan-out search to peers (stub — in production, HTTP fan-out with timeouts).

        For MVP, returns empty — real implementation would:
        1. Filter peers by category match
        2. Send parallel A2A tasks/send requests
        3. Merge results with local, deduplicate, re-rank
        """
        # Stub: peer search not implemented in MVP
        return []
