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


# -----------------------------------------------------------------------
# Display Ads tests
# -----------------------------------------------------------------------

def test_display_ads(client):
    data = _send(client, {"skill": "catalog.display_ads", "max": 3})
    assert "ads" in data
    assert "count" in data
    assert isinstance(data["ads"], list)


def test_display_ads_by_category(client):
    data = _send(client, {"skill": "catalog.display_ads", "cat": "audio", "max": 2})
    assert "ads" in data


# -----------------------------------------------------------------------
# Retargeting tests
# -----------------------------------------------------------------------

def test_retarget_with_prior_view(client):
    """View an item, then ask for retarget offers — should get at least one."""
    _send(client, {"skill": "catalog.lookup", "id": "WE-001"})
    data = _send(client, {"skill": "catalog.retarget", "max": 5})
    assert "offers" in data
    assert "count" in data
    # We viewed WE-001 but didn't buy — should get an offer
    assert data["count"] >= 1
    offer_ids = [o["item_id"] for o in data["offers"]]
    assert "WE-001" in offer_ids


# -----------------------------------------------------------------------
# Affiliate tests
# -----------------------------------------------------------------------

def test_affiliate_create(client):
    data = _send(client, {
        "skill": "catalog.affiliate",
        "action": "create",
        "vendor_id": "v-soundpod",
    })
    assert "referral_code" in data
    assert data["referral_code"].startswith("ref-")
    assert data["vendor_id"] == "v-soundpod"


def test_affiliate_status(client):
    # First create one
    _send(client, {
        "skill": "catalog.affiliate",
        "action": "create",
        "vendor_id": "v-soundpod",
    })
    data = _send(client, {"skill": "catalog.affiliate", "action": "status"})
    assert "referrals" in data
    assert "count" in data
    assert data["count"] >= 1


# -----------------------------------------------------------------------
# RTB Auction tests
# -----------------------------------------------------------------------

def test_auction(client):
    data = _send(client, {
        "skill": "catalog.auction",
        "q": "earbuds",
        "slots": 2,
    })
    assert "winners" in data
    assert "count" in data
    assert isinstance(data["winners"], list)


# -----------------------------------------------------------------------
# Promotions tests
# -----------------------------------------------------------------------

def test_promotions_discover(client):
    data = _send(client, {"skill": "catalog.promotions", "action": "discover"})
    assert "promotions" in data
    assert "count" in data
    assert data["count"] >= 1  # seed data has SOUND10


def test_promotions_validate(client):
    data = _send(client, {
        "skill": "catalog.promotions",
        "action": "validate",
        "code": "SOUND10",
        "item_id": "WE-001",
        "price_cents": 4999,
    })
    assert data["valid"] is True
    assert "discount_cents" in data
    assert data["discount_cents"] > 0


def test_promotions_validate_invalid_code(client):
    result = _send(client, {
        "skill": "catalog.promotions",
        "action": "validate",
        "code": "BOGUS",
        "item_id": "WE-001",
        "price_cents": 4999,
    })
    # Invalid code returns a failed state since validate_code puts "error" in response
    assert result["status"]["state"] == "failed"


# -----------------------------------------------------------------------
# Audience Segments tests
# -----------------------------------------------------------------------

def test_audience_list(client):
    data = _send(client, {"skill": "catalog.audience", "action": "list"})
    assert "segments" in data
    assert "count" in data
    assert data["count"] >= 5  # 5 default segments


def test_audience_classify(client):
    data = _send(client, {"skill": "catalog.audience", "action": "classify"})
    assert "agent_id" in data
    assert "segments" in data


# -----------------------------------------------------------------------
# Attribution tests
# -----------------------------------------------------------------------

def test_attribution_journey(client):
    # Do some activity to generate touchpoints
    _send(client, {"skill": "catalog.search", "q": "earbuds"})
    _send(client, {"skill": "catalog.lookup", "id": "WE-001"})

    data = _send(client, {
        "skill": "catalog.attribution",
        "action": "journey",
        "agent_id": "dev-agent",
    })
    assert "touchpoints" in data
    assert "count" in data


def test_attribution_campaign(client):
    data = _send(client, {
        "skill": "catalog.attribution",
        "action": "campaign",
        "campaign_id": "ad-001",
    })
    # Should return attribution data (may be empty if no purchases)
    assert isinstance(data, dict)


# -----------------------------------------------------------------------
# Cross-Sell tests
# -----------------------------------------------------------------------

