# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Audience segments & lookalike targeting.

Clusters agents by behavior into segments (bargain hunters, premium
buyers, category specialists). Advertisers can target segments for
more efficient ad spend. The first agent behavioral segmentation
system for AI commerce.
"""

from __future__ import annotations

import time
from typing import Any

from src.common.models import AgentSegment
from src.server.store import CatalogStore

# Pre-defined behavioral segments
_DEFAULT_SEGMENTS = [
    AgentSegment("seg-bargain", "Bargain Hunters",
                 "Agents that negotiate frequently and prefer lower-priced items"),
    AgentSegment("seg-premium", "Premium Buyers",
                 "Agents that consistently purchase high-priced items"),
    AgentSegment("seg-research", "Researchers",
                 "Agents that compare extensively before purchasing"),
    AgentSegment("seg-impulse", "Impulse Buyers",
                 "Agents that purchase quickly with minimal browsing"),
    AgentSegment("seg-loyal", "Loyal Repeat Buyers",
                 "Agents that return to the same vendors repeatedly"),
]


class AudienceEngine:
    """Manages agent behavioral segments and lookalike targeting."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store
        self._ensure_default_segments()

    def _ensure_default_segments(self) -> None:
        """Seed default segments if not present."""
        for seg in _DEFAULT_SEGMENTS:
            existing = self._store.get_segment(seg.segment_id)
            if not existing:
                seg.created_at = time.time()
                self._store.upsert_segment(seg)

    def classify_agent(self, agent_id: str) -> list[dict[str, Any]]:
        """Classify an agent into behavioral segments based on their activity."""
        profile = self._store.get_or_create_agent(agent_id)
        interests = self._store.get_interests(agent_id, top_n=50)
        events = self._store.get_agent_events(agent_id, limit=200)

        # Count event types
        counts: dict[str, int] = {}
        for ev in events:
            t = ev.get("event_type", "")
            counts[t] = counts.get(t, 0) + 1

        assignments: list[dict[str, Any]] = []

        # Bargain hunter: negotiates a lot relative to purchases
        neg_count = counts.get("negotiate", 0)
        if neg_count >= 3:
            self._store.assign_segment(agent_id, "seg-bargain", confidence=min(1.0, neg_count / 10))
            assignments.append({"segment_id": "seg-bargain", "label": "Bargain Hunters"})

        # Premium buyer: high average purchase price
        purchase_count = profile.get("total_purchases", 0)
        if purchase_count >= 2:
            # Check if they buy expensive items
            high_intent = [i for i in interests if i.get("intent_tier") in ("high_intent", "ready_to_buy")]
            if len(high_intent) >= 2:
                self._store.assign_segment(agent_id, "seg-premium", confidence=0.8)
                assignments.append({"segment_id": "seg-premium", "label": "Premium Buyers"})

        # Researcher: lots of compares
        compare_count = counts.get("compare", 0)
        if compare_count >= 3:
            self._store.assign_segment(agent_id, "seg-research", confidence=min(1.0, compare_count / 8))
            assignments.append({"segment_id": "seg-research", "label": "Researchers"})

        # Impulse buyer: purchases quickly (few searches before buy)
        search_count = counts.get("search", 0)
        if purchase_count >= 2 and search_count <= purchase_count * 2:
            self._store.assign_segment(agent_id, "seg-impulse", confidence=0.7)
            assignments.append({"segment_id": "seg-impulse", "label": "Impulse Buyers"})

        # Loyal: repeat lookups on same items
        repeat_items = [i for i in interests if i.get("visit_count", 0) >= 3]
        if len(repeat_items) >= 2:
            self._store.assign_segment(agent_id, "seg-loyal", confidence=0.9)
            assignments.append({"segment_id": "seg-loyal", "label": "Loyal Repeat Buyers"})

        return assignments

    def handle(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Handle the catalog.audience skill."""
        action = data.get("action", "classify")

        if action == "classify":
            if not agent_id:
                return {"error": "Authentication required"}
            segments = self.classify_agent(agent_id)
            existing = self._store.get_agent_segments(agent_id)
            return {
                "agent_id": agent_id,
                "segments": [
                    {
                        "segment_id": s["segment_id"],
                        "label": s.get("label", ""),
                        "confidence": s.get("confidence", 1.0),
                    }
                    for s in existing
                ],
                "newly_assigned": segments,
            }

        elif action == "list":
            segs = self._store.list_segments()
            return {
                "segments": [
                    {
                        "segment_id": s["segment_id"],
                        "label": s["label"],
                        "description": s["description"],
                        "agent_count": s["agent_count"],
                    }
                    for s in segs
                ],
                "count": len(segs),
            }

        return {"error": f"Unknown action: {action}"}
