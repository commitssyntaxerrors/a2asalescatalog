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
from src.server.skills import SkillRouter
from src.server.store import CatalogStore

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH = os.environ.get("CATALOG_DB", ":memory:")
API_KEYS: set[str] = set(filter(None, os.environ.get("CATALOG_API_KEYS", "").split(",")))
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
    router = SkillRouter(store, ad_engine)

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

    if method == "tasks/send":
        return _handle_task_send(rpc_id, params)
    elif method == "tasks/get":
        return _handle_task_get(rpc_id, params)
    else:
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        })


def _handle_task_send(rpc_id: Any, params: dict) -> JSONResponse:
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
    result_data = router.handle(skill_data)

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

    # Demo ad campaign
    s.upsert_campaign(AdCampaign(
        "ad-001", "v-soundpod",
        keywords=["earbuds", "headphones", "wireless", "audio"],
        categories=["audio", "electronics"],
        bid_cents=50,
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
