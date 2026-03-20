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

## 6. Advertising Model

### 6.1 How It Works

1. **Vendors register** and list products for free (organic listings).
2. **Advertisers bid** on keywords/categories for promoted placement.
3. When a consumer agent searches, the catalog:
   - Retrieves organic results ranked by relevance/rating
   - Inserts sponsored results based on bid rank and relevance
   - Marks every sponsored result with `sponsored: 1`
4. Advertisers are charged **per-impression** (result served) or **per-action** (buy_url clicked).

### 6.2 Trust Contract

- Sponsored results are **always marked** — agents that strip or hide the flag violate ToS.
- Organic results are **never suppressed** — sponsored items supplement, not replace.
- The ratio of sponsored to organic is capped (default: max 2 sponsored per 10 results).
- Agents may request `sponsored: 0` to exclude all ads (premium tier).

### 6.3 Revenue Tiers

| Tier | Cost | Sponsored | Rate Limit |
|---|---|---|---|
| Free | $0 | Included (max 20%) | 100 req/min |
| Pro | $49/mo | Opt-out available | 1,000 req/min |
| Enterprise | Custom | Opt-out, SLA, dedicated | Unlimited |

---

## 7. Architecture Overview

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

### 7.1 Components

| Component | Tech | Purpose |
|---|---|---|
| **A2A Server** | Python (FastAPI / Starlette) | Handles A2A protocol, routes skills |
| **Search Index** | SQLite FTS5 → Meilisearch | Full-text + faceted product search |
| **Ad Engine** | In-process module | Keyword bidding, insertion, attribution |
| **Auth & Rate Limit** | API key + token bucket | Tiered access control |
| **Vendor Portal** | Separate web app (future) | Product upload, ad campaign management |
| **Data Store** | PostgreSQL | Canonical product + vendor + ad data |

---

## 8. Security & Trust

| Concern | Mitigation |
|---|---|
| Prompt injection via product descriptions | Sanitize all vendor text; strip control chars |
| Agent impersonation | API key auth + optional mTLS |
| Ad fraud (fake impressions) | Rate limiting, agent fingerprinting, anomaly detection |
| Data poisoning by vendors | Review pipeline, flagging system |
| Denial of service | Token bucket rate limiter, max response size |

---

## 9. Data Model (Core Entities)

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
| budget_cents | int |
| spent_cents | int |
| active | bool |
| ad_tag | string |

---

## 10. Milestones

| Phase | Deliverable | Target |
|---|---|---|
| **0 — Scaffold** | Repo, schemas, agent card, spec | Now |
| **1 — MVP** | Search + Lookup over A2A, SQLite backend, no ads | +2 weeks |
| **2 — Ads** | Ad engine, sponsored insertion, attribution tracking | +4 weeks |
| **3 — Scale** | PostgreSQL, Meilisearch, rate limiting, vendor portal | +8 weeks |
| **4 — Ecosystem** | Client SDK, agent integration guides, marketplace launch | +12 weeks |

---

## 11. Open Questions

- [ ] Should we support streaming (SSE) for large result sets or keep it simple request/response?
- [ ] Multi-currency support — convert at query time or store per-vendor?
- [ ] Review/rating system — accept ratings from consumer agents or vendor-submitted only?
- [ ] How to handle product variants (size, color) in the compact format?
- [ ] Federation — can multiple catalog servers interoperate?
