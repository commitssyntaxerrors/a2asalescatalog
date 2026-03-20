# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""A2A Sales Catalog — Skill handlers.

Each skill maps to a function that takes the request data dict
and returns the response data dict (compact tuple format).
"""

from __future__ import annotations

import json
from typing import Any

from src.common.models import CATEGORY_FIELDS, SEARCH_FIELDS, SEARCH_FIELDS_WITH_EMB
from src.server.ads import AdEngine
from src.server.agent_tracker import AgentTracker
from src.server.embeddings import EmbeddingIndex
from src.server.federation import FederationManager
from src.server.negotiation import NegotiationEngine
from src.server.purchase import PurchaseEngine
from src.server.store import CatalogStore
from src.server.vendor_analytics import VendorAnalytics

COMPARE_BASE_FIELDS = ["id", "name", "price_cents", "rating", "review_count"]


class SkillRouter:
    """Dispatches A2A skill invocations to handler methods."""

    def __init__(
        self,
        store: CatalogStore,
        ad_engine: AdEngine,
        tracker: AgentTracker,
        negotiation: NegotiationEngine,
        purchase: PurchaseEngine,
        federation: FederationManager,
        embeddings: EmbeddingIndex,
        vendor_analytics: VendorAnalytics,
    ) -> None:
        self._store = store
        self._ads = ad_engine
        self._tracker = tracker
        self._negotiation = negotiation
        self._purchase = purchase
        self._federation = federation
        self._embeddings = embeddings
        self._vendor_analytics = vendor_analytics
        self._handlers: dict[str, Any] = {
            "catalog.search": self._handle_search,
            "catalog.lookup": self._handle_lookup,
            "catalog.categories": self._handle_categories,
            "catalog.compare": self._handle_compare,
            "catalog.negotiate": self._handle_negotiate,
            "catalog.purchase": self._handle_purchase,
            "catalog.agent_profile": self._handle_agent_profile,
            "catalog.reputation": self._handle_reputation,
            "catalog.embed": self._handle_embed,
            "catalog.peers": self._handle_peers,
            "catalog.vendor_analytics": self._handle_vendor_analytics,
        }

    def handle(self, data: dict[str, Any], agent_id: str = "") -> dict[str, Any]:
        skill = data.get("skill", "")
        handler = self._handlers.get(skill)
        if not handler:
            return {"error": f"Unknown skill: {skill}"}
        return handler(data, agent_id)

    # ------------------------------------------------------------------
    # catalog.search
    # ------------------------------------------------------------------

    def _handle_search(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        q = str(data.get("q", ""))
        limit = min(int(data.get("max", 10)), 50)
        cat = data.get("cat")
        price_min = data.get("price_min")
        price_max = data.get("price_max")
        sort = data.get("sort", "relevance")
        vendor = data.get("vendor")
        include_emb = data.get("include_embeddings", False)

        # Track event
        if agent_id:
            self._tracker.log(agent_id, "search", query=q, category=cat)

        organic = self._store.search(
            q,
            category=cat,
            vendor=vendor,
            price_min=price_min,
            price_max=price_max,
            sort=sort,
            limit=limit,
        )

        # Intent-aware ad injection
        intent_tier = self._tracker.get_intent_tier(agent_id) if agent_id else "browse"
        merged = self._ads.inject_sponsored(organic, q, cat, limit, intent_tier=intent_tier)

        # Encode as compact tuples
        fields = SEARCH_FIELDS_WITH_EMB if include_emb else SEARCH_FIELDS
        items = []
        for row in merged:
            t = [
                row["id"],
                row["name"],
                row["desc"],
                row["price_cents"],
                row.get("vendor_domain", row["vendor_id"]),
                row["rating"],
                row["sponsored"],
                row.get("ad_tag"),
            ]
            if include_emb:
                embs = self._embeddings.get_item_embeddings([row["id"]])
                t.append(embs[0][1] if embs else "")
            items.append(t)

        return {
            "fields": fields,
            "items": items,
            "currency": "USD",
            "total": len(items),
        }

    # ------------------------------------------------------------------
    # catalog.lookup
    # ------------------------------------------------------------------

    def _handle_lookup(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        item_id = str(data.get("id", ""))
        row = self._store.lookup(item_id)
        if not row:
            return {"error": f"Item not found: {item_id}"}

        # Track event
        if agent_id:
            self._tracker.log(agent_id, "lookup", item_id=item_id,
                              category=row.get("category_id"))

        attrs = json.loads(row["attrs"]) if isinstance(row["attrs"], str) else row["attrs"]
        images = json.loads(row["images"]) if isinstance(row["images"], str) else row["images"]

        # Trust-based pricing
        price = row["price_cents"]
        if agent_id and row.get("trusted_price_cents"):
            profile = self._store.get_or_create_agent(agent_id)
            if profile["reputation"] >= (row.get("reputation_threshold") or 0):
                price = row["trusted_price_cents"]

        return {
            "id": row["id"],
            "name": row["name"],
            "desc": row["desc"],
            "price_cents": price,
            "currency": row.get("currency", "USD"),
            "vendor": row.get("vendor_domain", row["vendor_id"]),
            "rating": row["rating"],
            "review_count": row["review_count"],
            "attrs": attrs,
            "buy_url": row["buy_url"],
            "images": images,
            "sponsored": row["sponsored"],
            "ad_tag": row.get("ad_tag"),
        }

    # ------------------------------------------------------------------
    # catalog.categories
    # ------------------------------------------------------------------

    def _handle_categories(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        parent = data.get("parent")
        cats = self._store.list_categories(parent)
        return {
            "fields": CATEGORY_FIELDS,
            "cats": [[c["id"], c["label"], c["item_count"]] for c in cats],
        }

    # ------------------------------------------------------------------
    # catalog.compare
    # ------------------------------------------------------------------

    def _handle_compare(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        ids = data.get("ids", [])
        if not ids or len(ids) < 2:
            return {"error": "Provide at least 2 item IDs to compare"}

        rows = self._store.get_items_by_ids(ids)
        if not rows:
            return {"error": "No items found for the given IDs"}

        # Track event
        if agent_id:
            for row in rows:
                self._tracker.log(agent_id, "compare", item_id=row["id"],
                                  category=row.get("category_id"))

        # Collect all attribute keys across items for comparison columns
        all_attr_keys: list[str] = []
        seen_keys: set[str] = set()
        for row in rows:
            attrs = json.loads(row["attrs"]) if isinstance(row["attrs"], str) else row["attrs"]
            for k, _v in attrs:
                if k not in seen_keys:
                    all_attr_keys.append(k)
                    seen_keys.add(k)

        fields = COMPARE_BASE_FIELDS + all_attr_keys
        result_rows = []
        for row in rows:
            attrs = json.loads(row["attrs"]) if isinstance(row["attrs"], str) else row["attrs"]
            attr_map = dict(attrs)
            result_row = [
                row["id"], row["name"], row["price_cents"],
                row["rating"], row["review_count"],
            ]
            for ak in all_attr_keys:
                result_row.append(attr_map.get(ak))
            result_rows.append(result_row)

        return {"fields": fields, "rows": result_rows}

    # ------------------------------------------------------------------
    # catalog.negotiate
    # ------------------------------------------------------------------

    def _handle_negotiate(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        if not agent_id:
            return {"error": "Authentication required for negotiation"}
        # Track event
        item_id = data.get("item_id", "")
        self._tracker.log(agent_id, "negotiate", item_id=item_id)
        return self._negotiation.negotiate(agent_id, data)

    # ------------------------------------------------------------------
    # catalog.purchase
    # ------------------------------------------------------------------

    def _handle_purchase(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        if not agent_id:
            return {"error": "Authentication required for purchase"}
        item_id = data.get("item_id", "")
        self._tracker.log(agent_id, "purchase", item_id=item_id)
        return self._purchase.purchase(agent_id, data)

    # ------------------------------------------------------------------
    # catalog.agent_profile
    # ------------------------------------------------------------------

    def _handle_agent_profile(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        if not agent_id:
            return {"error": "Authentication required"}
        return self._tracker.get_profile_summary(agent_id)

    # ------------------------------------------------------------------
    # catalog.reputation
    # ------------------------------------------------------------------

    def _handle_reputation(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        if not agent_id:
            return {"error": "Authentication required"}
        profile = self._store.get_or_create_agent(agent_id)
        import time
        age_days = (time.time() - profile["created_at"]) / 86400
        age_score = min(10, round(age_days * 0.1, 1))
        purchase_score = profile["total_purchases"] * 5.0
        consistency_score = min(15, round(profile["total_queries"] * 0.05, 1))

        benefits = []
        rep = profile["reputation"]
        if rep >= 60:
            benefits.append("trusted_pricing")
        if rep >= 40:
            benefits.append("negotiation_access")
        if rep >= 70:
            benefits.append("priority_response")

        tier = "new"
        if rep >= 80:
            tier = "trusted"
        elif rep >= 60:
            tier = "established"
        elif rep >= 40:
            tier = "active"

        return {
            "agent_id": agent_id,
            "score": rep,
            "factors": [
                ["age", age_score],
                ["purchases", purchase_score],
                ["consistency", consistency_score],
            ],
            "tier": tier,
            "benefits": benefits,
        }

    # ------------------------------------------------------------------
    # catalog.embed
    # ------------------------------------------------------------------

    def _handle_embed(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        return self._embeddings.embed(data)

    # ------------------------------------------------------------------
    # catalog.peers
    # ------------------------------------------------------------------

    def _handle_peers(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        return self._federation.list_peers()

    # ------------------------------------------------------------------
    # catalog.vendor_analytics
    # ------------------------------------------------------------------

    def _handle_vendor_analytics(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        return self._vendor_analytics.report(data)
