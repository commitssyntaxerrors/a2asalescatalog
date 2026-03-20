# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""A2A Sales Catalog — A2A protocol server.

Exposes the catalog as an A2A-compliant agent over HTTP.
Uses Starlette for minimal overhead.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

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
from src.server.skills import SkillRouter
from src.server.store import CatalogStore
from src.server.vendor_analytics import VendorAnalytics
from src.server.video_skills import VideoSkillRouter
from src.server.directory_skills import DirectorySkillRouter
from src.server.business_skills import BusinessSkillRouter
from src.server.jobs_skills import JobsSkillRouter
from src.server.services_skills import ServicesSkillRouter

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("CATALOG_DB", ":memory:")
API_KEYS: dict[str, str] = {}  # key -> agent_id mapping
_raw_keys = os.environ.get("CATALOG_API_KEYS", "")
for _k in filter(None, _raw_keys.split(",")):
    # Format: "key" or "key:agent_id"
    if ":" in _k:
        _key, _aid = _k.split(":", 1)
        API_KEYS[_key] = _aid
    else:
        API_KEYS[_k] = _k  # use key as agent_id if no explicit mapping
AGENT_CARD_PATH = Path(__file__).resolve().parent.parent.parent / "schemas" / "agent-card.json"

# ---------------------------------------------------------------------------
# Globals (initialized in lifespan)
# ---------------------------------------------------------------------------

store: CatalogStore | None = None
router: SkillRouter | None = None
video_router: VideoSkillRouter | None = None
directory_router: DirectorySkillRouter | None = None
business_router: BusinessSkillRouter | None = None
jobs_router: JobsSkillRouter | None = None
services_router: ServicesSkillRouter | None = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    global store, router, video_router, directory_router, business_router, jobs_router, services_router
    store = CatalogStore(DB_PATH)
    ad_engine = AdEngine(store)
    tracker = AgentTracker(store)
    negotiation = NegotiationEngine(store)
    purchase = PurchaseEngine(store)
    federation = FederationManager(store)
    embeddings = EmbeddingIndex(store)
    analytics = VendorAnalytics(store)
    retargeting = RetargetingEngine(store)
    affiliates = AffiliateEngine(store)
    rtb = RTBEngine(store)
    promotions = PromotionEngine(store)
    audience = AudienceEngine(store)
    attribution = AttributionEngine(store)
    router = SkillRouter(
        store, ad_engine, tracker, negotiation, purchase,
        federation, embeddings, analytics,
        retargeting, affiliates, rtb, promotions, audience, attribution,
    )
    video_router = VideoSkillRouter(store)
    directory_router = DirectorySkillRouter(store)
    business_router = BusinessSkillRouter(store)
    jobs_router = JobsSkillRouter(store)
    services_router = ServicesSkillRouter(store)

    # Seed demo data if empty
    if not store.list_categories():
        _seed_demo_data(store)

    yield  # app runs


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _check_auth(request: Request) -> bool:
    """Validate API key if keys are configured."""
    if not API_KEYS:
        return True  # No keys configured = open access (dev mode)
    key = request.headers.get("authorization", "").removeprefix("Bearer ")
    return key in API_KEYS


def _extract_agent_id(request: Request) -> str:
    """Extract agent_id from the API key. Returns '' for unauthenticated/dev."""
    if not API_KEYS:
        return "dev-agent"  # Dev mode default
    key = request.headers.get("authorization", "").removeprefix("Bearer ")
    return API_KEYS.get(key, "")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def agent_card(request: Request) -> JSONResponse:
    """Serve the A2A Agent Card at /.well-known/agent.json."""
    card = json.loads(AGENT_CARD_PATH.read_text())
    return JSONResponse(card)


async def a2a_endpoint(request: Request) -> JSONResponse:
    """Main A2A JSON-RPC endpoint."""
    if not _check_auth(request):
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Unauthorized"}},
            status_code=401,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )

    rpc_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    agent_id = _extract_agent_id(request)

    if method == "tasks/send":
        return _handle_task_send(rpc_id, params, agent_id)
    elif method == "tasks/get":
        return _handle_task_get(rpc_id, params)
    else:
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        })


