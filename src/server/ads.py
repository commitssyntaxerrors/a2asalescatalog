# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""A2A Sales Catalog — Ad engine.

Handles sponsored result insertion and attribution.
"""

from __future__ import annotations

import json
from typing import Any

from src.server.store import CatalogStore

# Max sponsored items per result page
MAX_SPONSORED_RATIO = 0.2  # 20% cap


class AdEngine:
    """Merges organic results with sponsored placements."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def inject_sponsored(
        self,
        organic_results: list[dict[str, Any]],
        query: str,
        category: str | None = None,
        limit: int = 10,
        *,
        intent_tier: str = "browse",
    ) -> list[dict[str, Any]]:
        """Insert sponsored items into organic results respecting the cap.

        Uses intent-tiered bidding: campaigns bid differently per intent tier
        (browse < consider < high_intent < ready_to_buy).
        """
        campaigns = self._store.get_matching_campaigns(query, category)
        if not campaigns:
            return organic_results

        # Sort campaigns by intent-tiered bid instead of flat bid
        bid_key = f"bid_cents_{intent_tier}"
        for camp in campaigns:
            camp["_effective_bid"] = camp.get(bid_key, 0) or camp.get("bid_cents", 0)
        campaigns.sort(key=lambda x: x["_effective_bid"], reverse=True)

        organic_ids = {r["id"] for r in organic_results}
        max_sponsored = max(1, int(limit * MAX_SPONSORED_RATIO))
        sponsored_added = 0

        merged = list(organic_results)

        for camp in campaigns:
            if sponsored_added >= max_sponsored:
                break
            if camp["spent_cents"] >= camp["budget_cents"]:
                continue

            # Find items from this campaign's vendor that aren't already in results
            vendor_items = self._store.search(
                query, vendor=None, limit=3,
            )
            for vi in vendor_items:
                if vi["id"] not in organic_ids and vi["vendor_id"] == camp["vendor_id"]:
                    vi["sponsored"] = 1
                    vi["ad_tag"] = camp["ad_tag"]
                    # Insert sponsored near top but not at position 0
                    insert_pos = min(1 + sponsored_added, len(merged))
                    merged.insert(insert_pos, vi)
                    organic_ids.add(vi["id"])
                    sponsored_added += 1
                    break

        return merged[:limit]

    def record_impression(self, ad_tag: str) -> None:
        """Track an ad impression (future: write to analytics store)."""
        # Stub — in production this increments spent_cents based on CPM
        pass
