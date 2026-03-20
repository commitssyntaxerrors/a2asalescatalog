"""A2A Sales Catalog — common data models."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Catalog domain models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CatalogItem:
    id: str
    name: str
    desc: str
    price_cents: int
    currency: str
    vendor_id: str
    category_id: str
    rating: float = 0.0
    review_count: int = 0
    attrs: list[list[str]] = field(default_factory=list)
    buy_url: str = ""
    images: list[str] = field(default_factory=list)
    sponsored: int = 0  # 0 or 1
    ad_tag: str | None = None
    active: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class Vendor:
    id: str
    name: str
    domain: str
    verified: bool = False
    tier: str = "free"


@dataclass(slots=True)
class Category:
    id: str
    label: str
    parent_id: str | None = None
    item_count: int = 0


@dataclass(slots=True)
class AdCampaign:
    id: str
    vendor_id: str
    keywords: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    bid_cents: int = 0
    budget_cents: int = 0
    spent_cents: int = 0
    active: bool = True
    ad_tag: str = ""


# ---------------------------------------------------------------------------
# Compact encoding helpers
# ---------------------------------------------------------------------------

SEARCH_FIELDS = ["id", "name", "desc", "price_cents", "vendor", "rating", "sponsored", "ad_tag"]
CATEGORY_FIELDS = ["id", "label", "item_count"]


def item_to_tuple(item: CatalogItem, vendor_domain: str = "") -> list[Any]:
    """Encode a CatalogItem as a positional tuple matching SEARCH_FIELDS."""
    return [
        item.id,
        item.name,
        item.desc,
        item.price_cents,
        vendor_domain or item.vendor_id,
        item.rating,
        item.sponsored,
        item.ad_tag,
    ]


def category_to_tuple(cat: Category) -> list[Any]:
    """Encode a Category as a positional tuple matching CATEGORY_FIELDS."""
    return [cat.id, cat.label, cat.item_count]
