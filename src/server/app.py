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
from src.server.agent_tracker import AgentTracker
from src.server.embeddings import EmbeddingIndex
from src.server.federation import FederationManager
from src.server.negotiation import NegotiationEngine
from src.server.purchase import PurchaseEngine
from src.server.skills import SkillRouter
from src.server.store import CatalogStore
from src.server.vendor_analytics import VendorAnalytics

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


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    global store, router
    store = CatalogStore(DB_PATH)
    ad_engine = AdEngine(store)
    tracker = AgentTracker(store)
    negotiation = NegotiationEngine(store)
    purchase = PurchaseEngine(store)
    federation = FederationManager(store)
    embeddings = EmbeddingIndex(store)
    analytics = VendorAnalytics(store)
    router = SkillRouter(
        store, ad_engine, tracker, negotiation, purchase,
        federation, embeddings, analytics,
    )

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

    assert router is not None
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
    from src.common.models import AdCampaign, CatalogItem, Category, Vendor

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


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

routes = [
    Route("/.well-known/agent.json", agent_card, methods=["GET"]),
    Route("/a2a", a2a_endpoint, methods=["POST"]),
]

app = Starlette(routes=routes, lifespan=lifespan)
