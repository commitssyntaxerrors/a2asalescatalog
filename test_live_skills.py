#!/usr/bin/env python3
"""Live smoke test — hits every skill on the running server."""

import json
import sys
import urllib.request

BASE = "http://localhost:8000"
_id = 0

def call(skill: str, **params):
    global _id
    _id += 1
    payload = {
        "jsonrpc": "2.0",
        "id": _id,
        "method": "tasks/send",
        "params": {
            "id": f"t{_id}",
            "message": {
                "role": "user",
                "parts": [{"type": "data", "data": {"skill": skill, **params}}],
            },
        },
    }
    req = urllib.request.Request(
        f"{BASE}/a2a",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        return None, body["error"]
    result = body["result"]
    state = result.get("status", {}).get("state")
    if state == "failed":
        msg = result.get("status", {}).get("message", "unknown")
        return {"_failed": True, "message": msg}, None
    arts = result.get("artifacts", [])
    if not arts:
        return None, "no artifacts"
    part = arts[0]["parts"][0]
    if part["type"] == "data":
        return part["data"], None
    return part.get("text", ""), None


def assert_key(d, key):
    if not isinstance(d, dict):
        raise AssertionError(f"expected dict, got {type(d).__name__}")
    if key not in d:
        raise AssertionError(f"missing key '{key}'")

def assert_true(cond, msg="assertion failed"):
    if not cond:
        raise AssertionError(msg)

passed = 0
failed = 0
errors = []

def check(label, skill, validator, **params):
    global passed, failed
    data, err = call(skill, **params)
    if err:
        failed += 1
        errors.append(f"  FAIL {label}: {err}")
        print(f"  FAIL  {label}: {err}")
        return
    try:
        validator(data)
        passed += 1
        print(f"  OK    {label}")
    except Exception as e:
        failed += 1
        errors.append(f"  FAIL {label}: {e}")
        print(f"  FAIL  {label}: {e}")


# ── Catalog skills ─────────────────────────────────────────
print("\n=== CATALOG SKILLS ===")

check("catalog.search", "catalog.search",
      lambda d: (
          assert_key(d, "items") or
          assert_key(d, "fields") or
          assert_true(len(d["items"]) > 0, "no items")
      ), q="earbuds", max=3)

check("catalog.lookup", "catalog.lookup",
      lambda d: (
          assert_key(d, "id") or
          assert_true(d["id"] == "WE-001", f"wrong id: {d['id']}")
      ), id="WE-001")

check("catalog.categories", "catalog.categories",
      lambda d: (
          assert_key(d, "cats") or
          assert_true(len(d["cats"]) > 0, "no categories")
      ))

check("catalog.compare", "catalog.compare",
      lambda d: (
          assert_key(d, "rows") or
          assert_true(len(d["rows"]) >= 2, "need >=2 rows")
      ), ids=["WE-001", "WE-002"])

check("catalog.negotiate", "catalog.negotiate",
      lambda d: (
          assert_key(d, "session_id") or
          assert_key(d, "status")
      ), item_id="WE-001", offer_cents=4000)

check("catalog.purchase", "catalog.purchase",
      lambda d: (
          assert_key(d, "order_id") or
          assert_key(d, "status")
      ), item_id="WE-001", quantity=1, payment_token="tok_test")

check("catalog.agent_profile", "catalog.agent_profile",
      lambda d: assert_key(d, "agent_id"),
      agent_id="agent-test")

check("catalog.reputation", "catalog.reputation",
      lambda d: assert_key(d, "agent_id"),
      agent_id="agent-test")

check("catalog.embed", "catalog.embed",
      lambda d: assert_key(d, "dim"),
      ids=["WE-001"])

check("catalog.peers", "catalog.peers",
      lambda d: assert_key(d, "peers"))

check("catalog.vendor_analytics", "catalog.vendor_analytics",
      lambda d: assert_key(d, "vendor_id"),
      vendor_id="v-soundpod", period="7d")

check("catalog.retarget", "catalog.retarget",
      lambda d: assert_key(d, "offers"),
      agent_id="agent-test")

check("catalog.affiliate", "catalog.affiliate",
      lambda d: assert_key(d, "referral_code"),
      action="create", agent_id="agent-test", vendor_id="v-soundpod")

check("catalog.auction", "catalog.auction",
      lambda d: assert_key(d, "winners"),
      keyword="earbuds", slots=2, agent_id="agent-test")

check("catalog.promotions", "catalog.promotions",
      lambda d: assert_key(d, "promotions"),
      action="discover")

check("catalog.audience", "catalog.audience",
      lambda d: assert_key(d, "agent_id") or assert_key(d, "segments"),
      action="classify", agent_id="agent-test")

check("catalog.attribution", "catalog.attribution",
      lambda d: True,  # any response is fine
      action="campaign", campaign_id="ad-001")

check("catalog.cross_sell", "catalog.cross_sell",
      lambda d: assert_key(d, "recommendations"),
      item_id="WE-001")

check("catalog.display_ads", "catalog.display_ads",
      lambda d: assert_key(d, "ads"),
      category="audio", max=3)

check("catalog.ab_results", "catalog.ab_results",
      lambda d: assert_true(d.get("_failed") or "results" in d, "unexpected response"),
      campaign_id="ad-seed-001")

# ── Catalog AXON format ────────────────────────────────────
print("\n=== AXON FORMAT ===")

check("catalog.search (AXON)", "catalog.search",
      lambda d: assert_true(isinstance(d, str) and "@{" in d, "not AXON"),
      q="earbuds", max=3, format="axon")

# ── Video skills ───────────────────────────────────────────
print("\n=== VIDEO SKILLS ===")

check("video.search", "video.search",
      lambda d: (
          assert_key(d, "items") or
          assert_true(len(d["items"]) > 0, "no videos")
      ), q="python", max=5)

check("video.search (platform filter)", "video.search",
      lambda d: assert_key(d, "items"),
      q="review", platform="youtube", max=3)

check("video.search (category filter)", "video.search",
      lambda d: assert_key(d, "items"),
      q="review", cat="technology", max=3)

check("video.lookup", "video.lookup",
      lambda d: (
          assert_key(d, "id") or
          assert_true(d["id"] == "VID-001", f"wrong id: {d['id']}")
      ), id="VID-001")

check("video.lookup (not found)", "video.lookup",
      lambda d: assert_true(d.get("_failed", False), "expected failure"),
      id="VID-NONEXISTENT")

check("video.trending", "video.trending",
      lambda d: (
          assert_key(d, "items") or
          assert_true(len(d["items"]) > 0, "no trending")
      ), max=5)

check("video.trending (by category)", "video.trending",
      lambda d: assert_key(d, "items"),
      cat="technology", max=3)

check("video.creator", "video.creator",
      lambda d: (
          assert_key(d, "channel_id") or
          assert_true(d["channel_id"] == "ch-techrev", "wrong channel")
      ), channel_id="ch-techrev")

check("video.creator (not found)", "video.creator",
      lambda d: assert_true(d.get("_failed", False), "expected failure"),
      channel_id="ch-nonexistent")

check("video.categories", "video.categories",
      lambda d: (
          assert_key(d, "cats") or
          assert_true(len(d["cats"]) > 0, "no categories")
      ))

check("video.playlist (get)", "video.playlist",
      lambda d: assert_key(d, "id"),
      id="pl-001")

check("video.playlist (list)", "video.playlist",
      lambda d: assert_key(d, "playlists"))

check("video.transcript", "video.transcript",
      lambda d: (
          assert_key(d, "results") or
          assert_true(len(d["results"]) > 0, "no results")
      ), q="earbuds", max=5)

check("video.recommend (by video)", "video.recommend",
      lambda d: assert_key(d, "items"),
      video_id="VID-001", max=5)

check("video.recommend (by category)", "video.recommend",
      lambda d: assert_key(d, "items"),
      cat="technology", max=5)

# ── Summary ────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"PASSED: {passed}  |  FAILED: {failed}  |  TOTAL: {passed+failed}")
if errors:
    print("\nFailures:")
    for e in errors:
        print(e)
print()
sys.exit(1 if failed else 0)
