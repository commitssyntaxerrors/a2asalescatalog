# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Vendor analytics — agent behavior analytics for vendors.

A new class of analytics that doesn't exist today: vendors see how
*AI agents* interact with their products, not human click patterns.
"""

from __future__ import annotations

import time
from typing import Any

from src.server.store import CatalogStore

_PERIOD_SECONDS = {
    "1d": 86400,
    "7d": 86400 * 7,
    "30d": 86400 * 30,
}


class VendorAnalytics:
    """Generates vendor-facing analytics reports."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def report(self, data: dict[str, Any]) -> dict[str, Any]:
        """Generate a vendor analytics report."""
        vendor_id = data.get("vendor_id", "")
        period = data.get("period", "7d")

        if not vendor_id:
            return {"error": "vendor_id is required"}

        since = time.time() - _PERIOD_SECONDS.get(period, 86400 * 7)

        summary = self._store.vendor_event_summary(vendor_id, since)
        top_queries = self._store.vendor_top_queries(vendor_id, since)
        intent_breakdown = self._store.vendor_intent_breakdown(vendor_id)

        total_impressions = summary.get("impressions", 0)
        purchases = summary.get("purchases", 0)
        conversion = round(purchases / total_impressions, 4) if total_impressions else 0.0
        unique_agents = summary.get("unique_agents", 0)

        return {
            "vendor_id": vendor_id,
            "period": period,
            "summary": {
                "total_impressions": total_impressions,
                "unique_agents": unique_agents,
                "lookups": summary.get("lookups", 0),
                "comparisons": summary.get("compares", 0),
                "negotiations": summary.get("negotiations", 0),
                "purchases": purchases,
                "conversion_rate": conversion,
            },
            "top_queries": top_queries,
            "agent_intent_breakdown": intent_breakdown,
        }
