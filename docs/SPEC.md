# A2A Sales Catalog — Specification Sheet

**Version:** 0.1.0-draft
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

## 5. API Skills (Endpoints)

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

## 6. Agent Identity, Tracking & Interest Scoring

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

## 7. Agent Reputation & Trust Scores

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

## 8. Negotiation Protocol

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

## 9. Purchase Completion Protocol

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

## 10. Federated Catalog Network

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

## 11. Semantic Embeddings Index

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

## 12. Vendor Analytics

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

## 13. Advertising Model

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

## 14. Architecture Overview

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

### 14.1 Components

| Component | Tech | Purpose |
|---|---|---|
| **A2A Server** | Python (FastAPI / Starlette) | Handles A2A protocol, routes skills |
| **Search Index** | SQLite FTS5 → Meilisearch | Full-text + faceted product search |
| **Ad Engine** | In-process module | Keyword bidding, intent-tiered insertion, attribution |
| **Agent Tracker** | In-process module | Visit logging, interest scoring, intent classification |
| **Negotiation Engine** | In-process module | Offer/counter-offer, vendor floor pricing |
| **Purchase Handler** | In-process module | Order creation, payment token validation |
| **Federation Router** | In-process module | Peer discovery, cross-catalog fan-out |
| **Embedding Index** | NumPy / FAISS (future) | Semantic vectors for items and queries |
| **Vendor Analytics** | In-process module | Agent behavior analytics per vendor |
| **Auth & Rate Limit** | API key + token bucket | Tiered access control |
| **Vendor Portal** | Separate web app (future) | Product upload, ad campaign management |
| **Data Store** | PostgreSQL | Canonical product + vendor + ad data |

---

## 15. Security & Trust

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

## 16. Data Model (Core Entities)

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

---

## 17. Milestones

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

## 18. Open Questions

- [ ] Should we support streaming (SSE) for large result sets or keep it simple request/response?
- [ ] Multi-currency support — convert at query time or store per-vendor?
- [ ] Review/rating system — accept ratings from consumer agents or vendor-submitted only?
- [ ] How to handle product variants (size, color) in the compact format?
- [ ] Embedding model selection — which model for product embeddings? (candidate: all-MiniLM-L6-v2)
- [ ] Federation trust — how to verify peer catalog integrity?
- [ ] Negotiation AI — vendor-configurable negotiation strategies or marketplace-default?
- [ ] Payment processor integration — Stripe, crypto, or pluggable?
