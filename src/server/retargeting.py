# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Agent retargeting / remarketing engine.

Re-surfaces items an agent previously viewed or compared but didn't
purchase, with time-decayed discount offers. The first agent-to-agent
retargeting system for autonomous commerce.
"""

from __future__ import annotations

import time
from typing import Any

from src.common.models import RetargetOffer
from src.server.store import CatalogStore

# Default discount tiers based on how long since the agent last viewed
_DISCOUNT_TIERS = [
    (86400,      5),   # within 1 day: 5% off
    (86400 * 3, 10),   # within 3 days: 10% off
    (86400 * 7, 15),   # within 7 days: 15% off
]
_OFFER_TTL = 86400  # retarget offers expire after 24h


class RetargetingEngine:
    """Generates retargeting offers for agents based on past behavior."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def get_retarget_offers(self, agent_id: str, *, max_offers: int = 5) -> list[dict[str, Any]]:
        """Find items the agent viewed but didn't purchase, generate discount offers."""
        now = time.time()

        # Get items the agent looked up
        lookup_events = self._store.get_agent_events(
            agent_id, event_type="lookup", limit=50,
        )
        # Get items the agent purchased
        purchase_events = self._store.get_agent_events(
            agent_id, event_type="purchase", limit=100,
        )
        purchased_ids = {e["item_id"] for e in purchase_events if e.get("item_id")}

        # Deduplicate lookups, keep most recent per item
        seen: dict[str, float] = {}
        for ev in lookup_events:
            iid = ev.get("item_id", "")
            if iid and iid not in purchased_ids:
                ts = ev.get("timestamp", 0)
                if iid not in seen or ts > seen[iid]:
                    seen[iid] = ts

        offers: list[dict[str, Any]] = []
        for item_id, last_seen in sorted(seen.items(), key=lambda x: x[1], reverse=True):
            if len(offers) >= max_offers:
                break
            item = self._store.lookup(item_id)
            if not item or not item.get("active"):
                continue

            elapsed = now - last_seen
            discount_pct = 0
            for max_age, pct in _DISCOUNT_TIERS:
                if elapsed <= max_age:
                    discount_pct = pct
                    break
            else:
                discount_pct = _DISCOUNT_TIERS[-1][1]  # max discount for old views

            original = item["price_cents"]
            offer_price = int(original * (100 - discount_pct) / 100)

            offers.append({
                "item_id": item_id,
                "item_name": item["name"],
                "original_price_cents": original,
                "offer_price_cents": offer_price,
                "discount_pct": discount_pct,
                "expires_at": now + _OFFER_TTL,
                "vendor": item.get("vendor_domain", item["vendor_id"]),
            })

        return offers

    def handle(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Handle the catalog.retarget skill."""
        if not agent_id:
            return {"error": "Authentication required for retargeting"}
        max_offers = min(int(data.get("max", 5)), 20)
        offers = self.get_retarget_offers(agent_id, max_offers=max_offers)
        return {
            "agent_id": agent_id,
            "offers": offers,
            "count": len(offers),
        }