def _handle_task_send(rpc_id: Any, params: dict, agent_id: str = "") -> JSONResponse:
    """Process a tasks/send request — extract skill data and dispatch."""
    task_id = params.get("id", str(uuid.uuid4()))
    message = params.get("message", {})
    parts = message.get("parts", [])

    # Find the data part with the skill invocation
    skill_data: dict[str, Any] | None = None
    for part in parts:
        if part.get("type") == "data" and isinstance(part.get("data"), dict):
            skill_data = part["data"]
            break

    if not skill_data or "skill" not in skill_data:
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32602, "message": "Missing skill data in message parts"},
        })

    # Check if client requested AXON format
    use_axon = str(skill_data.pop("format", "")).lower() == "axon"

    # Dispatch to the correct router
    skill_name = skill_data.get("skill", "")
    assert router is not None
    assert video_router is not None
    assert directory_router is not None
    assert business_router is not None
    assert jobs_router is not None
    assert services_router is not None
    if video_router.can_handle(skill_name):
        result_data = video_router.handle(skill_data, agent_id=agent_id)
    elif directory_router.can_handle(skill_name):
        result_data = directory_router.handle(skill_data, agent_id=agent_id)
    elif business_router.can_handle(skill_name):
        result_data = business_router.handle(skill_data, agent_id=agent_id)
    elif jobs_router.can_handle(skill_name):
        result_data = jobs_router.handle(skill_data, agent_id=agent_id)
    elif services_router.can_handle(skill_name):
        result_data = services_router.handle(skill_data, agent_id=agent_id)
    else:
        result_data = router.handle(skill_data, agent_id=agent_id)

    if "error" in result_data:
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "id": task_id,
                "status": {"state": "failed", "message": result_data["error"]},
            },
        })

    # AXON encoding: return as text part instead of data part
    if use_axon:
        from src.common.axon import encode_response
        axon_text = encode_response(result_data)
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "id": task_id,
                "status": {"state": "completed"},
                "artifacts": [{"parts": [{"type": "text", "text": axon_text}]}],
            },
        })

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "id": task_id,
            "status": {"state": "completed"},
            "artifacts": [{"parts": [{"type": "data", "data": result_data}]}],
        },
    })


def _handle_task_get(rpc_id: Any, params: dict) -> JSONResponse:
    """Stub for tasks/get — stateless server, tasks are not persisted."""
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": rpc_id,
        "error": {"code": -32602, "message": "Stateless server — use tasks/send"},
    })


# ---------------------------------------------------------------------------
# Demo seed data
# ---------------------------------------------------------------------------

