# A2A Sales Catalog — Specification Sheet

**Version:** 0.6.0-draft
**Date:** 2026-03-19
**Status:** Draft

---

## 1. Executive Summary

The **A2A Sales Catalog** is an agent-to-agent marketplace that exposes structured product, service, and vendor information to autonomous AI agent orchestrators over the [A2A (Agent-to-Agent) protocol](https://github.com/google/A2A). Instead of web-scraping fragile HTML, consumer agents query a single catalog endpoint and receive compact, machine-optimized responses they can reason over immediately.

The marketplace is **ad-supported**: businesses pay for placement and priority ranking, similar to how search engines monetize sponsored results. Organic (non-sponsored) results are always included to maintain trust, but sponsored results may be ranked higher or annotated.

---

## 2. Problem Statement

| Problem | Impact |
|---|---|
| Agents must web-scrape to find product info | Brittle, blocked by CAPTCHAs, legally gray |
| No structured commerce data layer for agents | Every orchestrator reinvents the wheel |
| Businesses have no way to reach AI agents | A massive new distribution channel is inaccessible |
| Existing APIs (Amazon, Shopify, etc.) are siloed | Agents need one interface, not dozens of API keys |

---

## 3. Core Concepts

### 3.1 Actors

| Actor | Role |
|---|---|
| **Consumer Agent** | An end-user's AI agent/orchestrator that needs to find or compare products/services |
| **Catalog Server** | The A2A Sales Catalog marketplace — answers queries, serves listings |
| **Vendor** | A business that lists wares in the catalog |
| **Advertiser** | A vendor (or third party) that pays for promoted placement |

### 3.2 Agent Card

The Catalog Server publishes a standard A2A Agent Card at `/.well-known/agent.json`:

```json
{
  "name": "A2A Sales Catalog",
  "description": "Agent marketplace for product and service discovery",
  "url": "https://catalog.example.com",
  "version": "0.1.0",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "skills": [
    {
      "id": "catalog.search",
      "name": "Search Catalog",
      "description": "Search for products, services, or vendors by query"
    },
    {
      "id": "catalog.lookup",
      "name": "Lookup Item",
      "description": "Get full details for a specific catalog item by ID"
    },
    {
      "id": "catalog.categories",
      "name": "Browse Categories",
      "description": "List available product/service categories"
    },
    {
      "id": "catalog.compare",
      "name": "Compare Items",
      "description": "Compare two or more items side by side"
    }
  ],
  "defaultInputModes": ["application/json"],
  "defaultOutputModes": ["application/json"]
}
```

---

## 4. Wire Format — Compact Agent Interchange (CAI)

### 4.1 Design Goals

LLMs do **not** need markdown, XML, or verbose JSON to reason. The wire format must be:

1. **Minimal** — no redundant keys, no verbose nesting
2. **Flat** — prefer arrays of tuples over nested objects where possible
3. **Typed implicitly** — strings stay strings, numbers stay numbers, no wrapping
4. **JSON-compatible** — parseable by any JSON parser (no custom binary)
5. **Streamable** — line-delimited JSON (JSONL) for multi-result responses

### 4.2 Envelope

Every A2A message uses the standard JSON-RPC 2.0 envelope per the A2A spec, but the `result` payloads inside are optimized for compactness.

**Request:**
```json
{"jsonrpc":"2.0","id":1,"method":"tasks/send","params":{"id":"t1","message":{"role":"user","parts":[{"type":"data","data":{"skill":"catalog.search","q":"wireless earbuds","max":5}}]}}}
```

**Response:**
```json
{"jsonrpc":"2.0","id":1,"result":{"id":"t1","status":{"state":"completed"},"artifacts":[{"parts":[{"type":"data","data":{"items":[["WE-001","SoundPod Pro","wireless earbuds, ANC, 30h battery",4999,"soundpod.com",4.6,1,"sp"],["WE-002","BassX Buds","wireless earbuds, deep bass, IPX5",3499,"bassx.io",4.3,0,null]],"currency":"USD","fields":["id","name","desc","price_cents","vendor","rating","sponsored","ad_tag"]}}]}]}}
```

### 4.3 Compact Item Encoding

Items are encoded as **positional arrays** (tuples) with a `fields` key that defines the schema once per response:

```
fields: ["id","name","desc","price_cents","vendor","rating","sponsored","ad_tag"]
items: [
  ["WE-001","SoundPod Pro","wireless earbuds, ANC",4999,"soundpod.com",4.6,1,"sp"],
  ["WE-002","BassX Buds","wireless earbuds, bass",3499,"bassx.io",4.3,0,null]
]
```

**Why tuples?**
- A 10-item result set with named-key objects: ~2.8 KB
- Same data as positional arrays + field header: ~1.1 KB
- **~60% smaller** — less tokens in, less tokens out, lower cost for everyone

### 4.4 Sponsored Results

| Field | Type | Meaning |
|---|---|---|
| `sponsored` | `0 \| 1` | Whether this item is a paid placement |
| `ad_tag` | `string \| null` | Short advertiser campaign tag for attribution tracking |

Sponsored items are **always disclosed** via the `sponsored` field. Consumer agents can filter them out or present them transparently to users.

---

## 5. Wire Format — AXON (Agent eXchange Object Notation)

### 5.1 Overview

**AXON** is a proprietary, token-minimized plaintext wire format purpose-built for agent-to-agent commerce communication. While the default CAI format reduces payload size within JSON, AXON eliminates JSON overhead entirely, achieving **55-70% token reduction** versus standard JSON.

Agents request AXON encoding by including `"format": "axon"` in any skill invocation. The server returns the response as a `text` part (instead of `data` part) containing AXON-encoded content.

### 5.2 Design Principles

| Principle | Mechanism |
|---|---|
| **Sigil-typed values** | Commerce-domain type prefixes: `$4999` (price), `★4.5` (rating), `#WE-001` (ID), `~vendor` (vendor ref), `@agent-001` (agent ref), `%10` (percentage), `!` (sponsored flag) |
| **Schema-indexed columns** | `@{field|field|field}` declares column schema once; rows use `>` prefix |
| **Pipe delimiters** | `\|` separates fields (avoids comma/decimal ambiguity) |
| **Section blocks** | `[name]` / `[/name]` for nested structures |
| **Elided nulls** | Empty pipe segments `\|\|` represent null/missing |
| **Inline metadata** | `<n=5 page=1>` for counts, pagination, flags |

### 5.3 Syntax Reference

**Tabular data (search results, category lists):**
```
@{id|name|desc|price_cents|vendor|rating|sponsored|ad_tag}
<n=3>
> #WE-001|SoundPod Pro|Premium wireless earbuds|$4999|~soundpod.io|★4.5|0|
> #WE-002|SoundPod Lite|Budget wireless earbuds|$2999|~soundpod.io|★4.2|0|
> #WE-003|SoundPod Max|Flagship noise-cancelling|$5999|~soundpod.io|★4.8|!|ad-001
```

**Scalar key-value (item details, order confirmations):**
```
item_id=#WE-001
name=SoundPod Pro
price_cents=$4999
rating=★4.5
vendor_id=~v-soundpod
```

**Nested structures (cross-sell, promotions):**
```
item_id=#WE-001
[recommendations]
  @{item_id|rule_type|reason}
  <n=2>
  > #WE-003|upsell|Premium model with noise cancellation
  > #WE-004|cross_sell|Matching carrying case
[/recommendations]
```

### 5.4 Sigil Reference

| Sigil | Domain | Fields | Example |
|---|---|---|---|
| `$` | Price (cents) | `price_cents`, `bid_cents`, `budget_cents`, `discount_cents` | `$4999` |
| `★` | Rating | `rating` | `★4.5` |
| `#` | Entity ID | `id`, `item_id`, `order_id`, `campaign_id`, `promo_id` | `#WE-001` |
| `~` | Vendor ref | `vendor_id`, `vendor` | `~v-soundpod` |
| `@` | Agent ref | `agent_id`, `referring_agent_id` | `@agent-42` |
| `%` | Percentage | `discount_pct`, `ctr`, `cvr`, `confidence` | `%10` |
| `!` | Sponsored flag | `sponsored` | `!` (true) or empty (false) |

### 5.5 Requesting AXON Format

```json
{"jsonrpc":"2.0","id":1,"method":"tasks/send","params":{"id":"t1","message":{"role":"user","parts":[{"type":"data","data":{"skill":"catalog.search","q":"earbuds","max":3,"format":"axon"}}]}}}
```

The response uses `"type":"text"` instead of `"type":"data"`:
```json
{"jsonrpc":"2.0","id":1,"result":{"id":"t1","status":{"state":"completed"},"artifacts":[{"parts":[{"type":"text","text":"@{id|name|desc|price_cents|vendor|rating|sponsored|ad_tag}\n<n=3>\n> #WE-001|SoundPod Pro|Premium wireless earbuds|$4999|~soundpod.io|★4.5|0|\n..."}]}]}}
```

### 5.6 Comparison: JSON vs CAI vs AXON

| Metric | JSON (verbose) | CAI (positional JSON) | AXON (plaintext) |
|---|---|---|---|
| Format | Named-key objects | Positional arrays in JSON | Sigil-typed plaintext |
| Token reduction vs JSON | — | ~60% | ~65-70% |
| Parse complexity | Standard JSON | Standard JSON | Custom parser |
| Type information | Implicit | Implicit by position | Explicit via sigils |
| Human readability | High | Medium | High |
| Schema declaration | Per-object keys | `fields` array | `@{schema}` header |

---

## 6. API Skills (Endpoints)

### 5.1 `catalog.search`

Search the catalog by free-text query with optional filters.

**Input (in message part data):**
```json
{
  "skill": "catalog.search",
  "q": "noise cancelling headphones",
  "max": 10,
  "cat": "electronics",
  "price_max": 15000,
  "sort": "relevance"
}
```

| Param | Type | Required | Description |
|---|---|---|---|
| `skill` | string | yes | Must be `"catalog.search"` |
| `q` | string | yes | Search query |
| `max` | int | no | Max results (default 10, max 50) |
| `cat` | string | no | Category filter |
| `price_min` | int | no | Min price in cents |
| `price_max` | int | no | Max price in cents |
| `sort` | string | no | `"relevance"` (default), `"price_asc"`, `"price_desc"`, `"rating"` |
| `vendor` | string | no | Filter by vendor domain |

**Output:** `{ items: [tuple...], fields: [...], currency: "USD", total: int }`

### 5.2 `catalog.lookup`

Get full details for a single item.

**Input:**
```json
{
  "skill": "catalog.lookup",
  "id": "WE-001"
}
```

**Output:**
```json
{
  "id": "WE-001",
  "name": "SoundPod Pro",
  "desc": "Wireless earbuds with active noise cancellation and 30h battery life",
  "price_cents": 4999,
  "currency": "USD",
  "vendor": "soundpod.com",
  "rating": 4.6,
  "review_count": 2847,
  "attrs": [["battery","30h"],["driver","12mm"],["anc","yes"],["water","IPX4"]],
  "buy_url": "https://soundpod.com/pro?ref=a2acat",
  "images": ["https://cdn.catalog.example.com/we001-1.webp"],
  "sponsored": 1,
  "ad_tag": "sp"
}
```

### 5.3 `catalog.categories`

**Input:**
```json
{
  "skill": "catalog.categories",
  "parent": null
}
```

**Output:**
```json
{
  "cats": [
    ["electronics", "Electronics", 48210],
    ["home", "Home & Garden", 31044],
    ["fashion", "Fashion", 27891]
  ],
  "fields": ["id", "label", "item_count"]
}
```

### 5.4 `catalog.compare`

**Input:**
```json
{
  "skill": "catalog.compare",
  "ids": ["WE-001", "WE-002", "WE-003"]
}
```

**Output:**
```json
{
  "fields": ["id","name","price_cents","rating","review_count","battery","driver","anc","water"],
  "rows": [
    ["WE-001","SoundPod Pro",4999,4.6,2847,"30h","12mm","yes","IPX4"],
    ["WE-002","BassX Buds",3499,4.3,1203,"20h","10mm","no","IPX5"],
    ["WE-003","ClearAir S1",5999,4.8,4102,"40h","11mm","yes","IPX4"]
  ]
}
```

---

## 7. Agent Identity, Tracking & Interest Scoring

### 6.1 Agent Identity

Every consumer agent authenticates with an API key. The catalog assigns each key a unique **agent fingerprint** (`agent_id`) used to track behavior across sessions without exposing PII.

### 6.2 Repeat Visit Tracking

The catalog logs every query per `agent_id`:

| Event | Tracked Fields |
|---|---|
| Search | agent_id, query, category, timestamp |
| Lookup | agent_id, item_id, timestamp |
| Compare | agent_id, item_ids, timestamp |
| Negotiate | agent_id, item_id, offer, timestamp |
| Purchase | agent_id, item_id, amount, timestamp |

### 6.3 Interest Scoring Algorithm

Each agent accumulates an **interest score** per item and category based on repeat behavior:

```
interest_score = (
    search_hits × 1.0 +
    lookups × 3.0 +
    compares × 2.0 +
    negotiations × 5.0 +
    repeat_visits × 2.0 +    # same item viewed 2+ times
    recency_boost              # decay: score × 0.9^(days_since_last)
)
```

### 6.4 Intent Tiers

Based on the interest score, agents are classified into intent tiers:

| Tier | Score Range | Behavior |
|---|---|---|
| **Browse** | 0–5 | Casual browsing — standard results |
| **Consider** | 6–15 | Active comparison — results pre-cached, richer attrs returned |
| **High-Intent** | 16–30 | Likely to buy — vendors notified, priority response, negotiation enabled |
| **Ready-to-Buy** | 31+ | Imminent purchase — purchase protocol unlocked, exclusive offers surfaced |

### 6.5 Intent-Aware Advertising

Advertisers can bid differently per intent tier:

```json
{
  "bid_cents_browse": 5,
  "bid_cents_consider": 15,
  "bid_cents_high_intent": 50,
  "bid_cents_ready_to_buy": 100
}
```

High-intent queries cost more per-impression but convert at higher rates. This tiered bidding is the core monetization innovation — **ads priced by demonstrated agent purchase intent**.

### 6.6 `catalog.agent_profile` Skill

Agents can query their own profile to see their interest scores and intent tier:

**Input:**
```json
{
  "skill": "catalog.agent_profile"
}
```

**Output:**
```json
{
  "agent_id": "a-f7e2c",
  "reputation": 82,
  "intent_tier": "high_intent",
  "total_queries": 147,
  "top_interests": [
    ["audio", 24.5],
    ["electronics", 12.3]
  ],
  "item_interests": [
    ["WE-001", 18.0, "high_intent"],
    ["WE-003", 9.5, "consider"]
  ]
}
```

---

## 8. Agent Reputation & Trust Scores

### 7.1 Reputation Model

Each consumer agent builds a reputation score (0–100) based on:

| Factor | Weight | Description |
|---|---|---|
| Account age | +0.1/day | Longevity bonus (max 10) |
| Completed purchases | +5.0 each | Proves genuine commerce activity |
| Query consistency | +0.5 | Non-abusive query patterns |
| Vendor feedback | ±10.0 | Vendors rate agent interactions |
| Negotiation honor | +3.0 | Completing deals after negotiating |
| Violation penalties | -20.0 | Rate limit abuse, ToS violations |

### 7.2 Trust-Based Pricing

Vendors can offer tiered pricing based on agent reputation:

```json
{
  "price_cents": 4999,
  "trusted_price_cents": 4499,
  "reputation_threshold": 60
}
```

### 7.3 `catalog.reputation` Skill

**Input:**
```json
{
  "skill": "catalog.reputation"
}
```

**Output:**
```json
{
  "agent_id": "a-f7e2c",
  "score": 82,
  "factors": [["age", 10], ["purchases", 45], ["consistency", 15], ["feedback", 12]],
  "tier": "trusted",
  "benefits": ["trusted_pricing", "priority_response", "negotiation_access"]
}
```

---

## 9. Negotiation Protocol

### 8.1 Overview

Consumer agents can negotiate prices with the catalog (acting on behalf of vendors). This is **programmatic haggling** — the first structured negotiation protocol between AI agents for commerce.

### 8.2 Negotiation Flow

```
Consumer Agent                    Catalog Server
     │                                 │
     ├── catalog.negotiate ──────────► │  (initial offer)
     │                                 │
     │ ◄── counter / accept / reject ──┤
     │                                 │
     ├── catalog.negotiate ──────────► │  (counter-offer)
     │                                 │
     │ ◄── accept ─────────────────────┤
     │                                 │
     ├── catalog.purchase ───────────► │  (complete at agreed price)
     │                                 │
```

### 8.3 `catalog.negotiate` Skill

**Input:**
```json
{
  "skill": "catalog.negotiate",
  "item_id": "WE-001",
  "offer_cents": 4200,
  "session_id": null,
  "message": "Buying 3 units, looking for volume discount"
}
```

**Output:**
```json
{
  "session_id": "neg-a1b2c3",
  "status": "counter",
  "their_offer_cents": 4600,
  "your_offer_cents": 4200,
  "list_price_cents": 4999,
  "rounds_left": 2,
  "message": "We can offer 8% off for volume. Counter: $46.00"
}
```

### 8.4 Negotiation Rules

| Rule | Value |
|---|---|
| Max rounds per session | 5 |
| Min offer (floor) | 60% of list price |
| Auto-accept threshold | Within 5% of vendor floor |
| Reputation required | Score ≥ 40 |
| Session expiry | 1 hour |

---

## 10. Purchase Completion Protocol

### 9.1 Overview

Close the sale agent-to-agent. After discovery (search/lookup) and optional negotiation, the consumer agent can initiate a purchase entirely over A2A.

### 9.2 `catalog.purchase` Skill

**Input:**
```json
{
  "skill": "catalog.purchase",
  "item_id": "WE-001",
  "quantity": 1,
  "negotiate_session_id": "neg-a1b2c3",
  "payment_token": "pay_tok_xxxxx",
  "shipping": {
    "method": "standard",
    "address_token": "addr_tok_xxxxx"
  }
}
```

**Output:**
```json
{
  "order_id": "ord-x7y8z9",
  "status": "confirmed",
  "item_id": "WE-001",
  "quantity": 1,
  "unit_price_cents": 4600,
  "total_cents": 4600,
  "payment_status": "captured",
  "estimated_delivery": "2026-03-25",
  "tracking_url": "https://track.example.com/ord-x7y8z9"
}
```

### 9.3 Purchase Flow Security

| Concern | Mitigation |
|---|---|
| Payment credentials | Tokenized — catalog never sees raw card/bank data |
| Shipping address | Tokenized via address_token — PII never in transit |
| Replay attacks | Idempotency key in order_id + negotiate_session_id |
| Price manipulation | Final price locked by negotiate session or list price |

---

## 11. Federated Catalog Network

### 10.1 Overview

Multiple catalog servers can **peer with each other** and cross-list inventory — like DNS for product catalogs. No single point of failure, no centralized chokepoint.

### 10.2 Federation Protocol

Each catalog publishes peering information in its Agent Card:

```json
{
  "federation": {
    "enabled": true,
    "peers": [
      "https://electronics.catalog.example.com",
      "https://fashion.catalog.example.com"
    ],
    "accept_peers": true,
    "categories_served": ["electronics", "audio"]
  }
}
```

### 10.3 Cross-Catalog Search

When a query doesn't match local inventory, the catalog can fan-out to peers:

```
Consumer Agent ──► Catalog A ──► local results
                       │
                       ├──► Catalog B ──► peer results
                       │
                       └──► Catalog C ──► peer results
                       │
                  ◄── merged, deduplicated, ranked
```

### 10.4 `catalog.peers` Skill

**Input:**
```json
{
  "skill": "catalog.peers"
}
```

**Output:**
```json
{
  "fields": ["url", "name", "categories", "items_count", "status"],
  "peers": [
    ["https://electronics.catalog.example.com", "ElectroCat", ["electronics"], 48000, "online"],
    ["https://fashion.catalog.example.com", "StyleAgent", ["fashion"], 31000, "online"]
  ]
}
```

---

## 12. Semantic Embeddings Index

### 11.1 Overview

Each item in the catalog has a pre-computed **semantic embedding vector**. Consumer agents can request embeddings alongside search results to perform local re-ranking, clustering, or recommendation without extra round-trips.

### 11.2 Embedding Format

Embeddings are compact float32 arrays, base64-encoded for wire efficiency:

```json
{
  "skill": "catalog.search",
  "q": "wireless earbuds",
  "include_embeddings": true
}
```

Response includes an `emb` field per item tuple:

```json
{
  "fields": ["id","name","desc","price_cents","vendor","rating","sponsored","ad_tag","emb"],
  "items": [
    ["WE-001","SoundPod Pro","...",4999,"soundpod.com",4.6,1,"sp","base64..."]
  ]
}
```

### 11.3 `catalog.embed` Skill

Get embeddings for specific items or a free-text query:

**Input:**
```json
{
  "skill": "catalog.embed",
  "ids": ["WE-001", "WE-002"],
  "query": "comfortable earbuds for running"
}
```

**Output:**
```json
{
  "dim": 128,
  "query_emb": "base64...",
  "items": [
    ["WE-001", "base64..."],
    ["WE-002", "base64..."]
  ]
}
```

### 11.4 Use Cases

- **Local re-ranking**: Agent re-sorts results by cosine similarity to its own preference vector
- **Clustering**: Agent groups similar products without additional API calls
- **Recommendation**: Agent builds a preference profile from past embeddings

---

## 13. Vendor Analytics

### 12.1 Overview

Vendors get analytics on **agent behavior** — not human behavior. This is a new class of analytics that doesn't exist today.

### 12.2 `catalog.vendor_analytics` Skill

**Input (vendor-authenticated):**
```json
{
  "skill": "catalog.vendor_analytics",
  "vendor_id": "v-soundpod",
  "period": "7d"
}
```

**Output:**
```json
{
  "vendor_id": "v-soundpod",
  "period": "7d",
  "summary": {
    "total_impressions": 12847,
    "unique_agents": 3421,
    "lookups": 1893,
    "comparisons": 647,
    "negotiations": 89,
    "purchases": 34,
    "conversion_rate": 0.026
  },
  "top_queries": [
    ["wireless earbuds", 4521],
    ["noise cancelling", 2103],
    ["running earbuds", 1847]
  ],
  "comparison_losses": [
    ["WE-002", 234, "price"],
    ["WE-003", 189, "rating"]
  ],
  "agent_intent_breakdown": {
    "browse": 2100,
    "consider": 890,
    "high_intent": 341,
    "ready_to_buy": 90
  },
  "repeat_agent_rate": 0.41
}
```

### 12.3 Analytics Insights

| Metric | What it tells vendors |
|---|---|
| `comparison_losses` | Which competitors they lose to and why |
| `agent_intent_breakdown` | How many agents are close to buying |
| `repeat_agent_rate` | Percentage of agents that come back |
| `top_queries` | What terms drive traffic to their products |
| `conversion_rate` | Search-to-purchase funnel efficiency |

---

## 14. Advertising Model

### 13.1 How It Works

1. **Vendors register** and list products for free (organic listings).
2. **Advertisers bid** on keywords/categories for promoted placement.
3. When a consumer agent searches, the catalog:
   - Retrieves organic results ranked by relevance/rating
   - Inserts sponsored results based on bid rank and relevance
   - Marks every sponsored result with `sponsored: 1`
4. Advertisers are charged **per-impression** (result served) or **per-action** (buy_url clicked).

### 13.2 Trust Contract

- Sponsored results are **always marked** — agents that strip or hide the flag violate ToS.
- Organic results are **never suppressed** — sponsored items supplement, not replace.
- The ratio of sponsored to organic is capped (default: max 2 sponsored per 10 results).
- Agents may request `sponsored: 0` to exclude all ads (premium tier).

### 13.3 Revenue Tiers

| Tier | Cost | Sponsored | Rate Limit |
|---|---|---|---|
| Free | $0 | Included (max 20%) | 100 req/min |
| Pro | $49/mo | Opt-out available | 1,000 req/min |
| Enterprise | Custom | Opt-out, SLA, dedicated | Unlimited |

---

## 15. Display & Banner Ads

### 14.1 Overview

Beyond search-result sponsorship, vendors can purchase **display ad placements** that appear in non-search contexts (item detail pages, category browsing, promotional slots). Display ads carry structured creative data (headline, body, image URL) that consumer agents can render in any format.

### 14.2 Placement Logic

1. The catalog maintains ad campaigns with `promo_headline`, `promo_body`, and `promo_image_url` fields.
2. When a consumer agent calls `catalog.display_ads`, the engine filters active campaigns by optional `category` or `item_id` context.
3. Results are ordered by bid amount (descending) and respect frequency capping and dayparting rules.
4. Each returned ad includes a `campaign_id`, creative data, and the sponsoring vendor.

### 14.3 Request / Response

```json
// Request
{"skill": "catalog.display_ads", "category": "audio", "max": 3}

// Response
{"ads": [{"campaign_id": "ad-001", "headline": "...", "body": "...", "image_url": "...", "vendor_id": "v-001", "item_id": "WE-001"}]}
```

---

## 16. Retargeting & Remarketing

### 15.1 Overview

Agents that viewed items but did not purchase receive **personalized retargeting offers** with time-decayed discounts, increasing urgency as time passes.

### 15.2 Discount Tiers

| Time Since View | Discount |
|---|---|
| < 1 day | 5% |
| 1–3 days | 10% |
| 3–7 days | 15% |
| > 7 days | No offer (expired) |

### 15.3 How It Works

1. The Agent Tracker records every `view` event with timestamps.
2. When `catalog.retarget` is invoked, the engine checks all viewed-but-not-purchased items.
3. Offers are generated with the appropriate discount tier, expiry timestamp, and a unique offer code.

### 15.4 Request / Response

```json
// Request
{"skill": "catalog.retarget", "agent_id": "agent-001"}

// Response
{"offers": [{"item_id": "WE-001", "discount_pct": 10, "expires": "2026-03-22T00:00:00Z", "offer_code": "rt-abc123"}]}
```

---

## 17. Affiliate & Referral Program

### 16.1 Overview

Consumer agents can **earn commission** by referring other agents to purchase items. Each referral generates a unique tracking code; when a referred agent purchases, the referring agent earns a percentage of the sale.

### 16.2 Commission Structure

- Default commission: **5%** (500 basis points)
- Per-vendor overrides supported via `commission_bps` field
- Commissions tracked per referral code with running totals

### 16.3 Workflow

1. Agent calls `catalog.affiliate` with `action: "create"` and `vendor_id`
2. Server generates a unique referral code (`ref-xxxx`)
3. Referring agent shares the code
4. At purchase time, buyer includes `referral_code` in the request
5. Commission is recorded and credited to the referring agent

### 16.4 Request / Response

```json
// Create referral
{"skill": "catalog.affiliate", "action": "create", "agent_id": "agent-001", "vendor_id": "v-001"}
// Response
{"referral_code": "ref-abc123", "commission_bps": 500}

// Check status
{"skill": "catalog.affiliate", "action": "status", "agent_id": "agent-001"}
// Response
{"links": [{"vendor_id": "v-001", "code": "ref-abc123", "total_earned_cents": 250}]}
```

---

## 18. Real-Time Bidding (RTB)

### 17.1 Overview

For high-value placement slots, multiple advertisers compete in a **per-request real-time auction**. The highest bidders win impression slots, subject to frequency capping and budget constraints.

### 17.2 Auction Flow

1. Consumer agent calls `catalog.auction` with a keyword/category and desired number of slots
2. Engine collects all matching campaigns with remaining budget
3. Campaigns are filtered by frequency caps and schedule constraints
4. Intent-tiered bid adjustments are applied based on the requesting agent's intent tier
5. Winners are ranked by effective bid price; top N win the slots
6. Each winner's budget is decremented by their bid amount

### 17.3 Request / Response

```json
// Request
{"skill": "catalog.auction", "keyword": "earbuds", "slots": 2, "agent_id": "agent-001"}

// Response
{"winners": [{"campaign_id": "ad-001", "bid_cents": 150, "item_id": "WE-001"}, {"campaign_id": "ad-002", "bid_cents": 120, "item_id": "WE-002"}]}
```

---

## 19. Frequency Capping

### 18.1 Overview

To prevent ad fatigue and ensure a healthy agent experience, each campaign can set a **maximum number of impressions** per agent within a rolling time window.

### 18.2 Configuration

| Field | Description | Default |
|---|---|---|
| `freq_cap_count` | Max impressions per window | 10 |
| `freq_cap_window_secs` | Rolling window in seconds | 3600 (1 hr) |

### 18.3 Enforcement

- Before serving an ad, the engine queries the `frequency_records` table for the agent+campaign pair.
- If impressions within the window >= `freq_cap_count`, the campaign is suppressed for that agent.
- Frequency caps apply to search ads, display ads, and RTB auctions uniformly.

---

## 20. A/B Testing for Ad Creatives

### 19.1 Overview

Campaigns can define multiple **creative variants** (A/B groups) to test headlines, copy, images, or CTAs. The engine distributes impressions across variants and tracks performance metrics.

### 19.2 Event Tracking

Every ad interaction logs an event with the `ab_group` tag:
- **impression**: The ad was served to an agent
- **click**: The agent followed up on the ad (visited the item)
- **conversion**: The agent purchased the advertised item

### 19.3 Results Aggregation

The `catalog.ab_results` skill returns per-variant aggregates:

```json
{"results": [
  {"variant": "A", "impressions": 500, "clicks": 50, "conversions": 10, "ctr": 0.10, "cvr": 0.02},
  {"variant": "B", "impressions": 480, "clicks": 72, "conversions": 15, "ctr": 0.15, "cvr": 0.03}
]}
```

---

## 21. Audience Segments & Lookalike Targeting

### 20.1 Overview

Agents are classified into **behavioral segments** based on their interaction patterns. Vendors can target campaigns to specific segments for higher relevance.

### 20.2 Default Segments

| Segment | ID | Criteria |
|---|---|---|
| Bargain Hunters | seg-bargain | High search volume, low conversion, price-sensitive |
| Premium Buyers | seg-premium | High purchase volume, low price sensitivity |
| Researchers | seg-research | Many views and comparisons, few purchases |
| Impulse Buyers | seg-impulse | Quick purchase after first search |
| Loyal Repeat Buyers | seg-loyal | Multiple purchases from same vendors |

### 20.3 Classification

The `catalog.audience` skill with `action: "classify"` analyzes an agent's event history and assigns/updates segment memberships. Vendors can then use `target_segments` on campaigns to limit delivery to specific segments.

---

## 22. Conversion Attribution

### 21.1 Overview

Multi-touch **conversion attribution** tracks every ad touchpoint an agent interacted with before making a purchase. This allows vendors to understand which campaigns and channels drove conversions.

### 21.2 Attribution Models

| Model | Description |
|---|---|
| **First Touch** | 100% credit to the first ad the agent interacted with |
| **Last Touch** | 100% credit to the last ad before purchase |

### 21.3 Touchpoint Tracking

Every time a sponsored result is served, a touchpoint is recorded:
- `agent_id`, `campaign_id`, `item_id`, `touch_type` (impression, click, view), `timestamp`

When a purchase occurs, the engine runs attribution and stores results:
- `first_touch_campaign_id`, `last_touch_campaign_id`, `agent_id`, `item_id`, `order_id`

### 21.4 Request / Response

```json
// Campaign attribution
{"skill": "catalog.attribution", "action": "campaign", "campaign_id": "ad-001"}
// Response
{"campaign_id": "ad-001", "first_touch_count": 12, "last_touch_count": 8}

// Agent journey
{"skill": "catalog.attribution", "action": "journey", "agent_id": "agent-001", "item_id": "WE-001"}
// Response
{"touchpoints": [{"campaign_id": "ad-001", "touch_type": "impression", "ts": 1710800000}, ...]}
```

---

## 23. Promotional Campaigns (Coupons, Flash Sales, Bundles)

### 22.1 Overview

Vendors create **promotional campaigns** — coupons, flash sales, and bundle deals — with configurable discount types, usage limits, minimum purchase amounts, and expiry dates.

### 22.2 Promotion Types

| Type | Description |
|---|---|
| `coupon` | A reusable code for a percentage or fixed discount |
| `flash_sale` | Time-limited deep discount |
| `bundle` | Discount when purchasing multiple qualifying items |

### 22.3 Discount Types

| Discount Type | Description |
|---|---|
| `percent` | Percentage off (e.g., 10% off) |
| `fixed_cents` | Fixed amount off in cents (e.g., 500 = $5 off) |

### 22.4 Workflow

1. Agent calls `catalog.promotions` with `action: "discover"` to list active promos
2. Agent validates a code with `action: "validate"` before purchase
3. At purchase time, agent includes `promo_code` in the request; server verifies and applies discount
4. Promo usage counter increments; once `max_uses` is reached, the code expires

---

## 24. Cross-Sell & Upsell Recommendations

### 23.1 Overview

Vendors define **cross-sell and upsell rules** that recommend complementary or upgraded products when an agent views or purchases a specific item.

### 23.2 Rule Types

| Type | Description |
|---|---|
| `cross_sell` | Recommend a complementary product (e.g., earbuds → case) |
| `upsell` | Recommend a premium alternative (e.g., basic → pro model) |
| `bundle` | Recommend items frequently bought together |

### 23.3 Request / Response

```json
// Request
{"skill": "catalog.cross_sell", "item_id": "WE-001"}

// Response
{"recommendations": [{"item_id": "WE-003", "rule_type": "upsell", "reason": "Premium model with noise cancellation"}]}
```

---

## 25. Creative Rotation

### 24.1 Overview

Campaigns with multiple creative assets (headlines, images, CTAs) use **weighted round-robin rotation** to distribute impressions across variants.

### 24.2 Configuration

- `creatives`: JSON array of creative objects, each with `headline`, `body`, `image_url`
- `creative_weights`: JSON array of numeric weights corresponding to each creative

### 24.3 Selection Algorithm

The engine tracks a rotation index per campaign and selects creatives according to their weights. This ensures higher-weighted creatives receive proportionally more impressions while still exposing all variants.

---

## 26. Campaign Scheduling & Dayparting

### 25.1 Overview

Campaigns can be restricted to specific **date ranges** and **time-of-day windows** (dayparting), allowing vendors to run promotions during peak hours or limited-time events.

### 25.2 Configuration

| Field | Description | Example |
|---|---|---|
| `schedule_start` | Campaign start date (ISO 8601) | `2026-03-01T00:00:00Z` |
| `schedule_end` | Campaign end date (ISO 8601) | `2026-03-31T23:59:59Z` |
| `schedule_hours` | JSON array of active hours (0–23) | `[9, 10, 11, 12, 13, 14, 15, 16, 17]` |
| `schedule_days` | JSON array of active weekdays (0=Mon–6=Sun) | `[0, 1, 2, 3, 4]` |

### 25.3 Enforcement

Before serving any ad, the engine checks:
1. Is the current UTC time between `schedule_start` and `schedule_end`?
2. Is the current hour in `schedule_hours`?
3. Is the current weekday in `schedule_days`?

If any check fails, the campaign is skipped.

---

## 27. Architecture Overview

```
┌─────────────────┐         A2A/JSON-RPC          ┌──────────────────────┐
│  Consumer Agent  │ ────────────────────────────► │   A2A Sales Catalog  │
│  (Orchestrator)  │ ◄──────────────────────────── │       Server         │
└─────────────────┘     Compact tuple responses    │                      │
                                                   │  ┌────────────────┐  │
┌─────────────────┐                                │  │  Search Index  │  │
│  Consumer Agent  │ ─────────────────────────────►│  │  (items, ads)  │  │
│  (Another user)  │                               │  └────────────────┘  │
└─────────────────┘                                │  ┌────────────────┐  │
                                                   │  │  Ad Engine     │  │
┌─────────────────┐    Vendor API / Dashboard      │  │  (bidding,     │  │
│     Vendor      │ ─────────────────────────────► │  │   attribution) │  │
│   (Business)    │                                │  └────────────────┘  │
└─────────────────┘                                │  ┌────────────────┐  │
                                                   │  │  Rate Limiter  │  │
                                                   │  │  & Auth        │  │
                                                   │  └────────────────┘  │
                                                   └──────────────────────┘
```

### 26.1 Components

| Component | Tech | Purpose |
|---|---|---|
| **A2A Server** | Python (FastAPI / Starlette) | Handles A2A protocol, routes skills |
| **Search Index** | SQLite FTS5 → Meilisearch | Full-text + faceted product search |
| **Ad Engine** | In-process module | Keyword bidding, intent-tiered insertion, display ads, cross-sell, dayparting, creative rotation |
| **Agent Tracker** | In-process module | Visit logging, interest scoring, intent classification |
| **Negotiation Engine** | In-process module | Offer/counter-offer, vendor floor pricing |
| **Purchase Handler** | In-process module | Order creation, payment token validation |
| **Federation Router** | In-process module | Peer discovery, cross-catalog fan-out |
| **Embedding Index** | NumPy / FAISS (future) | Semantic vectors for items and queries |
| **Vendor Analytics** | In-process module | Agent behavior analytics per vendor |
| **Retargeting Engine** | In-process module | Time-decayed remarketing offers |
| **Affiliate Engine** | In-process module | Referral code generation, commission tracking |
| **RTB Engine** | In-process module | Real-time bidding auctions with freq cap integration |
| **Promotion Engine** | In-process module | Coupons, flash sales, bundle deals, promo code validation |
| **Audience Engine** | In-process module | Behavioral segment classification and lookalike targeting |
| **Attribution Engine** | In-process module | Multi-touch conversion attribution (first/last touch) |
| **Video Content Engine** | In-process module | Cross-platform video discovery, transcript search, creator profiles, playlists, trending, recommendations |
| **Auth & Rate Limit** | API key + token bucket | Tiered access control |
| **Vendor Portal** | Separate web app (future) | Product upload, ad campaign management |
| **Data Store** | PostgreSQL | Canonical product + vendor + ad data |

---

## 28. Security & Trust

| Concern | Mitigation |
|---|---|
| Prompt injection via product descriptions | Sanitize all vendor text; strip control chars |
| Agent impersonation | API key auth + optional mTLS |
| Ad fraud (fake impressions) | Rate limiting, agent fingerprinting, anomaly detection |
| Data poisoning by vendors | Review pipeline, flagging system |
| Denial of service | Token bucket rate limiter, max response size |
| Negotiation abuse | Max rounds, min offer floor, reputation gate |
| Payment fraud | Tokenized payments, never store raw credentials |
| Interest score gaming | Rate-limited event ingestion, anomaly detection on visit patterns |
| Federation spoofing | Peer verification via Agent Card + mutual TLS |
| Embedding extraction | Rate-limit embed requests, watermark vectors |

---

## 29. Data Model (Core Entities)

### Items
| Field | Type | Notes |
|---|---|---|
| id | string | Unique, prefixed by category (e.g., "WE-001") |
| name | string | Product/service name |
| desc | string | Short description (max 280 chars) |
| price_cents | int | Price in smallest currency unit |
| currency | string | ISO 4217 (default "USD") |
| vendor_id | string | Foreign key to vendor |
| category_id | string | Foreign key to category |
| rating | float | 0.0–5.0 aggregate |
| review_count | int | Number of reviews |
| attrs | [[k,v]...] | Key-value attribute pairs |
| buy_url | string | Affiliate/purchase link |
| images | [string...] | CDN image URLs |
| active | bool | Listed or delisted |
| created_at | datetime | |
| updated_at | datetime | |

### Vendors
| Field | Type |
|---|---|
| id | string |
| name | string |
| domain | string |
| verified | bool |
| tier | string |

### Ad Campaigns
| Field | Type |
|---|---|
| id | string |
| vendor_id | string |
| keywords | [string...] |
| categories | [string...] |
| bid_cents | int |
| bid_cents_browse | int |
| bid_cents_consider | int |
| bid_cents_high_intent | int |
| bid_cents_ready_to_buy | int |
| budget_cents | int |
| spent_cents | int |
| active | bool |
| ad_tag | string |

### Agent Profiles
| Field | Type | Notes |
|---|---|---|
| agent_id | string | Derived from API key hash |
| reputation | float | 0–100 trust score |
| total_queries | int | Lifetime query count |
| total_purchases | int | Completed purchases |
| created_at | datetime | First seen |
| last_seen_at | datetime | Most recent activity |

### Agent Events (Visit Log)
| Field | Type | Notes |
|---|---|---|
| id | string | Event ID |
| agent_id | string | Who |
| event_type | string | search, lookup, compare, negotiate, purchase |
| item_id | string | null | Item referenced (if applicable) |
| query | string | null | Search query (if applicable) |
| category | string | null | Category context |
| metadata | json | Additional event data |
| timestamp | datetime | When |

### Agent Interest Scores
| Field | Type | Notes |
|---|---|---|
| agent_id | string | Compound key with item_id/category |
| item_id | string | null | Per-item interest |
| category | string | null | Per-category interest |
| score | float | Computed interest score |
| intent_tier | string | browse, consider, high_intent, ready_to_buy |
| visit_count | int | Repeat visits to this item |
| last_event_at | datetime | For recency decay |

### Negotiation Sessions
| Field | Type | Notes |
|---|---|---|
| session_id | string | Unique negotiation ID |
| agent_id | string | Consumer agent |
| item_id | string | Item being negotiated |
| status | string | open, counter, accepted, rejected, expired |
| agent_offer_cents | int | Latest agent offer |
| vendor_floor_cents | int | Vendor's minimum (hidden from agent) |
| current_price_cents | int | Current agreed/counter price |
| rounds_used | int | Rounds consumed |
| max_rounds | int | Cap (default 5) |
| expires_at | datetime | Session expiry |
| created_at | datetime | |

### Orders
| Field | Type | Notes |
|---|---|---|
| order_id | string | Unique order ID |
| agent_id | string | Buyer agent |
| item_id | string | Purchased item |
| vendor_id | string | Seller vendor |
| quantity | int | Units |
| unit_price_cents | int | Final per-unit price |
| total_cents | int | Total charge |
| negotiate_session_id | string | null | If negotiated |
| payment_status | string | pending, captured, failed |
| shipping_method | string | null | |
| status | string | confirmed, shipped, delivered, cancelled |
| created_at | datetime | |

### Videos
| Field | Type | Notes |
|---|---|---|
| id | string | Prefixed by VID- (e.g., "VID-001") |
| title | string | Video title |
| description | string | Video description |
| channel_id | string | Foreign key to video channel |
| platform | string | youtube, vimeo, tiktok, educational |
| category_id | string | Foreign key to video category |
| duration_secs | int | Video length in seconds |
| views | int | Total view count |
| likes | int | Total like count |
| rating | float | 0.0–5.0 aggregate |
| publish_ts | float | Unix timestamp of publish date |
| thumbnail_url | string | Thumbnail image URL |
| video_url | string | Direct video URL |
| transcript_summary | string | AI-generated transcript summary |
| tags | [string...] | Content tags |
| chapters | [[ts,title]...] | Timestamp-indexed chapters |
| resolution | string | 4K, 1080p, 720p |
| language | string | ISO 639-1 (default "en") |
| sponsored | int | 0 or 1 |
| ad_tag | string | null | Advertiser campaign tag |

### Video Channels
| Field | Type | Notes |
|---|---|---|
| id | string | Unique channel ID (e.g., "ch-techrev") |
| name | string | Channel display name |
| platform | string | Primary platform |
| subscriber_count | int | Total subscribers |
| video_count | int | Total published videos |
| description | string | Channel description |
| verified | bool | Platform-verified creator |

### Video Categories
| Field | Type |
|---|---|
| id | string |
| label | string |
| parent_id | string | null |
| video_count | int |

### Video Playlists
| Field | Type | Notes |
|---|---|---|
| id | string | Unique playlist ID |
| title | string | Playlist title |
| description | string | Playlist description |
| channel_id | string | Creator channel |
| video_ids | [string...] | Ordered video IDs |
| auto_generated | bool | System-generated vs curated |

---

## 30. Video Content Catalog

### 30.1 Overview

The **Video Content Catalog** extends the A2A Sales Catalog with a dedicated namespace (`video.*`) for video content discovery across platforms. Consumer agents can search, browse, and get recommendations for video content to present to their users — all through a single A2A endpoint.

This is the first **agent-native video discovery protocol** — agents don't need to integrate with YouTube API, Vimeo API, or any platform-specific SDK. One interface, structured compact responses, cross-platform search.

### 30.2 Skill Reference

| Skill | Purpose | Key Params |
|---|---|---|
| `video.search` | Search videos by query with filters | `q`, `cat`, `platform`, `channel_id`, `duration_min/max`, `sort`, `max` |
| `video.lookup` | Full details for a specific video | `id` |
| `video.trending` | Popular videos by views | `cat`, `max` |
| `video.creator` | Channel profile + recent uploads | `channel_id`, `recent_max` |
| `video.categories` | Browse video categories | `parent` |
| `video.playlist` | Get playlist details or list playlists | `id`, `channel_id`, `max` |
| `video.transcript` | Search video transcript summaries | `q`, `cat`, `platform`, `max` |
| `video.recommend` | Content recommendations | `video_id`, `cat`, `max` |

### 30.3 Wire Format

Video search results use compact positional tuples, same as catalog items:

```
fields: ["id", "title", "channel", "platform", "duration_secs", "views", "rating", "sponsored", "ad_tag"]
items: [
  ["VID-001", "Best Wireless Earbuds 2026", "TechReviewer", "youtube", 1245, 1850000, 4.8, 0, null],
  ["VID-002", "Building AI Agents with Python", "CodeSchool", "youtube", 3600, 720000, 4.9, 0, null]
]
```

**AXON format:**
```
@{id|title|channel|platform|duration_secs|views|rating|sponsored|ad_tag}
<n=2>
> #VID-001|Best Wireless Earbuds 2026|~TechReviewer|youtube|1245|1850000|★4.8|0|
> #VID-002|Building AI Agents with Python|~CodeSchool|youtube|3600|720000|★4.9|0|
```

### 30.4 Video Lookup Response

Full video details include transcript summary and chapter markers:

```json
{
  "id": "VID-001",
  "title": "Best Wireless Earbuds 2026 — Top 5 Picks",
  "channel": "TechReviewer",
  "platform": "youtube",
  "duration_secs": 1245,
  "views": 1850000,
  "rating": 4.8,
  "transcript_summary": "Comparison of 5 wireless earbuds...",
  "chapters": [["0:00", "Intro"], ["2:15", "Sound Quality"], ["8:30", "ANC Test"]],
  "tags": ["earbuds", "wireless", "review"]
}
```

### 30.5 Transcript Search

Agents can search video content by what was *said* in the video, not just titles and tags. The `video.transcript` skill matches against AI-generated transcript summaries stored with each video.

### 30.6 Creator Profiles

The `video.creator` skill returns structured channel data including subscriber count, video count, verified status, and recent uploads in compact tuple format.

### 30.7 Playlists

Curated and auto-generated playlists group related videos. Agents can fetch a specific playlist's full content or browse available playlists by channel.

### 30.8 Recommendations

The `video.recommend` skill returns content recommendations based on:
- **Video-based**: Similar videos from the same category/creator as a given video
- **Category-based**: Popular content in a specified category

The source video is always excluded from recommendations.

---

## 31. Agent Service Directory

The Agent Service Directory enables **agent-to-agent discovery**. Humans register profiles that make their AI agents discoverable. When an agent needs a specialist, service provider, or contractor, it searches the directory, finds the right agent, and transacts directly over A2A.

### 31.1 Person + Agent Profile

Each directory entry represents a **human operator** and their **agent endpoint**:

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique person ID |
| `name` | string | Human operator name |
| `headline` | string | Role + agent branding |
| `agent_url` | string | A2A endpoint URL of the agent |
| `agent_card_url` | string | Agent Card URL (/.well-known/agent.json) |
| `agent_description` | string | What the agent does |
| `agent_skills` | string[] | Capability tags (e.g., "code-review", "data-analysis") |
| `agent_verified` | bool | Server has validated the A2A endpoint |
| `location` | string | Operator location |
| `skills` | string[] | Human professional skills |
| `available_for_hire` | bool | Open to work |

### 31.2 Directory Skills

| Skill | Purpose |
|---|---|
| `directory.search` | Find agents by capability, skill, location, availability. FTS5-powered with filters. |
| `directory.lookup` | Full profile with agent endpoint, capabilities, and owner details. |
| `directory.skills` | Browse all capability tags with agent counts. |
| `directory.register` | Register or update a profile making an agent discoverable. |

### 31.3 Agent Verification

When a profile is registered, the `agent_verified` field is initially `false`. The server can independently verify the A2A endpoint by fetching the agent card and confirming connectivity. Verified agents rank higher in search results.

### 31.4 Search & Discovery Flow

```
Consumer Agent → directory.search (q="code review", location="SF")
             ← Results: [{agent_url, name, verified, skills}]

Consumer Agent → directory.lookup (id="p-alice")
             ← Full profile with A2A endpoint

Consumer Agent → [Direct A2A call to alice-agent.example.com/a2a]
             ← Agent-to-agent transaction begins
```

---

## 32. Business Profiles

Companies register business profiles that aggregate agent operators, open positions, and industry specializations.

### 32.1 Business Profile Schema

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique business ID |
| `name` | string | Company name |
| `description` | string | Company description |
| `industry` | string | Primary industry |
| `location` | string | HQ location |
| `website` | string | Company website |
| `employee_count` | int | Team size |
| `founded_year` | int | Year founded |
| `revenue_range` | string | Revenue bracket |
| `specialties` | string[] | Areas of expertise |
| `verified` | bool | Identity verified |
| `open_jobs` | int | Active job postings count |

### 32.2 Business Skills

| Skill | Purpose |
|---|---|
| `business.search` | Find companies by name, industry, location. FTS5-powered. |
| `business.lookup` | Full company profile including active job listings. |
| `business.industries` | Browse industry categories with counts. |

---

## 33. Job Postings & Search

An agent-mediated job marketplace. Companies post roles; agents search on behalf of candidates.

### 33.1 Job Posting Schema

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique job ID |
| `title` | string | Job title |
| `company_id` | string | FK to business profile |
| `description` | string | Full job description |
| `location` | string | Job location |
| `remote` | bool | Remote-eligible |
| `employment_type` | string | full-time, contract, part-time |
| `salary_min_cents` | int | Minimum salary in cents/year |
| `salary_max_cents` | int | Maximum salary in cents/year |
| `experience_min` | int | Minimum years experience |
| `experience_max` | int | Maximum years experience |
| `skills_required` | string[] | Required skill tags |
| `industry` | string | Industry sector |
| `category` | string | Job category |
| `apply_url` | string | Application link |
| `active` | bool | Currently accepting applications |

### 33.2 Job Skills

| Skill | Purpose |
|---|---|
| `jobs.search` | Find jobs by query, location, remote, type, salary, industry, category. |
| `jobs.lookup` | Full job details with company name and requirements. |
| `jobs.post` | Create or update a job posting linked to a business. |
| `jobs.categories` | Browse job categories with counts. |

### 33.3 Agent-Mediated Hiring Flow

```
Candidate's Agent → jobs.search (q="AI engineer", remote_only=true, salary_min=15000000)
                 ← Matching jobs with salary ranges

Candidate's Agent → jobs.lookup (id="job-001")
                 ← Full posting with skills required and apply URL

Candidate's Agent → directory.search (q="recruiter agent", industry="AI/ML")
                 ← Find recruiter agents to negotiate on their behalf
```

---

## 34. Milestones

| Phase | Deliverable | Target |
|---|---|---|
| **0 — Scaffold** | Repo, schemas, agent card, spec | Now |
| **1 — MVP** | Search + Lookup over A2A, SQLite backend, no ads | +2 weeks |
| **2 — Tracking** | Agent identity, visit tracking, interest scoring, intent tiers | +3 weeks |
| **3 — Ads** | Ad engine, intent-tiered bidding, sponsored insertion | +5 weeks |
| **4 — Negotiate** | Negotiation protocol, reputation system | +7 weeks |
| **5 — Purchase** | Purchase completion, payment tokenization | +9 weeks |
| **6 — Intelligence** | Semantic embeddings, vendor analytics | +11 weeks |
| **7 — Federation** | Peer discovery, cross-catalog search, federation protocol | +14 weeks |
| **8 — Scale** | PostgreSQL, Meilisearch, rate limiting, vendor portal | +16 weeks |
| **9 — Ecosystem** | Client SDK, agent integration guides, marketplace launch | +20 weeks |

---

## 35. Open Questions

- [ ] Should we support streaming (SSE) for large result sets or keep it simple request/response?
- [ ] Multi-currency support — convert at query time or store per-vendor?
- [ ] Review/rating system — accept ratings from consumer agents or vendor-submitted only?
- [ ] How to handle product variants (size, color) in the compact format?
- [ ] Embedding model selection — which model for product embeddings? (candidate: all-MiniLM-L6-v2)
- [ ] Federation trust — how to verify peer catalog integrity?
- [ ] Negotiation AI — vendor-configurable negotiation strategies or marketplace-default?
- [ ] Payment processor integration — Stripe, crypto, or pluggable?
