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
    # Display ad support
    promo_headline: str = ""
    promo_body: str = ""
    promo_image_url: str = ""
    promo_type: str = "search"  # search, display, retarget, cross_sell
    # Frequency capping
    freq_cap_count: int = 0  # 0 = unlimited
    freq_cap_window_secs: int = 3600
    # A/B testing
    ab_variant: str = ""  # variant label (e.g., "A", "B")
    ab_group: str = ""  # test group identifier
    # Creative rotation
    creatives: list[str] = field(default_factory=list)  # JSON list of creative dicts
    creative_weights: list[float] = field(default_factory=list)
    # Campaign scheduling / dayparting
    schedule_start: float = 0.0  # unix timestamp, 0 = always
    schedule_end: float = 0.0
    schedule_hours: list[int] = field(default_factory=list)  # hours of day (0-23)
    schedule_days: list[int] = field(default_factory=list)   # days of week (0=Mon, 6=Sun)
    # Audience targeting
    target_segments: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DisplayAd:
    """A structured promotional block injected into non-search responses."""
    campaign_id: str
    vendor_id: str
    headline: str
    body: str
    image_url: str = ""
    item_id: str = ""
    ad_tag: str = ""
    creative_variant: str = ""


@dataclass(slots=True)
class RetargetOffer:
    """A retargeting offer for an agent who viewed but didn't purchase."""
    agent_id: str
    item_id: str
    item_name: str
    original_price_cents: int
    offer_price_cents: int
    discount_pct: float
    expires_at: float = 0.0
    campaign_id: str = ""


@dataclass(slots=True)
class AffiliateLink:
    """Tracks referral commissions between agents."""
    referral_code: str
    referring_agent_id: str
    vendor_id: str
    commission_bps: int = 500  # basis points (5% default)
    total_referrals: int = 0
    total_earned_cents: int = 0
    active: bool = True
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class AuctionBid:
    """A single bid in a real-time bidding auction."""
    campaign_id: str
    vendor_id: str
    bid_cents: int
    ad_tag: str = ""
    item_id: str = ""


@dataclass(slots=True)
class FrequencyRecord:
    """Tracks how many times an agent has seen a specific campaign."""
    agent_id: str
    campaign_id: str
    impressions: int = 0
    window_start: float = field(default_factory=time.time)


@dataclass(slots=True)
class ABTestResult:
    """Aggregated A/B test variant metrics."""
    ab_group: str
    variant: str
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0
    revenue_cents: int = 0


@dataclass(slots=True)
class AgentSegment:
    """Behavioral audience segment for agent targeting."""
    segment_id: str
    label: str
    description: str = ""
    criteria: str = "{}"  # JSON criteria definition
    agent_count: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class AgentSegmentMembership:
    """Maps agents to audience segments."""
    agent_id: str
    segment_id: str
    confidence: float = 1.0
    assigned_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class TouchPoint:
    """A single touchpoint in a conversion attribution chain."""
    agent_id: str
    event_id: str
    event_type: str  # search, lookup, compare, ad_impression, ad_click
    campaign_id: str = ""
    item_id: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class ConversionAttribution:
    """Attribution record linking a purchase to ad touchpoints."""
    order_id: str
    agent_id: str
    item_id: str
    touchpoints: int = 0
    first_touch_campaign: str = ""
    last_touch_campaign: str = ""
    attributed_revenue_cents: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class Promotion:
    """Time-limited discount / deal / coupon."""
    promo_id: str
    vendor_id: str
    item_id: str = ""  # empty = vendor-wide
    code: str = ""
    discount_type: str = "percent"  # percent, fixed_cents
    discount_value: int = 0  # percent (e.g., 10) or cents
    min_price_cents: int = 0
    max_uses: int = 0  # 0 = unlimited
    used_count: int = 0
    starts_at: float = 0.0
    expires_at: float = 0.0
    active: bool = True
    bundle_item_ids: list[str] = field(default_factory=list)
    promo_type: str = "coupon"  # coupon, flash_sale, bundle


@dataclass(slots=True)
class CrossSellRule:
    """Defines cross-sell / upsell relationships between items."""
    source_item_id: str
    target_item_id: str
    relation_type: str = "cross_sell"  # cross_sell, upsell
    vendor_id: str = ""
    bid_cents: int = 0  # vendor pays for recommendation
    priority: int = 0


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
