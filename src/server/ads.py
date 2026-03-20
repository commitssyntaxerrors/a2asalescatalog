# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""A2A Sales Catalog — Ad engine.

Handles sponsored result insertion, display ads, frequency capping,
A/B testing, creative rotation, dayparting, and cross-sell injection.
"""

from __future__ import annotations

import json
import time
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
        agent_id: str = "",
    ) -> list[dict[str, Any]]:
        """Insert sponsored items into organic results respecting the cap.

        Uses intent-tiered bidding, frequency capping, and dayparting.
        """
        campaigns = self._store.get_matching_campaigns(query, category)
        if not campaigns:
            return organic_results

        now = time.time()

        # Sort campaigns by intent-tiered bid
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

            # Frequency cap check
            if agent_id and camp.get("freq_cap_count", 0) > 0:
                freq = self._store.get_frequency(agent_id, camp["id"])
                if freq:
                    window = camp.get("freq_cap_window_secs", 3600)
                    if (now - freq["window_start"]) <= window:
                        if freq["impressions"] >= camp["freq_cap_count"]:
                            continue

            # Dayparting check
            if not self._check_schedule(camp, now):
                continue

            # Find items from this campaign's vendor
            vendor_items = self._store.search(query, vendor=None, limit=3)
            for vi in vendor_items:
                if vi["id"] not in organic_ids and vi["vendor_id"] == camp["vendor_id"]:
                    vi["sponsored"] = 1
                    vi["ad_tag"] = camp["ad_tag"]
                    insert_pos = min(1 + sponsored_added, len(merged))
                    merged.insert(insert_pos, vi)
                    organic_ids.add(vi["id"])
                    sponsored_added += 1

                    # Record impression for frequency capping
                    if agent_id:
                        self._store.record_impression_freq(agent_id, camp["id"])

                    # A/B test impression tracking
                    ab_group = camp.get("ab_group", "")
                    ab_variant = camp.get("ab_variant", "")
                    if ab_group and ab_variant:
                        self._store.log_ab_event(ab_group, ab_variant, "impression", camp["id"])

                    break

        return merged[:limit]

    def get_display_ads(
        self,
        *,
        category: str | None = None,
        item_id: str | None = None,
        agent_id: str = "",
        max_ads: int = 2,
    ) -> list[dict[str, Any]]:
        """Get structured display/banner ads for non-search contexts (lookup, categories)."""
        campaigns = self._store.get_all_active_campaigns()
        now = time.time()
        results: list[dict[str, Any]] = []

        for camp in campaigns:
            if len(results) >= max_ads:
                break
            if camp["spent_cents"] >= camp["budget_cents"]:
                continue
            if not self._check_schedule(camp, now):
                continue

            # Frequency cap
            if agent_id and camp.get("freq_cap_count", 0) > 0:
                freq = self._store.get_frequency(agent_id, camp["id"])
                if freq:
                    window = camp.get("freq_cap_window_secs", 3600)
                    if (now - freq["window_start"]) <= window:
                        if freq["impressions"] >= camp["freq_cap_count"]:
                            continue

            # Category relevance
            cats = json.loads(camp["categories"]) if isinstance(camp["categories"], str) else camp["categories"]
            if category and cats and category not in cats:
                continue

            # Pick creative variant via rotation
            creative = self._select_creative(camp)

            results.append({
                "campaign_id": camp["id"],
                "vendor_id": camp["vendor_id"],
                "headline": camp.get("promo_headline", "") or f"From {camp['vendor_id']}",
                "body": camp.get("promo_body", ""),
                "image_url": camp.get("promo_image_url", ""),
                "ad_tag": camp["ad_tag"],
                "creative_variant": creative,
                "sponsored": 1,
            })

            if agent_id:
                self._store.record_impression_freq(agent_id, camp["id"])

        return results

    def get_cross_sell_recommendations(
        self,
        item_id: str,
        *,
        max_recs: int = 3,
    ) -> list[dict[str, Any]]:
        """Get cross-sell / upsell recommendations for an item."""
        rules = self._store.get_cross_sells(item_id)
        results = []
        for r in rules[:max_recs]:
            results.append({
                "item_id": r["target_item_id"],
                "name": r.get("target_name", ""),
                "price_cents": r.get("target_price_cents", 0),
                "rating": r.get("target_rating", 0),
                "relation": r["relation_type"],
                "sponsored": 1 if r["bid_cents"] > 0 else 0,
            })
        return results

    def record_impression(self, ad_tag: str) -> None:
        """Track an ad impression (future: write to analytics store)."""
        pass

    def _check_schedule(self, camp: dict[str, Any], now: float) -> bool:
        """Check if campaign is within its scheduled time window."""
        start = camp.get("schedule_start", 0)
        end = camp.get("schedule_end", 0)
        if start and now < start:
            return False
        if end and now > end:
            return False

        # Dayparting: check hours and days
        schedule_hours = camp.get("schedule_hours")
        schedule_days = camp.get("schedule_days")
        if schedule_hours or schedule_days:
            lt = time.localtime(now)
            if schedule_hours:
                hours = json.loads(schedule_hours) if isinstance(schedule_hours, str) else schedule_hours
                if hours and lt.tm_hour not in hours:
                    return False
            if schedule_days:
                days = json.loads(schedule_days) if isinstance(schedule_days, str) else schedule_days
                if days and lt.tm_wday not in days:
                    return False
        return True

    def _select_creative(self, camp: dict[str, Any]) -> str:
        """Select a creative variant from the campaign's creative rotation pool."""
        creatives = camp.get("creatives")
        if not creatives:
            return ""
        if isinstance(creatives, str):
            creatives = json.loads(creatives)
        if not creatives:
            return ""

        weights = camp.get("creative_weights")
        if isinstance(weights, str):
            weights = json.loads(weights)

        # Simple round-robin based on impression count
        # In production, use weighted random or multi-armed bandit
        freq_total = camp.get("spent_cents", 0)  # proxy for impression count
        idx = freq_total % len(creatives)
        return creatives[idx]