def test_cross_sell(client):
    data = _send(client, {"skill": "catalog.cross_sell", "item_id": "WE-001"})
    assert "item_id" in data
    assert data["item_id"] == "WE-001"
    assert "recommendations" in data
    assert "count" in data
    # Seed data has a cross-sell rule for WE-001 -> WE-003
    assert data["count"] >= 1


def test_cross_sell_missing_item(client):
    result = _send(client, {"skill": "catalog.cross_sell"})
    assert result["status"]["state"] == "failed"


# -----------------------------------------------------------------------
# A/B Results tests
# -----------------------------------------------------------------------

def test_ab_results_missing_group(client):
    result = _send(client, {"skill": "catalog.ab_results"})
    assert result["status"]["state"] == "failed"


def test_ab_results(client):
    data = _send(client, {"skill": "catalog.ab_results", "ab_group": "test-group"})
    assert "ab_group" in data
    assert "variants" in data
    assert "count" in data


# -----------------------------------------------------------------------
# Purchase with promo code test
# -----------------------------------------------------------------------

def test_purchase_with_promo(client):
    data = _send(client, {
        "skill": "catalog.purchase",
        "item_id": "WE-001",
        "quantity": 1,
        "payment_token": "pay_tok_promo_test",
        "promo_code": "SOUND10",
    })
    assert "order_id" in data
    assert data["status"] == "confirmed"


# -----------------------------------------------------------------------
# Agent Card updated skill count
# -----------------------------------------------------------------------

def test_agent_card_has_39_skills(client):
    resp = client.get("/.well-known/agent.json")
    card = resp.json()
    assert len(card["skills"]) == 39
    assert card["version"] == "0.6.0"


# -----------------------------------------------------------------------
# AXON format tests
# -----------------------------------------------------------------------

def _send_axon(client, skill_data, task_id="t1"):
    """Send a request with format=axon, return raw AXON text."""
    skill_data = {**skill_data, "format": "axon"}
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
    assert result["status"]["state"] == "completed"
    part = result["artifacts"][0]["parts"][0]
    assert part["type"] == "text"
    return part["text"]


def test_axon_search(client):
    """Search with AXON format should return text, not JSON data."""
    text = _send_axon(client, {"skill": "catalog.search", "q": "earbuds", "max": 3})
    assert isinstance(text, str)
    # Should contain schema header
    assert "@{" in text
    # Should contain row markers
    assert "> " in text
    # Should contain pipe delimiters
    assert "|" in text
    # Should NOT be JSON
    assert not text.strip().startswith("{")


def test_axon_search_has_sigils(client):
    """AXON output should use sigil-typed values for commerce fields."""
    text = _send_axon(client, {"skill": "catalog.search", "q": "earbuds", "max": 3})
    # Price sigil $ should appear in rows
    assert "$" in text
    # Rating sigil ★ should appear
    assert "\u2605" in text


def test_axon_lookup(client):
    """Lookup with AXON format should return key=value pairs."""
    text = _send_axon(client, {"skill": "catalog.lookup", "id": "WE-001"})
    assert isinstance(text, str)
    assert "name=" in text
    assert "SoundPod Pro" in text


def test_axon_categories(client):
    """Categories with AXON format should return tabular data."""
    text = _send_axon(client, {"skill": "catalog.categories"})
    assert "@{" in text
    assert "> " in text


def test_axon_promotions(client):
    """Promotions with AXON format should return structured data."""
    text = _send_axon(client, {"skill": "catalog.promotions", "action": "discover"})
    assert isinstance(text, str)
    assert "count=" in text or "promotions" in text.lower() or ">" in text


def test_axon_roundtrip():
    """Encode a dict to AXON and decode it back — should preserve structure."""
    from src.common.axon import encode, decode

    original = {
        "fields": ["id", "name", "price_cents", "rating"],
        "items": [
            ["WE-001", "SoundPod Pro", 4999, 4.5],
            ["WE-002", "SoundPod Lite", 2999, 4.2],
        ],
    }
    axon_text = encode(original)
    decoded = decode(axon_text)

    assert decoded["fields"] == original["fields"]
    assert len(decoded["items"]) == 2
    # Values should round-trip (sigils stripped, types coerced)
    assert decoded["items"][0][0] == "WE-001"
    assert decoded["items"][0][2] == 4999
    assert decoded["items"][0][3] == 4.5


def test_axon_scalar_dict_roundtrip():
    """Encode a flat key-value dict and decode it back."""
    from src.common.axon import encode, decode

    original = {
        "order_id": "ORD-001",
        "status": "confirmed",
        "price_cents": 4999,
        "agent_id": "agent-42",
    }
    axon_text = encode(original)
    decoded = decode(axon_text)

    assert decoded["status"] == "confirmed"
    assert decoded["price_cents"] == 4999


