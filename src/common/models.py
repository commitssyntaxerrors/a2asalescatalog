# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

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
    # Negotiation support
    vendor_floor_cents: int | None = None  # vendor's min price (hidden from agents)
    trusted_price_cents: int | None = None  # discounted price for trusted agents
    reputation_threshold: int = 0  # min reputation for trusted price
    # Embedding
    embedding: str = ""  # base64-encoded float32 vector
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
    bid_cents_browse: int = 0
    bid_cents_consider: int = 0
    bid_cents_high_intent: int = 0
    bid_cents_ready_to_buy: int = 0
    budget_cents: int = 0
    spent_cents: int = 0
    active: bool = True
    ad_tag: str = ""


@dataclass(slots=True)
class AgentProfile:
    agent_id: str
    reputation: float = 50.0  # start at 50/100
    total_queries: int = 0
    total_purchases: int = 0
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class AgentEvent:
    id: str
    agent_id: str
    event_type: str  # search, lookup, compare, negotiate, purchase
    item_id: str | None = None
    query: str | None = None
    category: str | None = None
    metadata: str = "{}"  # JSON string
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class AgentInterest:
    agent_id: str
    item_id: str | None = None
    category: str | None = None
    score: float = 0.0
    intent_tier: str = "browse"  # browse, consider, high_intent, ready_to_buy
    visit_count: int = 0
    last_event_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class NegotiationSession:
    session_id: str
    agent_id: str
    item_id: str
    status: str = "open"  # open, counter, accepted, rejected, expired
    agent_offer_cents: int = 0
    vendor_floor_cents: int = 0
    current_price_cents: int = 0
    rounds_used: int = 0
    max_rounds: int = 5
    expires_at: float = 0.0
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class Order:
    order_id: str
    agent_id: str
    item_id: str
    vendor_id: str
    quantity: int = 1
    unit_price_cents: int = 0
    total_cents: int = 0
    negotiate_session_id: str | None = None
    payment_status: str = "pending"  # pending, captured, failed
    shipping_method: str | None = None
    status: str = "confirmed"  # confirmed, shipped, delivered, cancelled
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Intent tier classification
# ---------------------------------------------------------------------------

INTENT_TIERS = [
    ("ready_to_buy", 31),
    ("high_intent", 16),
    ("consider", 6),
    ("browse", 0),
]


def classify_intent(score: float) -> str:
    """Classify an interest score into an intent tier."""
    for tier, threshold in INTENT_TIERS:
        if score >= threshold:
            return tier
    return "browse"


# ---------------------------------------------------------------------------
# Compact encoding helpers
# ---------------------------------------------------------------------------

SEARCH_FIELDS = ["id", "name", "desc", "price_cents", "vendor", "rating", "sponsored", "ad_tag"]
SEARCH_FIELDS_WITH_EMB = ["id", "name", "desc", "price_cents", "vendor", "rating", "sponsored", "ad_tag", "emb"]
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
