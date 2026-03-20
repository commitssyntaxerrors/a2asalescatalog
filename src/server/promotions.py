# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Promotional campaigns — coupons, flash sales, bundles.

Time-limited discount codes and deals that agents can discover and
apply to purchases. Agent-discoverable deals with structured
redemption protocol.
"""

from __future__ import annotations

import json
import time
from typing import Any

from src.common.models import Promotion
from src.server.store import CatalogStore


class PromotionEngine:
    """Manages promotional campaigns, deals, and coupon validation."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def discover(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle catalog.promotions skill — discover active promotions."""
        vendor_id = data.get("vendor_id", "")
        item_id = data.get("item_id", "")

        promos = self._store.get_active_promotions(
            vendor_id=vendor_id, item_id=item_id,
        )

        results = []
        for p in promos:
            bundle = json.loads(p["bundle_item_ids"]) if isinstance(p["bundle_item_ids"], str) else p["bundle_item_ids"]
            results.append({
                "promo_id": p["promo_id"],
                "vendor_id": p["vendor_id"],
                "code": p["code"],
                "promo_type": p["promo_type"],
                "discount_type": p["discount_type"],
                "discount_value": p["discount_value"],
                "item_id": p["item_id"] or None,
                "min_price_cents": p["min_price_cents"],
                "expires_at": p["expires_at"],
                "bundle_items": bundle if bundle else None,
                "remaining_uses": (p["max_uses"] - p["used_count"]) if p["max_uses"] else None,
            })

        return {
            "promotions": results,
            "count": len(results),
        }

    def validate_code(self, code: str, item_id: str,
                      price_cents: int) -> dict[str, Any]:
        """Validate a promo code and calculate the discount."""
        promo = self._store.get_promotion_by_code(code)
        if not promo:
            return {"valid": False, "error": "Invalid or expired promo code"}

        now = time.time()
        if promo["expires_at"] and now > promo["expires_at"]:
            return {"valid": False, "error": "Promo code has expired"}
        if promo["starts_at"] and now < promo["starts_at"]:
            return {"valid": False, "error": "Promo code not yet active"}
        if promo["max_uses"] and promo["used_count"] >= promo["max_uses"]:
            return {"valid": False, "error": "Promo code fully redeemed"}
        if promo["item_id"] and promo["item_id"] != item_id:
            return {"valid": False, "error": "Promo code not valid for this item"}
        if price_cents < promo["min_price_cents"]:
            return {"valid": False, "error": f"Minimum purchase {promo['min_price_cents']} cents"}

        # Calculate discount
        if promo["discount_type"] == "percent":
            discount = int(price_cents * promo["discount_value"] / 100)
        else:
            discount = promo["discount_value"]

        discount = min(discount, price_cents)  # can't discount more than price
        final_price = price_cents - discount

        return {
            "valid": True,
            "promo_id": promo["promo_id"],
            "discount_cents": discount,
            "final_price_cents": final_price,
            "discount_type": promo["discount_type"],
            "discount_value": promo["discount_value"],
        }

    def redeem(self, code: str) -> None:
        """Mark a promo code as used (increment usage count)."""
        promo = self._store.get_promotion_by_code(code)
        if promo:
            self._store.increment_promo_usage(promo["promo_id"])
