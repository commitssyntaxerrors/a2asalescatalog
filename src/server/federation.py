# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Federated catalog network — peer discovery and cross-catalog search.

Multiple catalog servers can peer with each other and cross-list inventory.
Like DNS for product catalogs: no single point of failure, no centralized
chokepoint.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

from src.server.store import CatalogStore

# Default configuration
DEFAULT_PEER_TIMEOUT_SECS = 2.0
DEFAULT_MIN_RESULTS = 5
_MAX_PEERS = 20  # safety cap on fan-out breadth


class FederationManager:
    """Manages federation peers and cross-catalog fan-out."""

    def __init__(self, store: CatalogStore,
                 peer_timeout: float = DEFAULT_PEER_TIMEOUT_SECS) -> None:
        self._store = store
        self._peer_timeout = peer_timeout
        # Optional HTTP client — injected for testing / production
        self._http_client: Any = None

    def set_http_client(self, client: Any) -> None:
        """Inject an HTTP client (e.g. ``httpx.Client``) for peer calls."""
        self._http_client = client

    def add_peer(self, url: str, name: str, categories: list[str],
                 items_count: int = 0) -> None:
        """Register a federation peer."""
        self._store.upsert_peer(url, name, categories, items_count)

    def remove_peer(self, url: str) -> None:
        """Unregister a federation peer."""
        self._store.remove_peer(url)

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

    # ------------------------------------------------------------------
    # Peer health check
    # ------------------------------------------------------------------

    def check_peer_health(self, peer_url: str) -> bool:
        """Verify that a peer is reachable by fetching its agent card."""
        client = self._http_client
        if client is None:
            return False
        try:
            parsed = urlparse(peer_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            resp = client.get(
                f"{base}/.well-known/agent.json",
                timeout=self._peer_timeout,
            )
            return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Fan-out search
    # ------------------------------------------------------------------

    def fan_out_search(
        self,
        query: str,
        category: str | None = None,
        *,
        min_results: int = DEFAULT_MIN_RESULTS,
        local_results: list[dict[str, Any]] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Fan query out to registered peers in parallel, merge & deduplicate.

        Parameters
        ----------
        query:
            The search query string.
        category:
            Optional category filter forwarded to peers.
        min_results:
            If *local_results* already has at least this many items the
            fan-out is skipped entirely.
        local_results:
            Items already returned by the local catalog.  Used for the
            min-results check and deduplication.
        limit:
            Maximum total results to return (local + peer combined).

        Returns a list of result dicts.  Each result includes a ``source``
        key indicating ``"local"`` or the peer URL.
        """
        local = local_results or []

        # Tag local results
        for item in local:
            item.setdefault("source", "local")

        # If we already have enough locally, skip fan-out
        if len(local) >= min_results:
            return local[:limit]

        client = self._http_client
        if client is None:
            return local[:limit]

        peers = self._store.list_peers()
        if not peers:
            return local[:limit]

        # Filter peers by category overlap when possible
        candidates = []
        for p in peers:
            if p.get("status") != "online":
                continue
            if category:
                cats = json.loads(p["categories"]) if isinstance(p["categories"], str) else p["categories"]
                if cats and category not in cats:
                    continue
            candidates.append(p)

        candidates = candidates[:_MAX_PEERS]
        if not candidates:
            return local[:limit]

        # Build a set of local IDs for dedup
        seen_ids: set[str] = set()
        for item in local:
            if item.get("id"):
                seen_ids.add(item["id"])

        peer_items: list[dict[str, Any]] = []

        def _query_peer(peer: dict) -> list[dict[str, Any]]:
            """Send a catalog.search to a single peer."""
            peer_url = peer["url"]
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tasks/send",
                "params": {
                    "id": f"fan-out-{int(time.time()*1000)}",
                    "message": {
                        "role": "user",
                        "parts": [{
                            "type": "data",
                            "data": {
                                "skill": "catalog.search",
                                "q": query,
                                **({"cat": category} if category else {}),
                                "max": limit,
                            },
                        }],
                    },
                },
            }
            try:
                resp = client.post(
                    peer_url,
                    json=payload,
                    timeout=self._peer_timeout,
                )
                if resp.status_code != 200:
                    self._store.update_peer_status(peer_url, "degraded")
                    return []
                body = resp.json()
                result = body.get("result", {})
                if result.get("status", {}).get("state") != "completed":
                    return []
                artifacts = result.get("artifacts", [])
                if not artifacts:
                    return []
                data = artifacts[0].get("parts", [{}])[0].get("data", {})
                fields = data.get("fields", [])
                items_raw = data.get("items", [])
                # Convert CAI tuples back to dicts
                converted = []
                for row in items_raw:
                    item = {}
                    for i, f in enumerate(fields):
                        if i < len(row):
                            item[f] = row[i]
                    item["source"] = peer_url
                    converted.append(item)
                return converted
            except Exception:
                self._store.update_peer_status(peer_url, "offline")
                return []

        # Parallel fan-out with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(candidates), 5)) as pool:
            futures = {pool.submit(_query_peer, p): p for p in candidates}
            try:
                for fut in as_completed(futures, timeout=self._peer_timeout + 0.5):
                    try:
                        peer_items.extend(fut.result())
                    except Exception:
                        pass
            except TimeoutError:
                # Some peers didn't respond in time — proceed with what we have
                pass

        # Deduplicate by item ID — local results take priority
        for item in peer_items:
            item_id = item.get("id")
            if item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                local.append(item)

        # Re-rank merged results by relevance score (rating as proxy)
        def _sort_key(item: dict) -> tuple:
            # Prefer local, then by rating descending
            is_local = 0 if item.get("source") == "local" else 1
            rating = -(item.get("rating") or 0)
            return (is_local, rating)

        local.sort(key=_sort_key)
        return local[:limit]