def test_axon_nested_section():
    """Encode nested dicts using [section] blocks."""
    from src.common.axon import encode, decode

    original = {
        "item_id": "WE-001",
        "recommendations": [
            {"item_id": "WE-003", "rule_type": "upsell", "reason": "Premium model"},
        ],
    }
    axon_text = encode(original)
    assert "[recommendations]" in axon_text
    assert "[/recommendations]" in axon_text


def test_axon_token_savings():
    """AXON should produce fewer tokens than JSON for the same data."""
    import json as json_mod
    from src.common.axon import encode, token_estimate

    data = {
        "fields": ["id", "name", "desc", "price_cents", "vendor", "rating", "sponsored", "ad_tag"],
        "items": [
            ["WE-001", "SoundPod Pro", "Premium wireless earbuds", 4999, "soundpod.io", 4.5, 0, None],
            ["WE-002", "SoundPod Lite", "Budget wireless earbuds", 2999, "soundpod.io", 4.2, 0, None],
            ["WE-003", "SoundPod Max", "Flagship noise-cancelling", 5999, "soundpod.io", 4.8, 1, "ad-001"],
        ],
    }
    json_text = json_mod.dumps(data)
    axon_text = encode(data)

    json_tokens = token_estimate(json_text)
    axon_tokens = token_estimate(axon_text)

    # AXON should use fewer tokens than JSON
    assert axon_tokens < json_tokens
    # Should achieve at least 30% reduction
    reduction = 1 - (axon_tokens / json_tokens)
    assert reduction >= 0.3, f"Only {reduction:.0%} reduction, expected >= 30%"


# -----------------------------------------------------------------------
# Video catalog tests
# -----------------------------------------------------------------------


def test_video_search(client):
    """video.search returns compact tuples for video results."""
    data = _send(client, {"skill": "video.search", "q": "earbuds"})
    assert "fields" in data
    assert "items" in data
    assert data["total"] >= 1
    assert "id" in data["fields"]
    assert "title" in data["fields"]
    # First result should match earbuds
    first = data["items"][0]
    assert "VID-" in first[0]


def test_video_search_by_platform(client):
    """video.search filters by platform."""
    data = _send(client, {"skill": "video.search", "q": "", "platform": "vimeo"})
    assert data["total"] >= 1
    for item in data["items"]:
        assert item[3] == "vimeo"  # platform field


def test_video_search_by_category(client):
    """video.search filters by category."""
    data = _send(client, {"skill": "video.search", "q": "", "cat": "vid-cooking"})
    assert data["total"] >= 1


def test_video_lookup(client):
    """video.lookup returns full video details."""
    data = _send(client, {"skill": "video.lookup", "id": "VID-001"})
    assert data["id"] == "VID-001"
    assert data["title"] == "Best Wireless Earbuds 2026 — Top 5 Picks"
    assert data["channel"] == "TechReviewer"
    assert data["platform"] == "youtube"
    assert data["duration_secs"] == 1245
    assert data["views"] == 1_850_000
    assert data["rating"] == 4.8
    assert "chapters" in data
    assert len(data["chapters"]) > 0
    assert "tags" in data
    assert "earbuds" in data["tags"]
    assert data["transcript_summary"] != ""


def test_video_lookup_not_found(client):
    """video.lookup returns error for unknown video."""
    result = _send(client, {"skill": "video.lookup", "id": "VID-NOPE"})
    # Returns a failed task
    assert result["status"]["state"] == "failed"


def test_video_trending(client):
    """video.trending returns videos sorted by views."""
    data = _send(client, {"skill": "video.trending", "max": 3})
    assert data["total"] == 3
    # Should be ordered by views descending
    views = [item[5] for item in data["items"]]  # views is index 5
    assert views == sorted(views, reverse=True)


def test_video_trending_by_category(client):
    """video.trending accepts category filter."""
    data = _send(client, {"skill": "video.trending", "cat": "vid-cooking"})
    assert data["total"] >= 1


def test_video_creator(client):
    """video.creator returns channel profile and recent videos."""
    data = _send(client, {"skill": "video.creator", "channel_id": "ch-techrev"})
    assert data["channel_id"] == "ch-techrev"
    assert data["name"] == "TechReviewer"
    assert data["subscribers"] == 2_400_000
    assert data["verified"] is True
    assert "recent_uploads" in data
    assert len(data["recent_uploads"]["items"]) >= 1


