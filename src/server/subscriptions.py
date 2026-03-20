# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Premium subscription management and agent preference profiles.

Handles subscription lifecycle, preference CRUD, preference-aware
re-ranking, and subscription status queries. Premium agents unlock
preference profiles, negotiation priority, sponsored-free results,
and preference-weighted ranking.
"""

from __future__ import annotations

import time
from typing import Any

from src.common.models import AgentPreferences, Subscription
from src.server.store import CatalogStore

# Subscription defaults
_DEFAULT_EXPIRY_DAYS = 365
_PREMIUM_NEGOTIATION_ROUNDS = 7
_PREMIUM_FLOOR_RATIO = 0.55
_FREE_FLOOR_RATIO = 0.70


class SubscriptionEngine:
    """Manages premium subscriptions and agent preference profiles."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Subscription lifecycle
    # ------------------------------------------------------------------

    def subscribe(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a subscription (catalog.subscribe skill)."""
        if not agent_id:
            return {"error": "Authentication required for subscription"}

        tier = data.get("tier", "premium")
        if tier not in ("free", "premium"):
            return {"error": f"Invalid tier: {tier}. Must be 'free' or 'premium'"}

        payment_token = data.get("payment_token", "")
        if tier == "premium" and not payment_token:
            return {"error": "payment_token required for premium subscription"}

        now = time.time()
        expires_at = now + (_DEFAULT_EXPIRY_DAYS * 86400) if tier == "premium" else 0.0

        # Check for existing subscription
        existing = self._store.get_subscription(agent_id)
        created_at = existing["created_at"] if existing else now

        sub = Subscription(
            agent_id=agent_id,
            tier=tier,
            status="active",
            payment_token=payment_token,
            created_at=created_at,
            expires_at=expires_at,
        )
        self._store.upsert_subscription(sub)
        self._store.get_or_create_agent(agent_id)

        return {
            "agent_id": agent_id,
            "tier": tier,
            "status": "active",
            "expires_at": expires_at,
            "premium_benefits": _premium_benefits() if tier == "premium" else [],
        }

    # ------------------------------------------------------------------
    # Subscription status
    # ------------------------------------------------------------------

    def subscription_status(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Return current subscription status (catalog.subscription_status skill)."""
        if not agent_id:
            return {"error": "Authentication required"}

        sub = self._store.get_subscription(agent_id)
        if not sub:
            return {
                "agent_id": agent_id,
                "tier": "free",
                "status": "none",
                "preferences_active": False,
            }

        is_active_premium = (
            sub["tier"] == "premium"
            and sub["status"] == "active"
            and (not sub["expires_at"] or sub["expires_at"] > time.time())
        )

        prefs = self._store.get_preferences(agent_id)
        prefs_summary = {}
        if prefs and is_active_premium:
            prefs_summary = {
                "max_price_cents": prefs["max_price_cents"],
                "min_rating": prefs["min_rating"],
                "preferred_vendors_count": len(prefs["preferred_vendors"]),
                "excluded_vendors_count": len(prefs["excluded_vendors"]),
                "categories_preferred_count": len(prefs["categories_preferred"]),
            }

        return {
            "agent_id": agent_id,
            "tier": sub["tier"],
            "status": sub["status"],
            "expires_at": sub["expires_at"],
            "preferences_active": bool(prefs) and is_active_premium,
            "preferences_summary": prefs_summary,
            "premium_benefits": _premium_benefits() if is_active_premium else [],
        }

    # ------------------------------------------------------------------
    # Preference CRUD
    # ------------------------------------------------------------------

    def preferences(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Handle catalog.preferences skill (get | set | reset)."""
        if not agent_id:
            return {"error": "Authentication required"}

        if not self._store.is_premium(agent_id):
            return {"error": "Premium subscription required for preference profiles"}

        action = data.get("action", "get")

        if action == "get":
            return self._get_preferences(agent_id)
        elif action == "set":
            return self._set_preferences(agent_id, data)
        elif action == "reset":
            return self._reset_preferences(agent_id)
        else:
            return {"error": f"Unknown action: {action}. Use get, set, or reset"}

    def _get_preferences(self, agent_id: str) -> dict[str, Any]:
        prefs = self._store.get_preferences(agent_id)
        if not prefs:
            return {"agent_id": agent_id, "status": "no_preferences"}
        return {
            "agent_id": agent_id,
            "status": "active",
            "preferences": prefs,
        }

    def _set_preferences(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        # Merge with existing or start fresh
        existing = self._store.get_preferences(agent_id) or {}
        # Preferences may be nested under a "preferences" key or at top level
        pdata = data.get("preferences", data)
        now = time.time()

        prefs = AgentPreferences(
            agent_id=agent_id,
            max_price_cents=int(pdata.get("max_price_cents", existing.get("max_price_cents", 0))),
            min_rating=float(pdata.get("min_rating", existing.get("min_rating", 0.0))),
            preferred_vendors=pdata.get("preferred_vendors", existing.get("preferred_vendors", [])),
            excluded_vendors=pdata.get("excluded_vendors", existing.get("excluded_vendors", [])),
            sustainability_weight=float(pdata.get("sustainability_weight", existing.get("sustainability_weight", 0.0))),
            speed_weight=float(pdata.get("speed_weight", existing.get("speed_weight", 0.0))),
            price_weight=float(pdata.get("price_weight", existing.get("price_weight", 0.0))),
            brand_loyalty=pdata.get("brand_loyalty", existing.get("brand_loyalty", [])),
            geo_preference=pdata.get("geo_preference", existing.get("geo_preference", "")),
            categories_preferred=pdata.get("categories_preferred", existing.get("categories_preferred", [])),
            categories_excluded=pdata.get("categories_excluded", existing.get("categories_excluded", [])),
            updated_at=now,
        )
        # Clamp weights to [0, 1]
        prefs.sustainability_weight = max(0.0, min(1.0, prefs.sustainability_weight))
        prefs.speed_weight = max(0.0, min(1.0, prefs.speed_weight))
        prefs.price_weight = max(0.0, min(1.0, prefs.price_weight))
        prefs.min_rating = max(0.0, min(5.0, prefs.min_rating))

        self._store.upsert_preferences(prefs)
        return {
            "agent_id": agent_id,
            "status": "updated",
            "preferences": self._store.get_preferences(agent_id),
        }

    def _reset_preferences(self, agent_id: str) -> dict[str, Any]:
        self._store.delete_preferences(agent_id)
        return {"agent_id": agent_id, "status": "reset"}

    # ------------------------------------------------------------------
    # Preference-aware re-ranking (called from search)
    # ------------------------------------------------------------------

    def rerank_results(
        self,
        agent_id: str,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Re-rank search results against the agent's preference profile.

        Returns the filtered/reranked list with preference_match_score added.
        Called only for premium agents with active preferences.
        """
        prefs = self._store.get_preferences(agent_id)
        if not prefs:
            return items

        filtered: list[dict[str, Any]] = []
        for item in items:
            # Hard filters
            vendor_domain = item.get("vendor_domain", item.get("vendor_id", ""))
            if prefs["excluded_vendors"] and vendor_domain in prefs["excluded_vendors"]:
                continue
            if prefs["max_price_cents"] and item.get("price_cents", 0) > prefs["max_price_cents"]:
                continue
            if prefs["min_rating"] and item.get("rating", 0) < prefs["min_rating"]:
                continue
            cat_id = item.get("category_id", "")
            if prefs["categories_excluded"] and cat_id in prefs["categories_excluded"]:
                continue

            # Compute preference match score
            score = 0.0

            # Preferred vendor boost
            if vendor_domain in prefs.get("preferred_vendors", []):
                score += 3.0
            # Brand loyalty boost
            if vendor_domain in prefs.get("brand_loyalty", []):
                score += 2.0
            # Preferred category boost
            if cat_id in prefs.get("categories_preferred", []):
                score += 1.5

            # Price weight: lower price = higher score (normalized)
            price = item.get("price_cents", 0)
            if prefs["price_weight"] > 0 and price > 0:
                max_p = prefs["max_price_cents"] if prefs["max_price_cents"] else 100000
                price_score = (1.0 - min(price / max_p, 1.0)) * prefs["price_weight"] * 2.0
                score += price_score

            # Rating contribution
            rating = item.get("rating", 0.0)
            score += rating * 0.5

            item["preference_match_score"] = round(score, 2)
            filtered.append(item)

        # Sort by preference_match_score descending (stable sort preserves relevance tie-breaking)
        filtered.sort(key=lambda x: x.get("preference_match_score", 0), reverse=True)
        return filtered

    # ------------------------------------------------------------------
    # Negotiation helpers
    # ------------------------------------------------------------------

    def get_negotiation_params(self, agent_id: str) -> dict[str, Any]:
        """Return negotiation parameters based on subscription tier."""
        is_premium = self._store.is_premium(agent_id)
        return {
            "premium_agent": is_premium,
            "max_rounds": _PREMIUM_NEGOTIATION_ROUNDS if is_premium else 5,
            "floor_ratio": _PREMIUM_FLOOR_RATIO if is_premium else _FREE_FLOOR_RATIO,
        }


def _premium_benefits() -> list[str]:
    return [
        "preference_profiles",
        "negotiation_priority",
        "sponsored_free_results",
        "preference_weighted_ranking",
        "extended_negotiation_rounds",
        "lower_floor_pricing",
        "personalized_deals",
    ]
