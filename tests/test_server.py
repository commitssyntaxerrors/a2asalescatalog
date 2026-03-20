# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Smoke tests for the A2A Sales Catalog server."""

import json
import pytest
from starlette.testclient import TestClient

from src.server.app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _send(client, skill_data, task_id="t1"):
    """Helper to send a tasks/send request."""
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tasks/send",
        "params": {
            "id": task_id,
            "message": {"role": "user", "parts": [
                {"type": "data", "data": skill_data}
            ]},
        },
    }
    resp = client.post("/a2a", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    result = body["result"]
    if result["status"]["state"] == "completed":
        return result["artifacts"][0]["parts"][0]["data"]
    return result


# -----------------------------------------------------------------------
# Original tests
# -----------------------------------------------------------------------

def test_agent_card(client):
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "A2A Sales Catalog"
    assert len(card["skills"]) >= 11


def test_search_earbuds(client):
    data = _send(client, {"skill": "catalog.search", "q": "earbuds", "max": 5})
    assert "fields" in data
    assert "items" in data
    assert len(data["items"]) > 0


def test_lookup_item(client):
    data = _send(client, {"skill": "catalog.lookup", "id": "WE-001"})
    assert data["id"] == "WE-001"
    assert data["name"] == "SoundPod Pro"
    assert data["price_cents"] == 4999


def test_categories(client):
    data = _send(client, {"skill": "catalog.categories"})
    assert "fields" in data
    assert "cats" in data


def test_compare_items(client):
    data = _send(client, {"skill": "catalog.compare", "ids": ["WE-001", "WE-002"]})
    assert "fields" in data
    assert "rows" in data
    assert len(data["rows"]) == 2


def test_unknown_skill(client):
    result = _send(client, {"skill": "catalog.nonexistent"})
    assert result["status"]["state"] == "failed"


def test_unknown_method(client):
    payload = {"jsonrpc": "2.0", "id": 6, "method": "tasks/bogus", "params": {}}
    resp = client.post("/a2a", json=payload)
    body = resp.json()
    assert "error" in body


def test_search_with_price_filter(client):
    data = _send(client, {"skill": "catalog.search", "q": "earbuds", "price_max": 4000})
    fields = data["fields"]
    price_idx = fields.index("price_cents")
    sponsored_idx = fields.index("sponsored")
    for item in data["items"]:
        if not item[sponsored_idx]:
            assert item[price_idx] <= 4000


# -----------------------------------------------------------------------
# Agent profile & reputation tests
# -----------------------------------------------------------------------

def test_agent_profile(client):
    data = _send(client, {"skill": "catalog.agent_profile"})
    assert "agent_id" in data
    assert "reputation" in data
    assert "intent_tier" in data
    assert data["reputation"] == 50.0  # default starting reputation


def test_reputation(client):
    data = _send(client, {"skill": "catalog.reputation"})
    assert "agent_id" in data
    assert "score" in data
    assert "tier" in data
    assert "benefits" in data
    assert "factors" in data


# -----------------------------------------------------------------------
# Agent tracking & interest scoring tests
# -----------------------------------------------------------------------

def test_interest_scoring_builds_on_repeat_visits(client):
    """Repeated lookups on the same item should increase interest score."""
    # First lookup
    _send(client, {"skill": "catalog.lookup", "id": "WE-001"})
    profile1 = _send(client, {"skill": "catalog.agent_profile"})

    # Second lookup — repeat visit bonus
    _send(client, {"skill": "catalog.lookup", "id": "WE-001"})
    profile2 = _send(client, {"skill": "catalog.agent_profile"})

    # Score should have increased
    def _item_score(profile, item_id):
        for entry in profile.get("item_interests", []):
            if entry[0] == item_id:
                return entry[1]
        return 0.0

    assert _item_score(profile2, "WE-001") > _item_score(profile1, "WE-001")


# -----------------------------------------------------------------------
# Negotiation tests
# -----------------------------------------------------------------------

def test_negotiate_new_session(client):
    data = _send(client, {
        "skill": "catalog.negotiate",
        "item_id": "WE-001",
        "offer_cents": 3500,
    })
    assert "session_id" in data
    assert data["status"] in ("counter", "accepted")
    assert "rounds_left" in data


def test_negotiate_too_low_offer(client):
    result = _send(client, {
        "skill": "catalog.negotiate",
        "item_id": "WE-001",
        "offer_cents": 1000,  # way below 60% floor
    })
    # This should fail since 1000 < 60% of 4999 = 2999
    assert result["status"]["state"] == "failed"


def test_negotiate_continuation(client):
    # WE-003 is 5999 cents, floor defaults to 70% = 4199
    # Start session with a low-ish but valid offer
    data1 = _send(client, {
        "skill": "catalog.negotiate",
        "item_id": "WE-003",
        "offer_cents": 3600,  # 60% of 5999 = 3599, so just above min
    })
    assert "session_id" in data1
    session_id = data1["session_id"]
    assert data1["status"] == "counter"  # should counter, not accept

    # Continue with higher offer
    data2 = _send(client, {
        "skill": "catalog.negotiate",
        "item_id": "WE-003",
        "offer_cents": 4200,
        "session_id": session_id,
    })
    # Should be accepted since 4200 >= floor (4199)
    assert "session_id" in data2
    assert data2["status"] == "accepted"


# -----------------------------------------------------------------------
# Purchase tests
# -----------------------------------------------------------------------

def test_purchase_item(client):
    data = _send(client, {
        "skill": "catalog.purchase",
        "item_id": "WE-002",
        "quantity": 1,
        "payment_token": "pay_tok_test123",
        "shipping": {"method": "standard", "address_token": "addr_tok_test"},
    })
    assert "order_id" in data
    assert data["status"] == "confirmed"
    assert data["payment_status"] == "captured"
    assert data["item_id"] == "WE-002"


def test_purchase_no_payment_token(client):
    result = _send(client, {
        "skill": "catalog.purchase",
        "item_id": "WE-001",
        "quantity": 1,
    })
    assert result["status"]["state"] == "failed"


# -----------------------------------------------------------------------
# Embeddings tests
# -----------------------------------------------------------------------

def test_embed_items(client):
    data = _send(client, {
        "skill": "catalog.embed",
        "ids": ["WE-001", "WE-002"],
    })
    assert "dim" in data
    assert data["dim"] == 128
    assert "items" in data
    assert len(data["items"]) == 2
    assert data["items"][0][0] == "WE-001"
    assert len(data["items"][0][1]) > 0  # base64 embedding


def test_embed_query(client):
    data = _send(client, {
        "skill": "catalog.embed",
        "query": "comfortable running earbuds",
    })
    assert "query_emb" in data
    assert len(data["query_emb"]) > 0


# -----------------------------------------------------------------------
# Federation tests
# -----------------------------------------------------------------------

def test_peers_empty(client):
    data = _send(client, {"skill": "catalog.peers"})
    assert "fields" in data
    assert "peers" in data
    assert isinstance(data["peers"], list)


# -----------------------------------------------------------------------
# Vendor analytics tests
# -----------------------------------------------------------------------

def test_vendor_analytics(client):
    # Do some activity first
    _send(client, {"skill": "catalog.search", "q": "earbuds"})
    _send(client, {"skill": "catalog.lookup", "id": "WE-001"})

    data = _send(client, {
        "skill": "catalog.vendor_analytics",
        "vendor_id": "v-soundpod",
        "period": "7d",
    })
    assert data["vendor_id"] == "v-soundpod"
    assert "summary" in data
    assert "agent_intent_breakdown" in data


def test_vendor_analytics_missing_vendor(client):
    result = _send(client, {"skill": "catalog.vendor_analytics"})
    assert result["status"]["state"] == "failed"


# -----------------------------------------------------------------------
# Search with embeddings test
# -----------------------------------------------------------------------

def test_search_with_embeddings(client):
    data = _send(client, {
        "skill": "catalog.search",
        "q": "earbuds",
        "max": 3,
        "include_embeddings": True,
    })
    assert "emb" in data["fields"]
    # Each item tuple should have an extra embedding field
    assert len(data["items"][0]) == len(data["fields"])