def test_video_creator_not_found(client):
    """video.creator returns error for unknown channel."""
    result = _send(client, {"skill": "video.creator", "channel_id": "ch-nope"})
    assert result["status"]["state"] == "failed"


def test_video_categories(client):
    """video.categories lists top-level video categories."""
    data = _send(client, {"skill": "video.categories"})
    assert "cats" in data
    assert len(data["cats"]) >= 3
    labels = [c[1] for c in data["cats"]]
    assert "Technology" in labels


def test_video_categories_children(client):
    """video.categories with parent returns children."""
    data = _send(client, {"skill": "video.categories", "parent": "vid-tech"})
    labels = [c[1] for c in data["cats"]]
    assert "Product Reviews" in labels


def test_video_playlist_get(client):
    """video.playlist returns playlist details with video list."""
    data = _send(client, {"skill": "video.playlist", "id": "pl-001"})
    assert data["id"] == "pl-001"
    assert data["title"] == "Best of Tech Reviews 2026"
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_video_playlist_list(client):
    """video.playlist without id lists all playlists."""
    data = _send(client, {"skill": "video.playlist"})
    assert "playlists" in data
    assert data["total"] >= 2


def test_video_transcript(client):
    """video.transcript searches video transcripts."""
    data = _send(client, {"skill": "video.transcript", "q": "transformer attention"})
    assert data["total"] >= 1
    found = [r for r in data["results"] if r["id"] == "VID-003"]
    assert len(found) == 1
    assert "transcript_summary" in found[0]


def test_video_recommend(client):
    """video.recommend returns similar videos."""
    data = _send(client, {"skill": "video.recommend", "video_id": "VID-001"})
    assert data["total"] >= 1
    assert data["based_on"] == "VID-001"
    # Should not include the source video itself
    ids = [item[0] for item in data["items"]]
    assert "VID-001" not in ids


def test_video_recommend_by_category(client):
    """video.recommend by category returns results."""
    data = _send(client, {"skill": "video.recommend", "cat": "vid-programming"})
    assert data["total"] >= 1


# -----------------------------------------------------------------------
# Agent Directory tests
# -----------------------------------------------------------------------

def test_directory_search(client):
    """directory.search returns agent-discoverable profiles."""
    data = _send(client, {"skill": "directory.search", "q": "code review"})
    assert "fields" in data
    assert data["total"] >= 1
    # Alice's agent does code review
    ids = [item[0] for item in data["items"]]
    assert "p-alice" in ids


def test_directory_search_by_skill(client):
    """directory.search with skill_tag filter."""
    data = _send(client, {"skill": "directory.search", "q": "", "skill_tag": "python"})
    assert data["total"] >= 1


def test_directory_search_available_only(client):
    """directory.search with available_only filter."""
    data = _send(client, {"skill": "directory.search", "q": "", "available_only": True})
    assert data["total"] >= 1
    # Carol is not available for hire, should not appear
    ids = [item[0] for item in data["items"]]
    assert "p-carol" not in ids


def test_directory_search_by_location(client):
    """directory.search with location filter."""
    data = _send(client, {"skill": "directory.search", "q": "", "location": "San Francisco"})
    assert data["total"] >= 1
    ids = [item[0] for item in data["items"]]
    assert "p-alice" in ids


def test_directory_lookup(client):
    """directory.lookup returns full profile with agent details."""
    data = _send(client, {"skill": "directory.lookup", "id": "p-alice"})
    assert data["id"] == "p-alice"
    assert data["name"] == "Alice Chen"
    assert "agent" in data
    assert data["agent"]["url"] == "https://alice-agent.example.com/a2a"
    assert data["agent"]["verified"] is True
    assert "code-review" in data["agent"]["skills"]


def test_directory_lookup_not_found(client):
    """directory.lookup with invalid id returns error."""
    result = _send(client, {"skill": "directory.lookup", "id": "p-nonexistent"})
    assert result["status"]["state"] == "failed"


def test_directory_skills(client):
    """directory.skills returns capability tags."""
    data = _send(client, {"skill": "directory.skills"})
    assert "fields" in data
    assert "skills" in data
    assert len(data["skills"]) >= 5


def test_directory_register(client):
    """directory.register creates a new profile."""
    data = _send(client, {"skill": "directory.register",
                          "id": "p-test-new", "name": "Test Agent Owner",
                          "headline": "QA Engineer — Agent: TestRunner",
                          "agent_url": "https://test-agent.example.com/a2a",
                          "agent_description": "Automated testing agent",
                          "agent_skills": ["testing", "qa"],
                          "location": "Remote"})
    assert data["status"] == "registered"
    assert data["id"] == "p-test-new"
    # Verify it's searchable
    search = _send(client, {"skill": "directory.search", "q": "TestRunner"})
    assert search["total"] >= 1


