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


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    global store, router, video_router
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
    if video_router.can_handle(skill_name):
        result_data = video_router.handle(skill_data, agent_id=agent_id)
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


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

routes = [
    Route("/.well-known/agent.json", agent_card, methods=["GET"]),
    Route("/a2a", a2a_endpoint, methods=["POST"]),
]

app = Starlette(routes=routes, lifespan=lifespan)
