"""Smoke tests for the A2A Sales Catalog server."""

import json
import pytest
from starlette.testclient import TestClient

from src.server.app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_agent_card(client):
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "A2A Sales Catalog"
    assert len(card["skills"]) >= 4


def test_search_earbuds(client):
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tasks/send",
        "params": {
            "id": "t1",
            "message": {"role": "user", "parts": [
                {"type": "data", "data": {"skill": "catalog.search", "q": "earbuds", "max": 5}}
            ]},
        },
    }
    resp = client.post("/a2a", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    result = body["result"]
    assert result["status"]["state"] == "completed"
    data = result["artifacts"][0]["parts"][0]["data"]
    assert "fields" in data
    assert "items" in data
    assert len(data["items"]) > 0


def test_lookup_item(client):
    payload = {
        "jsonrpc": "2.0", "id": 2, "method": "tasks/send",
        "params": {
            "id": "t2",
            "message": {"role": "user", "parts": [
                {"type": "data", "data": {"skill": "catalog.lookup", "id": "WE-001"}}
            ]},
        },
    }
    resp = client.post("/a2a", json=payload)
    assert resp.status_code == 200
    data = resp.json()["result"]["artifacts"][0]["parts"][0]["data"]
    assert data["id"] == "WE-001"
    assert data["name"] == "SoundPod Pro"
    assert data["price_cents"] == 4999


def test_categories(client):
    payload = {
        "jsonrpc": "2.0", "id": 3, "method": "tasks/send",
        "params": {
            "id": "t3",
            "message": {"role": "user", "parts": [
                {"type": "data", "data": {"skill": "catalog.categories"}}
            ]},
        },
    }
    resp = client.post("/a2a", json=payload)
    assert resp.status_code == 200
    data = resp.json()["result"]["artifacts"][0]["parts"][0]["data"]
    assert "fields" in data
    assert "cats" in data


def test_compare_items(client):
    payload = {
        "jsonrpc": "2.0", "id": 4, "method": "tasks/send",
        "params": {
            "id": "t4",
            "message": {"role": "user", "parts": [
                {"type": "data", "data": {"skill": "catalog.compare", "ids": ["WE-001", "WE-002"]}}
            ]},
        },
    }
    resp = client.post("/a2a", json=payload)
    assert resp.status_code == 200
    data = resp.json()["result"]["artifacts"][0]["parts"][0]["data"]
    assert "fields" in data
    assert "rows" in data
    assert len(data["rows"]) == 2


def test_unknown_skill(client):
    payload = {
        "jsonrpc": "2.0", "id": 5, "method": "tasks/send",
        "params": {
            "id": "t5",
            "message": {"role": "user", "parts": [
                {"type": "data", "data": {"skill": "catalog.nonexistent"}}
            ]},
        },
    }
    resp = client.post("/a2a", json=payload)
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"]["state"] == "failed"


def test_unknown_method(client):
    payload = {"jsonrpc": "2.0", "id": 6, "method": "tasks/bogus", "params": {}}
    resp = client.post("/a2a", json=payload)
    body = resp.json()
    assert "error" in body


def test_search_with_price_filter(client):
    payload = {
        "jsonrpc": "2.0", "id": 7, "method": "tasks/send",
        "params": {
            "id": "t7",
            "message": {"role": "user", "parts": [
                {"type": "data", "data": {
                    "skill": "catalog.search", "q": "earbuds",
                    "price_max": 4000
                }}
            ]},
        },
    }
    resp = client.post("/a2a", json=payload)
    assert resp.status_code == 200
    data = resp.json()["result"]["artifacts"][0]["parts"][0]["data"]
    # All returned items should be ≤ 4000 cents (before sponsored injection)
    fields = data["fields"]
    price_idx = fields.index("price_cents")
    for item in data["items"]:
        # Sponsored items may exceed filter — only check organic
        sponsored_idx = fields.index("sponsored")
        if not item[sponsored_idx]:
            assert item[price_idx] <= 4000
