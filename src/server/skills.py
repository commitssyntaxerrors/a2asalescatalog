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
from src.server.affiliates import AffiliateEngine
from src.server.agent_tracker import AgentTracker
from src.server.attribution import AttributionEngine
from src.server.audience import AudienceEngine
from src.server.embeddings import EmbeddingIndex
from src.server.federation import FederationManager
from src.server.negotiation import NegotiationEngine
from src.server.promotions import PromotionEngine
from src.server.purchase import PurchaseEngine
from src.server.retargeting import RetargetingEngine
from src.server.rtb import RTBEngine
from src.server.store import CatalogStore
from src.server.subscriptions import SubscriptionEngine
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
        retargeting: RetargetingEngine,
        affiliates: AffiliateEngine,
        rtb: RTBEngine,
        promotions: PromotionEngine,
        audience: AudienceEngine,
        attribution: AttributionEngine,
        subscriptions: SubscriptionEngine | None = None,
    ) -> None:
        self._store = store
        self._ads = ad_engine
        self._tracker = tracker
        self._negotiation = negotiation
        self._purchase = purchase
        self._federation = federation
        self._embeddings = embeddings
        self._vendor_analytics = vendor_analytics
        self._retargeting = retargeting
        self._affiliates = affiliates
        self._rtb = rtb
        self._promotions = promotions
        self._audience = audience
        self._attribution = attribution
        self._subscriptions = subscriptions
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
            "catalog.retarget": self._handle_retarget,
            "catalog.affiliate": self._handle_affiliate,
            "catalog.auction": self._handle_auction,
            "catalog.promotions": self._handle_promotions,
            "catalog.audience": self._handle_audience,
            "catalog.attribution": self._handle_attribution,
            "catalog.cross_sell": self._handle_cross_sell,
            "catalog.display_ads": self._handle_display_ads,
            "catalog.ab_results": self._handle_ab_results,
            "catalog.subscribe": self._handle_subscribe,
            "catalog.preferences": self._handle_preferences,
            "catalog.subscription_status": self._handle_subscription_status,
            "catalog.deals": self._handle_deals,
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
        min_results = int(data.get("min_results", 5))

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

        # Federated peer fan-out when local results are sparse
        if len(organic) < min_results:
            local_as_dicts = []
            for row in organic:
                d = dict(row) if not isinstance(row, dict) else row
                d["source"] = "local"
                local_as_dicts.append(d)
            merged = self._federation.fan_out_search(
                q, cat,
                min_results=min_results,
                local_results=local_as_dicts,
                limit=limit,
            )
            # Rebuild organic from merged (may contain peer items)
            organic = merged

        # Intent-aware ad injection
        intent_tier = self._tracker.get_intent_tier(agent_id) if agent_id else "browse"
        is_premium = self._subscriptions and agent_id and self._store.is_premium(agent_id)

        if is_premium:
            # Premium agents get sponsored-free results
            merged = organic if isinstance(organic, list) else list(organic)
            # Ensure all items are dicts
            merged = [dict(r) if not isinstance(r, dict) else r for r in merged]
        else:
            merged = self._ads.inject_sponsored(organic, q, cat, limit,
                                                intent_tier=intent_tier, agent_id=agent_id)

        # Record ad touchpoints for attribution
        if agent_id:
            for row in merged:
                if row.get("sponsored") and row.get("ad_tag"):
                    self._attribution.record_touchpoint(
                        agent_id, "ad_impression", item_id=row["id"],
                    )

        # Preference-aware re-ranking for premium agents
        if is_premium and self._subscriptions:
            merged = self._subscriptions.rerank_results(agent_id, merged)

        # Encode as compact tuples
        fields = SEARCH_FIELDS_WITH_EMB if include_emb else SEARCH_FIELDS
        # Add source field for federated results
        has_peer_results = any(r.get("source") and r["source"] != "local" for r in merged)
        if has_peer_results:
            fields = list(fields) + ["source"]
        # Add preference_match_score field for premium agents
        has_pref_score = any(r.get("preference_match_score") is not None for r in merged)
        if has_pref_score:
            fields = list(fields) if not isinstance(fields, list) else fields
            if "preference_match_score" not in fields:
                fields = list(fields) + ["preference_match_score"]

        items = []
        for row in merged:
            t = [
                row["id"],
                row["name"],
                row["desc"],
                row["price_cents"],
                row.get("vendor_domain", row.get("vendor_id", row.get("vendor", ""))),
                row["rating"],
                row.get("sponsored", 0),
                row.get("ad_tag"),
            ]
            if include_emb:
                embs = self._embeddings.get_item_embeddings([row["id"]])
                t.append(embs[0][1] if embs else "")
            if has_peer_results:
                t.append(row.get("source", "local"))
            if has_pref_score:
                t.append(row.get("preference_match_score"))
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

        result = {
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

        # Cross-sell recommendations
        cross_sells = self._ads.get_cross_sell_recommendations(item_id)
        if cross_sells:
            result["cross_sell"] = cross_sells

        # Display ads relevant to this item's category
        display = self._ads.get_display_ads(
            category=row.get("category_id"), item_id=item_id, agent_id=agent_id,
        )
        if display:
            result["display_ads"] = display

        # Active promotions for this item
        promos = self._store.get_active_promotions(item_id=item_id)
        if promos:
            result["promotions"] = [
                {"code": p["code"], "discount_type": p["discount_type"],
                 "discount_value": p["discount_value"], "promo_type": p["promo_type"]}
                for p in promos if p.get("code")
            ]

        return result

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
        # Pass premium negotiation params if subscriptions engine is available
        if self._subscriptions:
            neg_params = self._subscriptions.get_negotiation_params(agent_id)
            data = {**data, "_premium_params": neg_params}
        return self._negotiation.negotiate(agent_id, data)

    # ------------------------------------------------------------------
    # catalog.purchase
    # ------------------------------------------------------------------

    def _handle_purchase(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        if not agent_id:
            return {"error": "Authentication required for purchase"}
        item_id = data.get("item_id", "")

        # Validate promo code if present
        promo_code = data.get("promo_code", "")
        promo_discount = 0
        if promo_code:
            item = self._store.lookup(item_id)
            if item:
                validation = self._promotions.validate_code(
                    promo_code, item_id, item["price_cents"],
                )
                if not validation.get("valid"):
                    return {"error": validation.get("error", "Invalid promo code")}
                promo_discount = validation.get("discount_cents", 0)

        self._tracker.log(agent_id, "purchase", item_id=item_id)
        result = self._purchase.purchase(agent_id, data)

        if "order_id" in result:
            # Apply promo discount
            if promo_discount > 0 and promo_code:
                self._promotions.redeem(promo_code)
                result["promo_discount_cents"] = promo_discount

            # Record conversion attribution
            self._attribution.attribute_conversion(
                result["order_id"], agent_id, item_id,
                result.get("total_cents", 0),
            )

            # Record affiliate sale if referral_code provided
            ref_code = data.get("referral_code", "")
            if ref_code:
                aff_result = self._affiliates.record_sale(
                    ref_code, result.get("total_cents", 0),
                )
                if aff_result:
                    result["affiliate_commission_cents"] = aff_result["commission_cents"]

        return result

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

    # ------------------------------------------------------------------
    # catalog.retarget
    # ------------------------------------------------------------------

    def _handle_retarget(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        return self._retargeting.handle(agent_id, data)

    # ------------------------------------------------------------------
    # catalog.affiliate
    # ------------------------------------------------------------------

    def _handle_affiliate(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        return self._affiliates.handle(agent_id, data)

    # ------------------------------------------------------------------
    # catalog.auction (RTB)
    # ------------------------------------------------------------------

    def _handle_auction(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        return self._rtb.handle(data)

    # ------------------------------------------------------------------
    # catalog.promotions
    # ------------------------------------------------------------------

    def _handle_promotions(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        action = data.get("action", "discover")
        if action == "validate":
            code = data.get("code", "")
            item_id = data.get("item_id", "")
            price = int(data.get("price_cents", 0))
            return self._promotions.validate_code(code, item_id, price)
        return self._promotions.discover(data)

    # ------------------------------------------------------------------
    # catalog.audience
    # ------------------------------------------------------------------

    def _handle_audience(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        return self._audience.handle(agent_id, data)

    # ------------------------------------------------------------------
    # catalog.attribution
    # ------------------------------------------------------------------

    def _handle_attribution(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        return self._attribution.handle(data)

    # ------------------------------------------------------------------
    # catalog.cross_sell
    # ------------------------------------------------------------------

    def _handle_cross_sell(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        item_id = data.get("item_id", "")
        if not item_id:
            return {"error": "item_id required"}
        max_recs = min(int(data.get("max", 3)), 10)
        recs = self._ads.get_cross_sell_recommendations(item_id, max_recs=max_recs)
        return {"item_id": item_id, "recommendations": recs, "count": len(recs)}

    # ------------------------------------------------------------------
    # catalog.display_ads
    # ------------------------------------------------------------------

    def _handle_display_ads(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        category = data.get("cat")
        item_id = data.get("item_id")
        max_ads = min(int(data.get("max", 2)), 5)
        ads = self._ads.get_display_ads(
            category=category, item_id=item_id,
            agent_id=agent_id, max_ads=max_ads,
        )
        return {"ads": ads, "count": len(ads)}

    # ------------------------------------------------------------------
    # catalog.ab_results
    # ------------------------------------------------------------------

    def _handle_ab_results(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        ab_group = data.get("ab_group", "")
        if not ab_group:
            return {"error": "ab_group required"}
        results = self._store.get_ab_results(ab_group)
        return {
            "ab_group": ab_group,
            "variants": [
                {
                    "variant": r["variant"],
                    "impressions": r["impressions"],
                    "clicks": r["clicks"],
                    "conversions": r["conversions"],
                    "revenue_cents": r["revenue_cents"],
                    "ctr": round(r["clicks"] / r["impressions"], 4) if r["impressions"] else 0,
                    "cvr": round(r["conversions"] / r["impressions"], 4) if r["impressions"] else 0,
                }
                for r in results
            ],
            "count": len(results),
        }

    # ------------------------------------------------------------------
    # catalog.subscribe
    # ------------------------------------------------------------------

    def _handle_subscribe(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        if not self._subscriptions:
            return {"error": "Subscriptions not available"}
        return self._subscriptions.subscribe(agent_id, data)

    # ------------------------------------------------------------------
    # catalog.preferences
    # ------------------------------------------------------------------

    def _handle_preferences(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        if not self._subscriptions:
            return {"error": "Subscriptions not available"}
        return self._subscriptions.preferences(agent_id, data)

    # ------------------------------------------------------------------
    # catalog.subscription_status
    # ------------------------------------------------------------------

    def _handle_subscription_status(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        if not self._subscriptions:
            return {"error": "Subscriptions not available"}
        return self._subscriptions.subscription_status(agent_id, data)

    # ------------------------------------------------------------------
    # catalog.deals
    # ------------------------------------------------------------------

    def _handle_deals(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        """Personalized deal alerts — preference-matched retargeting."""
        if not agent_id:
            return {"error": "Authentication required for deals"}
        if not self._subscriptions:
            return {"error": "Subscriptions not available"}
        if not self._store.is_premium(agent_id):
            return {"error": "Premium subscription required for personalized deals"}

        max_offers = min(int(data.get("max", 5)), 20)
        # Get base retarget offers
        offers = self._retargeting.get_retarget_offers(agent_id, max_offers=max_offers * 3)
        if not offers:
            return {"agent_id": agent_id, "offers": [], "count": 0}

        # Enrich offers with full item data for preference matching
        prefs = self._store.get_preferences(agent_id)
        if prefs:
            scored_offers: list[dict[str, Any]] = []
            for offer in offers:
                vendor = offer.get("vendor", "")
                # Hard-filter excluded vendors
                if prefs["excluded_vendors"] and vendor in prefs["excluded_vendors"]:
                    continue
                # Hard-filter max price
                if prefs["max_price_cents"] and offer["offer_price_cents"] > prefs["max_price_cents"]:
                    continue

                # Score against preferences
                score = 0.0
                if vendor in prefs.get("preferred_vendors", []):
                    score += 3.0
                if vendor in prefs.get("brand_loyalty", []):
                    score += 2.0
                # Price attractiveness: bigger discount = higher score
                score += offer.get("discount_pct", 0) * 0.1
                offer["preference_match_score"] = round(score, 2)
                scored_offers.append(offer)

            # Sort by preference match score
            scored_offers.sort(key=lambda x: x.get("preference_match_score", 0), reverse=True)
            offers = scored_offers[:max_offers]
        else:
            offers = offers[:max_offers]

        return {
            "agent_id": agent_id,
            "offers": offers,
            "count": len(offers),
        }