# -----------------------------------------------------------------------
# Business Directory tests
# -----------------------------------------------------------------------

def test_business_search(client):
    """business.search returns companies."""
    data = _send(client, {"skill": "business.search", "q": "agent"})
    assert "fields" in data
    assert data["total"] >= 1
    ids = [item[0] for item in data["items"]]
    assert "biz-agentforge" in ids


def test_business_search_by_industry(client):
    """business.search with industry filter."""
    data = _send(client, {"skill": "business.search", "q": "", "industry": "LegalTech"})
    assert data["total"] >= 1
    ids = [item[0] for item in data["items"]]
    assert "biz-lexai" in ids


def test_business_lookup(client):
    """business.lookup returns full company profile with jobs."""
    data = _send(client, {"skill": "business.lookup", "id": "biz-agentforge"})
    assert data["id"] == "biz-agentforge"
    assert data["name"] == "AgentForge"
    assert data["open_jobs"] >= 1
    assert len(data["jobs"]) >= 1
    assert "agent-frameworks" in data["specialties"]


def test_business_lookup_not_found(client):
    """business.lookup with invalid id returns error."""
    result = _send(client, {"skill": "business.lookup", "id": "biz-nonexistent"})
    assert result["status"]["state"] == "failed"


def test_business_industries(client):
    """business.industries returns industry categories."""
    data = _send(client, {"skill": "business.industries"})
    assert "fields" in data
    assert "industries" in data
    assert len(data["industries"]) >= 4


# -----------------------------------------------------------------------
# Job Postings tests
# -----------------------------------------------------------------------

def test_jobs_search(client):
    """jobs.search returns job postings."""
    data = _send(client, {"skill": "jobs.search", "q": "agent engineer"})
    assert "fields" in data
    assert data["total"] >= 1


def test_jobs_search_remote(client):
    """jobs.search with remote_only filter."""
    data = _send(client, {"skill": "jobs.search", "q": "", "remote_only": True})
    assert data["total"] >= 1
    # All returned jobs should be remote
    for item in data["items"]:
        assert item[4] is True  # remote field


def test_jobs_search_by_type(client):
    """jobs.search with employment_type filter."""
    data = _send(client, {"skill": "jobs.search", "q": "", "employment_type": "contract"})
    assert data["total"] >= 1
    for item in data["items"]:
        assert item[5] == "contract"


def test_jobs_search_salary_floor(client):
    """jobs.search with salary_min filter."""
    data = _send(client, {"skill": "jobs.search", "q": "", "salary_min": 15000000})
    assert data["total"] >= 1
    for item in data["items"]:
        assert item[7] >= 15000000  # salary_max_cents >= filter


def test_jobs_lookup(client):
    """jobs.lookup returns full job details."""
    data = _send(client, {"skill": "jobs.lookup", "id": "job-001"})
    assert data["id"] == "job-001"
    assert data["title"] == "Senior AI Agent Engineer"
    assert data["company_id"] == "biz-agentforge"
    assert data["remote"] is True
    assert "python" in data["skills_required"]


def test_jobs_lookup_not_found(client):
    """jobs.lookup with invalid id returns error."""
    result = _send(client, {"skill": "jobs.lookup", "id": "job-nonexistent"})
    assert result["status"]["state"] == "failed"


def test_jobs_post(client):
    """jobs.post creates a new job posting."""
    data = _send(client, {"skill": "jobs.post",
                          "id": "job-test", "title": "Test Position",
                          "company_id": "biz-agentforge",
                          "description": "Automated test job posting",
                          "location": "Remote", "remote": True,
                          "employment_type": "contract",
                          "salary_min_cents": 8000000,
                          "salary_max_cents": 12000000,
                          "skills_required": ["testing", "qa"],
                          "industry": "AI/ML", "category": "Engineering"})
    assert data["status"] == "posted"
    assert data["id"] == "job-test"
    # Verify searchable
    search = _send(client, {"skill": "jobs.search", "q": "Test Position"})
    assert search["total"] >= 1


def test_jobs_categories(client):
    """jobs.categories returns job categories."""
    data = _send(client, {"skill": "jobs.categories"})
    assert "fields" in data
    assert "categories" in data
    assert len(data["categories"]) >= 3