def _seed_demo_data(s: CatalogStore) -> None:
    """Populate the store with sample data for development."""
    from src.common.models import (
        AdCampaign, CatalogItem, Category, CrossSellRule, Promotion, Vendor,
    )

    # Vendors
    vendors = [
        Vendor("v-soundpod", "SoundPod", "soundpod.com", True, "pro"),
        Vendor("v-bassx", "BassX Audio", "bassx.io", True, "free"),
        Vendor("v-clearair", "ClearAir Tech", "clearair.co", True, "free"),
        Vendor("v-deskco", "DeskCo", "deskco.com", False, "free"),
    ]
    for v in vendors:
        s.upsert_vendor(v)

    # Categories
    cats = [
        Category("electronics", "Electronics", None, 3),
        Category("audio", "Audio", "electronics", 3),
        Category("furniture", "Furniture", None, 1),
    ]
    for c in cats:
        s.upsert_category(c)

    # Items
    items = [
        CatalogItem(
            "WE-001", "SoundPod Pro",
            "Wireless earbuds with ANC and 30h battery life",
            4999, "USD", "v-soundpod", "audio",
            4.6, 2847,
            [["battery", "30h"], ["driver", "12mm"], ["anc", "yes"], ["water", "IPX4"]],
            "https://soundpod.com/pro?ref=a2acat",
            ["https://cdn.example.com/we001.webp"],
        ),
        CatalogItem(
            "WE-002", "BassX Buds",
            "Wireless earbuds with deep bass and IPX5 water resistance",
            3499, "USD", "v-bassx", "audio",
            4.3, 1203,
            [["battery", "20h"], ["driver", "10mm"], ["anc", "no"], ["water", "IPX5"]],
            "https://bassx.io/buds?ref=a2acat",
            ["https://cdn.example.com/we002.webp"],
        ),
        CatalogItem(
            "WE-003", "ClearAir S1",
            "Premium wireless earbuds with spatial audio and 40h battery",
            5999, "USD", "v-clearair", "audio",
            4.8, 4102,
            [["battery", "40h"], ["driver", "11mm"], ["anc", "yes"], ["water", "IPX4"]],
            "https://clearair.co/s1?ref=a2acat",
            ["https://cdn.example.com/we003.webp"],
        ),
        CatalogItem(
            "FN-001", "ErgoDesk Pro",
            "Electric standing desk with memory presets",
            49900, "USD", "v-deskco", "furniture",
            4.5, 890,
            [["width", "60in"], ["height_min", "25in"], ["height_max", "50in"], ["motor", "dual"]],
            "https://deskco.com/ergodesk?ref=a2acat",
            ["https://cdn.example.com/fn001.webp"],
        ),
    ]
    for item in items:
        s.upsert_item(item)

    # Demo ad campaign with intent-tiered bids
    s.upsert_campaign(AdCampaign(
        "ad-001", "v-soundpod",
        keywords=["earbuds", "headphones", "wireless", "audio"],
        categories=["audio", "electronics"],
        bid_cents=50,
        bid_cents_browse=10,
        bid_cents_consider=30,
        bid_cents_high_intent=80,
        bid_cents_ready_to_buy=150,
        budget_cents=100000,
        spent_cents=0,
        active=True,
        ad_tag="sp",
    ))

    # Demo promotion — 10% off earbuds
    import time as _t
    s.upsert_promotion(Promotion(
        promo_id="promo-001",
        vendor_id="v-soundpod",
        item_id="WE-001",
        code="SOUND10",
        discount_type="percent",
        discount_value=10,
        starts_at=_t.time() - 86400,
        expires_at=_t.time() + 86400 * 30,
        promo_type="coupon",
    ))

    # Demo cross-sell rules
    s.upsert_cross_sell(CrossSellRule(
        source_item_id="WE-001",
        target_item_id="WE-003",
        relation_type="upsell",
        vendor_id="v-clearair",
        bid_cents=20,
        priority=10,
    ))
    s.upsert_cross_sell(CrossSellRule(
        source_item_id="WE-002",
        target_item_id="WE-001",
        relation_type="cross_sell",
        vendor_id="v-soundpod",
        bid_cents=15,
        priority=5,
    ))

    # ---------------------------------------------------------------
    # Video seed data
    # ---------------------------------------------------------------
    from src.common.models import VideoCategory, VideoChannel, VideoItem, VideoPlaylist

    # Video channels
    video_channels = [
        VideoChannel("ch-techrev", "TechReviewer", "youtube", 2_400_000, 342,
                     "In-depth tech product reviews and comparisons",
                     verified=True),
        VideoChannel("ch-codeschool", "CodeSchool", "youtube", 890_000, 215,
                     "Programming tutorials and software engineering",
                     verified=True),
        VideoChannel("ch-ailab", "AI Lab", "youtube", 1_100_000, 178,
                     "AI research explainers and tutorials",
                     verified=True),
        VideoChannel("ch-cookpro", "Cook Pro", "youtube", 3_200_000, 520,
                     "Professional cooking tutorials and recipes",
                     verified=True),
        VideoChannel("ch-fitlife", "FitLife", "vimeo", 450_000, 98,
                     "Fitness workouts and nutrition guides"),
    ]
    for ch in video_channels:
        s.upsert_video_channel(ch)

    # Video categories
    video_cats = [
        VideoCategory("vid-tech", "Technology", None, 3),
        VideoCategory("vid-reviews", "Product Reviews", "vid-tech", 2),
        VideoCategory("vid-tutorials", "Tutorials", None, 3),
        VideoCategory("vid-programming", "Programming", "vid-tutorials", 2),
        VideoCategory("vid-ai", "Artificial Intelligence", "vid-tech", 1),
        VideoCategory("vid-cooking", "Cooking", None, 2),
        VideoCategory("vid-fitness", "Fitness", None, 1),
    ]
    for c in video_cats:
        s.upsert_video_category(c)

    # Video items
    videos = [
        VideoItem(
            "VID-001", "Best Wireless Earbuds 2026 — Top 5 Picks",
            "Comprehensive comparison of the best wireless earbuds available in 2026. "
            "We test sound quality, ANC, battery life, and comfort.",
            "ch-techrev", "youtube", "vid-reviews",
            duration_secs=1245, views=1_850_000, likes=92_000, rating=4.8,
            thumbnail_url="https://cdn.example.com/vid001-thumb.webp",
            video_url="https://youtube.com/watch?v=example001",
            transcript_summary="Comparison of 5 wireless earbuds: SoundPod Pro, BassX Buds, "
                               "ClearAir S1, and two others. SoundPod Pro wins for ANC, ClearAir S1 for battery.",
            tags=["earbuds", "wireless", "review", "comparison", "2026"],
            chapters=[["0:00", "Intro"], ["2:15", "Sound Quality"], ["8:30", "ANC Test"],
                      ["14:00", "Battery Life"], ["18:45", "Verdict"]],
            resolution="4K", language="en",
        ),
        VideoItem(
            "VID-002", "Building AI Agents with Python — Complete Guide",
            "Step-by-step tutorial on building autonomous AI agents using Python. "
            "Covers planning, tool use, memory, and multi-agent orchestration.",
            "ch-codeschool", "youtube", "vid-programming",
            duration_secs=3600, views=720_000, likes=48_000, rating=4.9,
            thumbnail_url="https://cdn.example.com/vid002-thumb.webp",
            video_url="https://youtube.com/watch?v=example002",
            transcript_summary="Full tutorial on building AI agents. Covers LangChain, "
                               "AutoGen, and custom agent frameworks. Includes code examples.",
            tags=["python", "ai", "agents", "tutorial", "programming"],
            chapters=[["0:00", "Intro"], ["5:00", "Agent Architecture"],
                      ["20:00", "Tool Integration"], ["45:00", "Multi-Agent Systems"]],
            resolution="1080p", language="en",
        ),
        VideoItem(
            "VID-003", "Transformer Architecture Explained Simply",
            "Clear explanation of the Transformer architecture, attention mechanisms, "
            "and why they power modern AI. No PhD required.",
            "ch-ailab", "youtube", "vid-ai",
            duration_secs=1800, views=2_100_000, likes=130_000, rating=4.7,
            thumbnail_url="https://cdn.example.com/vid003-thumb.webp",
            video_url="https://youtube.com/watch?v=example003",
            transcript_summary="Explains transformer architecture from scratch. Covers "
                               "self-attention, multi-head attention, positional encoding, "
                               "and decoder-only vs encoder-decoder models.",
            tags=["ai", "transformer", "deep-learning", "explainer"],
            chapters=[["0:00", "Why Transformers?"], ["3:00", "Self-Attention"],
                      ["12:00", "Multi-Head Attention"], ["22:00", "Modern LLMs"]],
            resolution="4K", language="en",
        ),
        VideoItem(
            "VID-004", "Perfect Homemade Pasta from Scratch",
            "Learn to make fresh pasta at home with just flour and eggs. "
            "Includes three sauce recipes.",
            "ch-cookpro", "youtube", "vid-cooking",
            duration_secs=960, views=4_500_000, likes=280_000, rating=4.9,
            thumbnail_url="https://cdn.example.com/vid004-thumb.webp",
            video_url="https://youtube.com/watch?v=example004",
            transcript_summary="Step by step pasta making guide. Covers egg pasta dough, "
                               "rolling techniques, and three classic sauces: cacio e pepe, "
                               "carbonara, and arrabbiata.",
            tags=["cooking", "pasta", "recipe", "italian", "homemade"],
            chapters=[["0:00", "Ingredients"], ["2:00", "Making Dough"],
                      ["8:00", "Rolling & Cutting"], ["12:00", "Three Sauces"]],
            resolution="4K", language="en",
        ),
        VideoItem(
            "VID-005", "30-Minute Full Body HIIT Workout",
            "High-intensity interval training for all fitness levels. "
            "No equipment needed.",
            "ch-fitlife", "vimeo", "vid-fitness",
            duration_secs=1800, views=890_000, likes=52_000, rating=4.6,
            thumbnail_url="https://cdn.example.com/vid005-thumb.webp",
            video_url="https://vimeo.com/example005",
            transcript_summary="30 minute HIIT workout. Warm-up, 6 rounds of high-intensity "
                               "exercises, cool-down stretches. Modifications shown for beginners.",
            tags=["fitness", "hiit", "workout", "no-equipment"],
            chapters=[["0:00", "Warm Up"], ["5:00", "Round 1"],
                      ["10:00", "Round 2-3"], ["20:00", "Round 4-6"],
                      ["27:00", "Cool Down"]],
            resolution="1080p", language="en",
        ),
        VideoItem(
            "VID-006", "SoundPod Pro — Detailed Review and Teardown",
            "Full review of the SoundPod Pro wireless earbuds including sound test, "
            "teardown, and comparison with competitors.",
            "ch-techrev", "youtube", "vid-reviews",
            duration_secs=2100, views=960_000, likes=61_000, rating=4.7,
            thumbnail_url="https://cdn.example.com/vid006-thumb.webp",
            video_url="https://youtube.com/watch?v=example006",
            transcript_summary="In-depth SoundPod Pro review. Tests ANC in multiple environments, "
                               "teardown shows 12mm driver and ANC chip. Compared to BassX and ClearAir.",
            tags=["soundpod", "earbuds", "review", "teardown"],
            chapters=[["0:00", "Unboxing"], ["3:00", "Sound Test"],
                      ["12:00", "ANC Test"], ["20:00", "Teardown"],
                      ["30:00", "Verdict"]],
            resolution="4K", language="en",
        ),
        VideoItem(
            "VID-007", "Python Async Programming — From Zero to Hero",
            "Master async/await in Python. Covers asyncio, aiohttp, "
            "and real-world patterns for concurrent programming.",
            "ch-codeschool", "youtube", "vid-programming",
            duration_secs=2700, views=410_000, likes=29_000, rating=4.8,
            thumbnail_url="https://cdn.example.com/vid007-thumb.webp",
            video_url="https://youtube.com/watch?v=example007",
            transcript_summary="Complete async Python course. Coroutines, event loops, "
                               "TaskGroups, aiohttp client/server, structured concurrency patterns.",
            tags=["python", "async", "asyncio", "programming", "tutorial"],
            chapters=[["0:00", "Why Async?"], ["5:00", "Coroutines Basics"],
                      ["15:00", "asyncio Deep Dive"], ["30:00", "Real World Patterns"]],
            resolution="1080p", language="en",
        ),
        VideoItem(
            "VID-008", "5 Japanese Recipes Every Home Cook Should Know",
            "Essential Japanese home cooking recipes: miso soup, "
            "tamagoyaki, onigiri, teriyaki, and gyudon.",
            "ch-cookpro", "youtube", "vid-cooking",
            duration_secs=1500, views=2_800_000, likes=175_000, rating=4.8,
            thumbnail_url="https://cdn.example.com/vid008-thumb.webp",
            video_url="https://youtube.com/watch?v=example008",
            transcript_summary="Five Japanese recipes: dashi-based miso soup, "
                               "tamagoyaki technique, onigiri shaping, teriyaki sauce from scratch, "
                               "and quick gyudon (beef bowl).",
            tags=["cooking", "japanese", "recipe", "miso", "teriyaki"],
            chapters=[["0:00", "Miso Soup"], ["5:00", "Tamagoyaki"],
                      ["10:00", "Onigiri"], ["15:00", "Teriyaki"],
                      ["20:00", "Gyudon"]],
            resolution="4K", language="en",
        ),
    ]
    for v in videos:
        s.upsert_video(v)

    # Video playlists
    playlists = [
        VideoPlaylist(
            "pl-001", "Best of Tech Reviews 2026",
            "Top tech product reviews of 2026",
            "ch-techrev",
            ["VID-001", "VID-006"],
        ),
        VideoPlaylist(
            "pl-002", "Learn Python from Scratch",
            "Complete Python learning path",
            "ch-codeschool",
            ["VID-002", "VID-007"],
        ),
    ]
    for pl in playlists:
        s.upsert_video_playlist(pl)

    # ---------------------------------------------------------------
    # Agent directory seed data
    # ---------------------------------------------------------------
    from src.common.models import (
        BusinessProfile, IndustryCategory, JobCategory, JobPosting, PersonProfile,
    )

    # Directory skill tags
    skill_tags = [
        ("sk-code-review", "Code Review", 0),
        ("sk-data-analysis", "Data Analysis", 0),
        ("sk-web-scraping", "Web Scraping", 0),
        ("sk-content-writing", "Content Writing", 0),
        ("sk-translation", "Translation", 0),
        ("sk-image-gen", "Image Generation", 0),
        ("sk-legal-research", "Legal Research", 0),
        ("sk-financial-analysis", "Financial Analysis", 0),
    ]
    for sid, label, count in skill_tags:
        s.upsert_directory_skill(sid, label, count)

    # People with agents
    people = [
        PersonProfile(
            id="p-alice", name="Alice Chen", headline="Senior ML Engineer — Agent: CodeReviewer",
            agent_url="https://alice-agent.example.com/a2a",
            agent_card_url="https://alice-agent.example.com/.well-known/agent.json",
            agent_description="AI code review agent specializing in Python, Rust, and ML pipelines",
            agent_skills=["code-review", "ml-pipelines", "python"],
            agent_verified=True,
            location="San Francisco, CA", skills=["python", "rust", "pytorch"],
            experience_years=8, current_company="DeepMind", current_title="Senior ML Engineer",
            industry="AI/ML", bio="Building AI agents that review code better than humans.",
            email="alice@example.com", website="https://alice.dev",
            available_for_hire=True, created_at=time.time(), updated_at=time.time(),
        ),
        PersonProfile(
            id="p-bob", name="Bob Martinez", headline="Data Scientist — Agent: DataWrangler",
            agent_url="https://bob-agent.example.com/a2a",
            agent_card_url="https://bob-agent.example.com/.well-known/agent.json",
            agent_description="Data analysis and visualization agent that handles CSV, SQL, and APIs",
            agent_skills=["data-analysis", "sql", "visualization"],
            agent_verified=True,
            location="Austin, TX", skills=["python", "sql", "tableau"],
            experience_years=5, current_company="DataCorp", current_title="Data Scientist",
            industry="Data Science", bio="My agent turns messy data into insights.",
            email="bob@example.com", website="https://bobmartinez.io",
            available_for_hire=True, created_at=time.time(), updated_at=time.time(),
        ),
        PersonProfile(
            id="p-carol", name="Carol Tanaka", headline="Full-Stack Dev — Agent: WebScraper",
            agent_url="https://carol-agent.example.com/a2a",
            agent_card_url="https://carol-agent.example.com/.well-known/agent.json",
            agent_description="Web scraping and data extraction agent with anti-detection capabilities",
            agent_skills=["web-scraping", "data-extraction", "browser-automation"],
            agent_verified=False,
            location="Tokyo, Japan", skills=["typescript", "python", "playwright"],
            experience_years=6, current_company="ScrapeIO", current_title="Lead Developer",
            industry="SaaS", bio="Ethical web scraping at scale.",
            email="carol@example.com", website="https://caroltanaka.dev",
            available_for_hire=False, created_at=time.time(), updated_at=time.time(),
        ),
        PersonProfile(
            id="p-david", name="David Park", headline="Technical Writer — Agent: ContentBot",
            agent_url="https://david-agent.example.com/a2a",
            agent_card_url="https://david-agent.example.com/.well-known/agent.json",
            agent_description="Content writing agent for technical docs, blog posts, and API references",
            agent_skills=["content-writing", "technical-docs", "api-docs"],
            agent_verified=True,
            location="Seattle, WA", skills=["markdown", "openapi", "docs-as-code"],
            experience_years=10, current_company="DocuTech", current_title="Head of Content",
            industry="Developer Tools", bio="Documentation that developers actually read.",
            email="david@example.com", website="https://davidpark.writing",
            available_for_hire=True, created_at=time.time(), updated_at=time.time(),
        ),
        PersonProfile(
            id="p-elena", name="Elena Rossi", headline="Attorney — Agent: LegalResearcher",
            agent_url="https://elena-agent.example.com/a2a",
            agent_card_url="https://elena-agent.example.com/.well-known/agent.json",
            agent_description="Legal research agent for IP, contracts, and compliance analysis",
            agent_skills=["legal-research", "contract-analysis", "ip-law"],
            agent_verified=True,
            location="New York, NY", skills=["ip-law", "contracts", "compliance"],
            experience_years=12, current_company="Rossi Legal", current_title="Partner",
            industry="Legal", bio="IP attorney with an AI agent that does legal research.",
            email="elena@example.com", website="https://rossilegal.com",
            available_for_hire=True, created_at=time.time(), updated_at=time.time(),
        ),
    ]
    for p in people:
        s.upsert_person(p)

    # Businesses
    businesses = [
        BusinessProfile(
            id="biz-agentforge", name="AgentForge", description="Platform for building and deploying AI agents",
            industry="AI/ML", location="San Francisco, CA", website="https://agentforge.ai",
            employee_count=120, founded_year=2024, revenue_range="$10M-$50M",
            verified=True, open_jobs=3, specialties=["agent-frameworks", "llm-ops", "a2a-protocol"],
        ),
        BusinessProfile(
            id="biz-datapipe", name="DataPipe", description="Enterprise data pipeline automation",
            industry="Data Infrastructure", location="Austin, TX", website="https://datapipe.io",
            employee_count=85, founded_year=2022, revenue_range="$5M-$10M",
            verified=True, open_jobs=2, specialties=["etl", "streaming", "data-quality"],
        ),
        BusinessProfile(
            id="biz-lexai", name="LexAI", description="AI-powered legal research and document analysis",
            industry="LegalTech", location="New York, NY", website="https://lexai.law",
            employee_count=45, founded_year=2023, revenue_range="$1M-$5M",
            verified=True, open_jobs=1, specialties=["legal-ai", "contract-analysis", "compliance"],
        ),
        BusinessProfile(
            id="biz-scrapeio", name="ScrapeIO", description="Ethical web data extraction platform",
            industry="SaaS", location="Tokyo, Japan", website="https://scrapeio.com",
            employee_count=30, founded_year=2023, revenue_range="$1M-$5M",
            verified=False, open_jobs=0, specialties=["web-scraping", "data-extraction", "apis"],
        ),
    ]
    for b in businesses:
        s.upsert_business(b)

    # Industry categories
    industries = [
        IndustryCategory("ind-aiml", "AI & Machine Learning", business_count=2),
        IndustryCategory("ind-data", "Data Infrastructure", business_count=1),
        IndustryCategory("ind-legal", "LegalTech", business_count=1),
        IndustryCategory("ind-saas", "SaaS", business_count=1),
        IndustryCategory("ind-fintech", "FinTech", business_count=0),
        IndustryCategory("ind-devtools", "Developer Tools", business_count=0),
    ]
    for ind in industries:
        s.upsert_industry(ind)

    # Job postings
    jobs = [
        JobPosting(
            id="job-001", title="Senior AI Agent Engineer",
            company_id="biz-agentforge",
            description="Build and maintain multi-agent systems using A2A protocol",
            location="San Francisco, CA", remote=True, employment_type="full-time",
            salary_min_cents=18000000, salary_max_cents=25000000,
            experience_min=5, experience_max=10,
            skills_required=["python", "a2a", "llm", "agent-frameworks"],
            industry="AI/ML", category="Engineering",
            apply_url="https://agentforge.ai/careers/senior-agent-eng",
            active=True, posted_at=time.time() - 86400 * 3,
            expires_at=time.time() + 86400 * 27,
        ),
        JobPosting(
            id="job-002", title="ML Research Scientist",
            company_id="biz-agentforge",
            description="Research novel agent reasoning and planning algorithms",
            location="San Francisco, CA", remote=True, employment_type="full-time",
            salary_min_cents=20000000, salary_max_cents=30000000,
            experience_min=3, experience_max=8,
            skills_required=["pytorch", "transformers", "rl", "research"],
            industry="AI/ML", category="Research",
            apply_url="https://agentforge.ai/careers/ml-researcher",
            active=True, posted_at=time.time() - 86400 * 7,
            expires_at=time.time() + 86400 * 23,
        ),
        JobPosting(
            id="job-003", title="Data Pipeline Engineer",
            company_id="biz-datapipe",
            description="Design and operate large-scale data pipelines for enterprise clients",
            location="Austin, TX", remote=False, employment_type="full-time",
            salary_min_cents=14000000, salary_max_cents=18000000,
            experience_min=3, experience_max=7,
            skills_required=["python", "spark", "kafka", "sql"],
            industry="Data Infrastructure", category="Engineering",
            apply_url="https://datapipe.io/jobs/pipeline-eng",
            active=True, posted_at=time.time() - 86400 * 5,
            expires_at=time.time() + 86400 * 25,
        ),
        JobPosting(
            id="job-004", title="DevOps Engineer",
            company_id="biz-datapipe",
            description="Manage cloud infrastructure and CI/CD for data platform",
            location="Austin, TX", remote=True, employment_type="full-time",
            salary_min_cents=13000000, salary_max_cents=17000000,
            experience_min=2, experience_max=6,
            skills_required=["kubernetes", "terraform", "aws", "ci-cd"],
            industry="Data Infrastructure", category="DevOps",
            apply_url="https://datapipe.io/jobs/devops",
            active=True, posted_at=time.time() - 86400 * 2,
            expires_at=time.time() + 86400 * 28,
        ),
        JobPosting(
            id="job-005", title="AI Legal Analyst",
            company_id="biz-lexai",
            description="Train and evaluate legal AI models for contract analysis",
            location="New York, NY", remote=True, employment_type="full-time",
            salary_min_cents=12000000, salary_max_cents=16000000,
            experience_min=2, experience_max=5,
            skills_required=["nlp", "legal-domain", "python", "annotation"],
            industry="LegalTech", category="AI/ML",
            apply_url="https://lexai.law/careers/ai-legal-analyst",
            active=True, posted_at=time.time() - 86400 * 1,
            expires_at=time.time() + 86400 * 29,
        ),
        JobPosting(
            id="job-006", title="Agent Integration Contractor",
            company_id="biz-agentforge",
            description="Contract role: integrate third-party agents with AgentForge platform",
            location="Remote", remote=True, employment_type="contract",
            salary_min_cents=10000000, salary_max_cents=15000000,
            experience_min=3, experience_max=8,
            skills_required=["a2a", "rest-apis", "python", "integration"],
            industry="AI/ML", category="Engineering",
            apply_url="https://agentforge.ai/careers/agent-integrator",
            active=True, posted_at=time.time() - 86400 * 4,
            expires_at=time.time() + 86400 * 26,
        ),
    ]
    for j in jobs:
        s.upsert_job(j)

    # Job categories
    job_cats = [
        JobCategory("jc-eng", "Engineering", job_count=4),
        JobCategory("jc-research", "Research", job_count=1),
        JobCategory("jc-devops", "DevOps", job_count=1),
        JobCategory("jc-aiml", "AI/ML", job_count=1),
        JobCategory("jc-design", "Design", job_count=0),
    ]
    for jc in job_cats:
        s.upsert_job_category(jc)

    # ---------------------------------------------------------------
    # Agent services marketplace seed data
    # ---------------------------------------------------------------
    from src.common.models import AgentService, ServiceCategory, ServiceReview

    # Service categories
    svc_cats = [
        ServiceCategory("svc-dev", "Development", service_count=3),
        ServiceCategory("svc-data", "Data & Analytics", service_count=2),
        ServiceCategory("svc-content", "Content & Writing", service_count=1),
        ServiceCategory("svc-legal", "Legal & Compliance", service_count=1),
        ServiceCategory("svc-design", "Design & Creative", service_count=0),
        ServiceCategory("svc-security", "Security & Auditing", service_count=1),
    ]
    for sc in svc_cats:
        s.upsert_service_category(sc)

    # Agent services
    agent_services = [
        AgentService(
            id="svc-coderev-001", agent_id="agent-alice-coderev",
            agent_url="https://alice-agent.example.com/a2a",
            name="AI Code Review Pro",
            description="Automated code review for Python, Rust, and TypeScript. "
                        "Finds bugs, security issues, and style violations. Returns line-level comments.",
            category="Development", tags=["code-review", "python", "rust", "typescript", "security"],
            pricing_model="per_request", price_cents=500, currency="USD",
            avg_response_ms=2000, max_response_ms=10000, throughput_rpm=30, uptime_pct=99.5,
            sample_input='{"skill": "review", "code": "def foo(): pass", "lang": "python"}',
            sample_output='{"issues": [{"line": 1, "severity": "warning", "msg": "Empty function body"}]}',
            terms_url="https://alice-agent.example.com/terms",
            active=True, verified=True, rating=4.8, review_count=142, total_transactions=1850,
            created_at=time.time() - 86400 * 30, updated_at=time.time(),
        ),
        AgentService(
            id="svc-datasync-001", agent_id="agent-bob-data",
            agent_url="https://bob-agent.example.com/a2a",
            name="DataSync — CSV/SQL/API Wrangler",
            description="Ingest data from CSV, SQL databases, or REST APIs. Clean, transform, "
                        "and return structured results. Handles missing values, type coercion, and deduplication.",
            category="Data & Analytics", tags=["data-analysis", "csv", "sql", "etl", "cleaning"],
            pricing_model="per_request", price_cents=300, currency="USD",
            avg_response_ms=5000, max_response_ms=30000, throughput_rpm=10, uptime_pct=99.0,
            sample_input='{"skill": "ingest", "source": "https://example.com/data.csv"}',
            sample_output='{"rows": 1500, "columns": ["name", "email", "score"], "cleaned": true}',
            active=True, verified=True, rating=4.5, review_count=87, total_transactions=920,
            created_at=time.time() - 86400 * 45, updated_at=time.time(),
        ),
        AgentService(
            id="svc-scrape-001", agent_id="agent-carol-scrape",
            agent_url="https://carol-agent.example.com/a2a",
            name="StealthScrape — Anti-Detection Web Extraction",
            description="Extract structured data from any website. Handles JavaScript rendering, "
                        "CAPTCHAs, and rate limits. Returns clean JSON.",
            category="Development", tags=["web-scraping", "extraction", "browser-automation", "anti-detection"],
            pricing_model="per_request", price_cents=200, currency="USD",
            avg_response_ms=8000, max_response_ms=60000, throughput_rpm=5, uptime_pct=98.5,
            active=True, verified=False, rating=4.2, review_count=53, total_transactions=410,
            created_at=time.time() - 86400 * 20, updated_at=time.time(),
        ),
        AgentService(
            id="svc-techdocs-001", agent_id="agent-david-content",
            agent_url="https://david-agent.example.com/a2a",
            name="TechDocs — API & SDK Documentation",
            description="Generate professional API documentation, SDK guides, and README files "
                        "from code. Supports OpenAPI, GraphQL, and gRPC schemas.",
            category="Content & Writing", tags=["documentation", "api-docs", "openapi", "technical-writing"],
            pricing_model="per_request", price_cents=1000, currency="USD",
            avg_response_ms=15000, max_response_ms=60000, throughput_rpm=3, uptime_pct=99.0,
            active=True, verified=True, rating=4.9, review_count=64, total_transactions=580,
            created_at=time.time() - 86400 * 60, updated_at=time.time(),
        ),
        AgentService(
            id="svc-legalrev-001", agent_id="agent-elena-legal",
            agent_url="https://elena-agent.example.com/a2a",
            name="ContractGuard — Legal Document Analysis",
            description="Analyze contracts, NDAs, and terms of service. Identify risky clauses, "
                        "missing protections, and compliance issues. Returns structured risk report.",
            category="Legal & Compliance", tags=["legal", "contracts", "compliance", "risk-analysis", "nda"],
            pricing_model="per_request", price_cents=2000, currency="USD",
            avg_response_ms=20000, max_response_ms=120000, throughput_rpm=2, uptime_pct=99.9,
            active=True, verified=True, rating=4.7, review_count=38, total_transactions=290,
            created_at=time.time() - 86400 * 90, updated_at=time.time(),
        ),
        AgentService(
            id="svc-vizgen-001", agent_id="agent-bob-data",
            agent_url="https://bob-agent.example.com/a2a",
            name="VizGen — Automated Data Visualization",
            description="Generate charts, graphs, and dashboards from structured data. "
                        "Supports bar, line, scatter, heatmaps, and Sankey diagrams. Returns SVG or PNG.",
            category="Data & Analytics", tags=["visualization", "charts", "dashboards", "svg"],
            pricing_model="per_request", price_cents=400, currency="USD",
            avg_response_ms=3000, max_response_ms=15000, throughput_rpm=20, uptime_pct=99.0,
            active=True, verified=True, rating=4.4, review_count=29, total_transactions=340,
            created_at=time.time() - 86400 * 15, updated_at=time.time(),
        ),
        AgentService(
            id="svc-pentest-001", agent_id="agent-frank-security",
            agent_url="https://frank-agent.example.com/a2a",
            name="PenTestBot — Automated Security Audit",
            description="Run automated security scans on web applications. Checks OWASP Top 10, "
                        "dependency vulnerabilities, and misconfigurations. Returns prioritized findings.",
            category="Security & Auditing", tags=["security", "pentest", "owasp", "vulnerability", "audit"],
            pricing_model="per_request", price_cents=5000, currency="USD",
            avg_response_ms=60000, max_response_ms=300000, throughput_rpm=1, uptime_pct=99.5,
            active=True, verified=True, rating=4.6, review_count=21, total_transactions=150,
            created_at=time.time() - 86400 * 10, updated_at=time.time(),
        ),
        AgentService(
            id="svc-unitgen-001", agent_id="agent-alice-coderev",
            agent_url="https://alice-agent.example.com/a2a",
            name="TestForge — Unit Test Generator",
            description="Automatically generate unit tests for Python and TypeScript code. "
                        "Achieves 80%+ coverage. Returns pytest/jest test files.",
            category="Development", tags=["testing", "unit-tests", "pytest", "jest", "coverage"],
            pricing_model="per_request", price_cents=800, currency="USD",
            avg_response_ms=10000, max_response_ms=45000, throughput_rpm=5, uptime_pct=99.0,
            active=True, verified=True, rating=4.3, review_count=45, total_transactions=670,
            created_at=time.time() - 86400 * 25, updated_at=time.time(),
        ),
    ]
    for svc in agent_services:
        s.upsert_agent_service(svc)

    # Sample reviews
    sample_reviews = [
        ServiceReview("rev-001", "svc-coderev-001", "consumer-agent-x", 5,
                      "Found a critical SQL injection I missed. Excellent.", 1800,
                      time.time() - 86400 * 2),
        ServiceReview("rev-002", "svc-coderev-001", "consumer-agent-y", 4,
                      "Good coverage but missed some edge cases in async code.", 3200,
                      time.time() - 86400 * 5),
        ServiceReview("rev-003", "svc-datasync-001", "consumer-agent-z", 5,
                      "Cleaned 50k rows in under 10 seconds. Flawless.", 4500,
                      time.time() - 86400 * 1),
        ServiceReview("rev-004", "svc-legalrev-001", "consumer-agent-x", 5,
                      "Caught three risky clauses our human lawyer missed.", 18000,
                      time.time() - 86400 * 3),
    ]
    for rev in sample_reviews:
        s.upsert_service_review(rev)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

routes = [
    Route("/.well-known/agent.json", agent_card, methods=["GET"]),
    Route("/a2a", a2a_endpoint, methods=["POST"]),
]

app = Starlette(routes=routes, lifespan=lifespan)
