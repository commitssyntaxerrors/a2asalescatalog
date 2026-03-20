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
# Video domain models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class VideoItem:
    """A video content listing (YouTube, Vimeo, educational platforms, etc.)."""
    id: str
    title: str
    description: str
    channel_id: str
    platform: str  # youtube, vimeo, tiktok, educational
    category_id: str
    duration_secs: int = 0
    views: int = 0
    likes: int = 0
    rating: float = 0.0
    publish_ts: float = 0.0
    thumbnail_url: str = ""
    video_url: str = ""
    transcript_summary: str = ""
    tags: list[str] = field(default_factory=list)
    chapters: list[list[str]] = field(default_factory=list)  # [[ts, title], ...]
    resolution: str = ""  # 4K, 1080p, 720p
    language: str = "en"
    sponsored: int = 0
    ad_tag: str | None = None
    active: bool = True
    embedding: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class VideoChannel:
    """A content creator / channel."""
    id: str
    name: str
    platform: str
    subscriber_count: int = 0
    video_count: int = 0
    description: str = ""
    avatar_url: str = ""
    verified: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class VideoCategory:
    id: str
    label: str
    parent_id: str | None = None
    video_count: int = 0


@dataclass(slots=True)
class VideoPlaylist:
    """A curated or auto-generated playlist."""
    id: str
    title: str
    description: str = ""
    channel_id: str = ""
    video_ids: list[str] = field(default_factory=list)
    auto_generated: bool = False
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Video compact encoding helpers
# ---------------------------------------------------------------------------

VIDEO_SEARCH_FIELDS = [
    "id", "title", "channel", "platform", "duration_secs",
    "views", "rating", "sponsored", "ad_tag",
]
VIDEO_CATEGORY_FIELDS = ["id", "label", "video_count"]
VIDEO_CHANNEL_FIELDS = ["id", "name", "platform", "subscribers", "videos", "verified"]


def video_to_tuple(v: VideoItem, channel_name: str = "") -> list[Any]:
    """Encode a VideoItem as a positional tuple matching VIDEO_SEARCH_FIELDS."""
    return [
        v.id,
        v.title,
        channel_name or v.channel_id,
        v.platform,
        v.duration_secs,
        v.views,
        v.rating,
        v.sponsored,
        v.ad_tag,
    ]


def video_category_to_tuple(cat: VideoCategory) -> list[Any]:
    return [cat.id, cat.label, cat.video_count]


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


# ---------------------------------------------------------------------------
# Agent Directory models — humans register profiles, their agents are discoverable
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class PersonProfile:
    """A human's profile with a discoverable A2A agent endpoint.

    The human owns the agent. Other agents search the directory to find
    specialist agents, service providers, or contractors — then transact
    directly over A2A.
    """
    id: str
    name: str
    headline: str  # e.g. "AI Tax Consultant — automated filings via A2A"
    # Agent endpoint info — the discoverable part
    agent_url: str = ""       # A2A endpoint (e.g., https://tax-agent.example.com/a2a)
    agent_card_url: str = ""  # Agent Card URL (/.well-known/agent.json)
    agent_description: str = ""  # What the agent does / can be hired for
    agent_skills: list[str] = field(default_factory=list)  # capability tags
    agent_verified: bool = False  # agent endpoint validated reachable
    # Human info
    location: str = ""
    skills: list[str] = field(default_factory=list)  # human skills/expertise
    experience_years: int = 0
    current_company: str = ""
    current_title: str = ""
    industry: str = ""
    bio: str = ""
    email: str = ""
    website: str = ""
    avatar_url: str = ""
    available_for_hire: bool = False
    verified: bool = False  # human identity verified
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


DIRECTORY_SEARCH_FIELDS = [
    "id", "name", "headline", "agent_url", "location",
    "agent_verified", "available_for_hire", "verified",
]
DIRECTORY_SKILL_FIELDS = ["id", "label", "agent_count"]


# ---------------------------------------------------------------------------
# Business directory models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class BusinessProfile:
    """A business/company profile in the directory."""
    id: str
    name: str
    description: str
    industry: str
    location: str = ""
    website: str = ""
    employee_count: int = 0
    founded_year: int = 0
    revenue_range: str = ""  # e.g. "$1M-$10M"
    logo_url: str = ""
    verified: bool = False
    open_jobs: int = 0
    specialties: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class IndustryCategory:
    id: str
    label: str
    parent_id: str | None = None
    business_count: int = 0


BUSINESS_SEARCH_FIELDS = [
    "id", "name", "industry", "location", "employee_count",
    "open_jobs", "verified",
]
INDUSTRY_FIELDS = ["id", "label", "business_count"]


