# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Agent tracking, interest scoring, and intent classification.

Logs every agent interaction, computes interest scores per item/category,
and classifies agents into intent tiers for tiered ad bidding and
vendor notifications.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from src.common.models import AgentEvent, AgentInterest, classify_intent
from src.server.store import CatalogStore

# Scoring weights per event type
_WEIGHTS: dict[str, float] = {
    "search": 1.0,
    "lookup": 3.0,
    "compare": 2.0,
    "negotiate": 5.0,
    "purchase": 10.0,
}

_RECENCY_DECAY = 0.9  # score × 0.9^(days_since_last)
_REPEAT_BONUS = 2.0   # bonus per repeat visit (same item viewed 2+ times)


class AgentTracker:
    """Tracks agent behavior and computes interest/intent scores."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def ensure_agent(self, agent_id: str) -> dict[str, Any]:
        """Get or create an agent profile."""
        return self._store.get_or_create_agent(agent_id)

    def log(
        self,
        agent_id: str,
        event_type: str,
        *,
        item_id: str | None = None,
        query: str | None = None,
        category: str | None = None,
        metadata: str = "{}",
    ) -> None:
        """Log an event and update interest scores."""
        self._store.get_or_create_agent(agent_id)
        event = AgentEvent(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            event_type=event_type,
            item_id=item_id,
            query=query,
            category=category,
            metadata=metadata,
            timestamp=time.time(),
        )
        self._store.log_event(event)
        self._store.update_agent_stats(agent_id, queries=1 if event_type != "purchase" else 0,
                                       purchases=1 if event_type == "purchase" else 0)

        # Update interest scores
        if item_id:
            self._update_item_interest(agent_id, item_id, event_type)
        if category:
            self._update_category_interest(agent_id, category, event_type)

    def _update_item_interest(self, agent_id: str, item_id: str, event_type: str) -> None:
        existing = self._store.get_interest(agent_id, item_id)
        weight = _WEIGHTS.get(event_type, 1.0)
        now = time.time()

        if existing:
            old_score = existing["score"]
            visit_count = existing["visit_count"] + 1
            days_since = (now - existing["last_event_at"]) / 86400
            decayed = old_score * (_RECENCY_DECAY ** days_since)
            repeat_bonus = _REPEAT_BONUS if visit_count >= 2 else 0.0
            new_score = decayed + weight + repeat_bonus
        else:
            visit_count = 1
            new_score = weight

        tier = classify_intent(new_score)
        interest = AgentInterest(
            agent_id=agent_id,
            item_id=item_id,
            category="",
            score=round(new_score, 2),
            intent_tier=tier,
            visit_count=visit_count,
            last_event_at=now,
        )
        self._store.upsert_interest(interest)

    def _update_category_interest(self, agent_id: str, category: str, event_type: str) -> None:
        # Simplified: use item_id="" for category-level interests
        existing = self._store.get_interest(agent_id, "")
        weight = _WEIGHTS.get(event_type, 1.0) * 0.5  # categories get half weight
        now = time.time()

        if existing and existing.get("category") == category:
            old_score = existing["score"]
            visit_count = existing["visit_count"] + 1
            days_since = (now - existing["last_event_at"]) / 86400
            new_score = old_score * (_RECENCY_DECAY ** days_since) + weight
        else:
            visit_count = 1
            new_score = weight

        tier = classify_intent(new_score)
        interest = AgentInterest(
            agent_id=agent_id,
            item_id="",
            category=category,
            score=round(new_score, 2),
            intent_tier=tier,
            visit_count=visit_count,
            last_event_at=now,
        )
        self._store.upsert_interest(interest)

    def get_intent_tier(self, agent_id: str, item_id: str | None = None) -> str:
        """Get the current intent tier for an agent (optionally for a specific item)."""
        if item_id:
            interest = self._store.get_interest(agent_id, item_id)
            if interest:
                return interest["intent_tier"]
        # Fallback: highest tier across all interests
        interests = self._store.get_interests(agent_id, top_n=1)
        if interests:
            return interests[0]["intent_tier"]
        return "browse"

    def get_profile_summary(self, agent_id: str) -> dict[str, Any]:
        """Build a full agent profile summary for the catalog.agent_profile skill."""
        profile = self._store.get_or_create_agent(agent_id)
        interests = self._store.get_interests(agent_id, top_n=20)

        category_scores: dict[str, float] = {}
        item_interests: list[list] = []
        for i in interests:
            if i["item_id"]:
                item_interests.append([i["item_id"], i["score"], i["intent_tier"]])
            if i["category"]:
                cat = i["category"]
                category_scores[cat] = category_scores.get(cat, 0) + i["score"]

        top_categories = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)[:5]

        # Overall intent tier = max across items
        overall_tier = "browse"
        if interests:
            best = max(interests, key=lambda x: x["score"])
            overall_tier = best["intent_tier"]

        return {
            "agent_id": agent_id,
            "reputation": profile["reputation"],
            "intent_tier": overall_tier,
            "total_queries": profile["total_queries"],
            "top_interests": top_categories,
            "item_interests": item_interests[:10],
        }
