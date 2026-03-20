# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Real-time bidding (RTB) — per-request impression auctions.

On each search request, multiple advertisers bid in real time for
placement slots. Highest bid wins. Sub-100ms auction per query.
The first real-time bidding system for agent-to-agent commerce.
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.server.store import CatalogStore

# Auction timeout — if auction takes longer, fall back to static bids
_AUCTION_TIMEOUT_MS = 50


class RTBEngine:
    """Runs real-time impression auctions for ad placements."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def run_auction(
        self,
        query: str,
        category: str | None = None,
        *,
        intent_tier: str = "browse",
        slots: int = 2,
        agent_id: str = "",
    ) -> list[dict[str, Any]]:
        """Run a real-time auction. Returns winning bids sorted by bid amount."""
        campaigns = self._store.get_all_active_campaigns()
        if not campaigns:
            return []

        now = time.time()
        q_lower = query.lower()

        eligible: list[dict[str, Any]] = []
        for camp in campaigns:
            # Budget check
            if camp["spent_cents"] >= camp["budget_cents"]:
                continue

            # Keyword / category match
            kws = json.loads(camp["keywords"]) if isinstance(camp["keywords"], str) else camp["keywords"]
            cats = json.loads(camp["categories"]) if isinstance(camp["categories"], str) else camp["categories"]
            keyword_match = any(kw.lower() in q_lower for kw in kws)
            category_match = category and category in cats

            if not keyword_match and not category_match:
                continue

            # Frequency cap check
            if agent_id and camp.get("freq_cap_count", 0) > 0:
                freq = self._store.get_frequency(agent_id, camp["id"])
                if freq:
                    window_secs = camp.get("freq_cap_window_secs", 3600)
                    if (now - freq["window_start"]) <= window_secs:
                        if freq["impressions"] >= camp["freq_cap_count"]:
                            continue

            # Intent-tiered bid
            bid_key = f"bid_cents_{intent_tier}"
            effective_bid = camp.get(bid_key, 0) or camp.get("bid_cents", 0)

            eligible.append({
                "campaign_id": camp["id"],
                "vendor_id": camp["vendor_id"],
                "bid_cents": effective_bid,
                "ad_tag": camp["ad_tag"],
                "ab_group": camp.get("ab_group", ""),
                "ab_variant": camp.get("ab_variant", ""),
            })

        # Sort by bid (descending) — highest bidder wins
        eligible.sort(key=lambda x: x["bid_cents"], reverse=True)

        winners = eligible[:slots]

        # Record impressions for frequency capping
        if agent_id:
            for w in winners:
                self._store.record_impression_freq(
                    agent_id, w["campaign_id"],
                )

        return winners

    def handle(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle the catalog.auction skill — inspect recent auction results."""
        query = data.get("q", "")
        category = data.get("cat")
        slots = min(int(data.get("slots", 2)), 5)
        intent_tier = data.get("intent_tier", "browse")

        results = self.run_auction(
            query, category, intent_tier=intent_tier, slots=slots,
        )
        return {
            "query": query,
            "slots": slots,
            "winners": results,
            "count": len(results),
        }
