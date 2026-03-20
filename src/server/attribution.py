# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Conversion attribution — multi-touch attribution for agent journeys.

Tracks the full agent journey from first search to purchase and
attributes conversions across multiple ad touchpoints. The first
agent purchase funnel attribution system.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from src.common.models import ConversionAttribution, TouchPoint
from src.server.store import CatalogStore


class AttributionEngine:
    """Tracks ad touchpoints and attributes conversions."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def record_touchpoint(
        self,
        agent_id: str,
        event_type: str,
        *,
        campaign_id: str = "",
        item_id: str = "",
    ) -> None:
        """Record an ad-related touchpoint in the agent's journey."""
        tp = TouchPoint(
            agent_id=agent_id,
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            campaign_id=campaign_id,
            item_id=item_id,
            timestamp=time.time(),
        )
        self._store.log_touchpoint(tp)

    def attribute_conversion(
        self,
        order_id: str,
        agent_id: str,
        item_id: str,
        revenue_cents: int,
    ) -> dict[str, Any]:
        """Attribute a purchase to ad touchpoints using first-touch + last-touch."""
        touchpoints = self._store.get_agent_touchpoints(agent_id, item_id=item_id)

        # Filter to ad-related touchpoints only
        ad_touches = [tp for tp in touchpoints if tp.get("campaign_id")]

        first_campaign = ad_touches[0]["campaign_id"] if ad_touches else ""
        last_campaign = ad_touches[-1]["campaign_id"] if ad_touches else ""

        attr = ConversionAttribution(
            order_id=order_id,
            agent_id=agent_id,
            item_id=item_id,
            touchpoints=len(ad_touches),
            first_touch_campaign=first_campaign,
            last_touch_campaign=last_campaign,
            attributed_revenue_cents=revenue_cents,
            created_at=time.time(),
        )
        self._store.save_attribution(attr)

        return {
            "order_id": order_id,
            "touchpoints": len(ad_touches),
            "first_touch_campaign": first_campaign,
            "last_touch_campaign": last_campaign,
            "attributed_revenue_cents": revenue_cents,
        }

    def handle(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle the catalog.attribution skill."""
        action = data.get("action", "campaign")

        if action == "campaign":
            campaign_id = data.get("campaign_id", "")
            if not campaign_id:
                return {"error": "campaign_id required"}
            return self._store.get_campaign_attributions(campaign_id)

        elif action == "journey":
            agent_id = data.get("agent_id", "")
            item_id = data.get("item_id", "")
            if not agent_id:
                return {"error": "agent_id required"}
            touchpoints = self._store.get_agent_touchpoints(agent_id, item_id=item_id)
            return {
                "agent_id": agent_id,
                "item_id": item_id or None,
                "touchpoints": [
                    {
                        "event_type": tp["event_type"],
                        "campaign_id": tp["campaign_id"],
                        "item_id": tp["item_id"],
                        "timestamp": tp["timestamp"],
                    }
                    for tp in touchpoints
                ],
                "count": len(touchpoints),
            }

        return {"error": f"Unknown action: {action}"}
