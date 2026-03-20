"""A2A Sales Catalog — Skill handlers.

Each skill maps to a function that takes the request data dict
and returns the response data dict (compact tuple format).
"""

from __future__ import annotations

import json
from typing import Any

from src.common.models import CATEGORY_FIELDS, SEARCH_FIELDS
from src.server.ads import AdEngine
from src.server.store import CatalogStore

COMPARE_BASE_FIELDS = ["id", "name", "price_cents", "rating", "review_count"]


class SkillRouter:
    """Dispatches A2A skill invocations to handler methods."""

    def __init__(self, store: CatalogStore, ad_engine: AdEngine) -> None:
        self._store = store
        self._ads = ad_engine
        self._handlers = {
            "catalog.search": self._handle_search,
            "catalog.lookup": self._handle_lookup,
            "catalog.categories": self._handle_categories,
            "catalog.compare": self._handle_compare,
        }

    def handle(self, data: dict[str, Any]) -> dict[str, Any]:
        skill = data.get("skill", "")
        handler = self._handlers.get(skill)
        if not handler:
            return {"error": f"Unknown skill: {skill}"}
        return handler(data)

    # ------------------------------------------------------------------
    # catalog.search
    # ------------------------------------------------------------------

    def _handle_search(self, data: dict[str, Any]) -> dict[str, Any]:
        q = str(data.get("q", ""))
        limit = min(int(data.get("max", 10)), 50)
        cat = data.get("cat")
        price_min = data.get("price_min")
        price_max = data.get("price_max")
        sort = data.get("sort", "relevance")
        vendor = data.get("vendor")

        organic = self._store.search(
            q,
            category=cat,
            vendor=vendor,
            price_min=price_min,
            price_max=price_max,
            sort=sort,
            limit=limit,
        )

        merged = self._ads.inject_sponsored(organic, q, cat, limit)

        # Encode as compact tuples
        items = []
        for row in merged:
            items.append([
                row["id"],
                row["name"],
                row["desc"],
                row["price_cents"],
                row.get("vendor_domain", row["vendor_id"]),
                row["rating"],
                row["sponsored"],
                row.get("ad_tag"),
            ])

        return {
            "fields": SEARCH_FIELDS,
            "items": items,
            "currency": "USD",
            "total": len(items),
        }

    # ------------------------------------------------------------------
    # catalog.lookup
    # ------------------------------------------------------------------

    def _handle_lookup(self, data: dict[str, Any]) -> dict[str, Any]:
        item_id = str(data.get("id", ""))
        row = self._store.lookup(item_id)
        if not row:
            return {"error": f"Item not found: {item_id}"}

        attrs = json.loads(row["attrs"]) if isinstance(row["attrs"], str) else row["attrs"]
        images = json.loads(row["images"]) if isinstance(row["images"], str) else row["images"]

        return {
            "id": row["id"],
            "name": row["name"],
            "desc": row["desc"],
            "price_cents": row["price_cents"],
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

    def _handle_categories(self, data: dict[str, Any]) -> dict[str, Any]:
        parent = data.get("parent")
        cats = self._store.list_categories(parent)
        return {
            "fields": CATEGORY_FIELDS,
            "cats": [[c["id"], c["label"], c["item_count"]] for c in cats],
        }

    # ------------------------------------------------------------------
    # catalog.compare
    # ------------------------------------------------------------------

    def _handle_compare(self, data: dict[str, Any]) -> dict[str, Any]:
        ids = data.get("ids", [])
        if not ids or len(ids) < 2:
            return {"error": "Provide at least 2 item IDs to compare"}

        rows = self._store.get_items_by_ids(ids)
        if not rows:
            return {"error": "No items found for the given IDs"}

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