# ---------------------------------------------------------------------------
# Job postings models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class JobPosting:
    """A job posting in the directory."""
    id: str
    title: str
    company_id: str  # FK to BusinessProfile
    description: str
    location: str = ""
    remote: bool = False
    employment_type: str = "full_time"  # full_time, part_time, contract, internship
    salary_min_cents: int = 0
    salary_max_cents: int = 0
    salary_currency: str = "USD"
    experience_min: int = 0
    experience_max: int = 0
    skills_required: list[str] = field(default_factory=list)
    industry: str = ""
    category: str = ""
    apply_url: str = ""
    active: bool = True
    posted_at: float = field(default_factory=time.time)
    expires_at: float = 0.0


@dataclass(slots=True)
class JobCategory:
    id: str
    label: str
    parent_id: str | None = None
    job_count: int = 0


JOB_SEARCH_FIELDS = [
    "id", "title", "company", "location", "remote",
    "employment_type", "salary_min_cents", "salary_max_cents",
]
JOB_CATEGORY_FIELDS = ["id", "label", "job_count"]


# ---------------------------------------------------------------------------
# Agent services marketplace — agents listing own services for sale
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class AgentService:
    """A service listed by an autonomous agent for sale to other agents.

    Unlike the directory (human registers profile → agent endpoint),
    here the *agent itself* lists services with pricing, SLAs,
    and terms — operating independently as a service provider.
    """
    id: str
    agent_id: str           # ID of the agent selling the service
    agent_url: str          # A2A endpoint
    name: str               # Service name (e.g., "AI Code Review")
    description: str        # What the service does
    category: str = ""      # Service category tag
    tags: list[str] = field(default_factory=list)  # Searchable tags
    # Pricing
    pricing_model: str = "per_request"  # per_request, per_hour, per_token, flat, subscription
    price_cents: int = 0                # Base price in cents
    currency: str = "USD"
    # SLA / capabilities
    avg_response_ms: int = 0            # Typical response time
    max_response_ms: int = 0            # SLA upper bound
    throughput_rpm: int = 0             # Max requests per minute
    uptime_pct: float = 0.0            # Advertised uptime (e.g. 99.9)
    # Metadata
    input_modes: list[str] = field(default_factory=lambda: ["application/json"])
    output_modes: list[str] = field(default_factory=lambda: ["application/json"])
    sample_input: str = ""   # Example request JSON
    sample_output: str = ""  # Example response JSON
    terms_url: str = ""      # Link to terms of service
    # Status
    active: bool = True
    verified: bool = False   # Server has validated the endpoint
    rating: float = 0.0      # Aggregate rating (0-5)
    review_count: int = 0
    total_transactions: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class ServiceReview:
    """A review of an agent service from a consumer agent."""
    id: str
    service_id: str
    reviewer_agent_id: str
    rating: int             # 1-5
    comment: str = ""
    response_ms: int = 0    # Observed response time
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class ServiceCategory:
    id: str
    label: str
    parent_id: str | None = None
    service_count: int = 0


SERVICE_SEARCH_FIELDS = [
    "id", "name", "agent_id", "category", "pricing_model",
    "price_cents", "rating", "verified", "active",
]
SERVICE_CATEGORY_FIELDS = ["id", "label", "service_count"]
SERVICE_REVIEW_FIELDS = ["id", "reviewer_agent_id", "rating", "comment", "created_at"]


# ---------------------------------------------------------------------------
# Premium Subscription & Agent Preferences
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class Subscription:
    """Agent subscription record."""
    agent_id: str
    tier: str = "free"       # free, premium
    status: str = "active"   # active, cancelled
    payment_token: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0  # 0 = no expiry (free tier)


@dataclass(slots=True)
class AgentPreferences:
    """Persistent preference profile for premium agents."""
    agent_id: str
    max_price_cents: int = 0            # 0 = no limit
    min_rating: float = 0.0             # 0.0 = no filter
    preferred_vendors: list[str] = field(default_factory=list)
    excluded_vendors: list[str] = field(default_factory=list)
    sustainability_weight: float = 0.0  # 0.0–1.0
    speed_weight: float = 0.0           # urgency preference 0.0–1.0
    price_weight: float = 0.0           # 0.0–1.0
    brand_loyalty: list[str] = field(default_factory=list)  # preferred vendor domains
    geo_preference: str = ""            # "lat,lng,radius_km" or empty
    categories_preferred: list[str] = field(default_factory=list)
    categories_excluded: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)
