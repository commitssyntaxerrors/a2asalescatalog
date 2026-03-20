# A2A Sales Catalog

An **agent-to-agent marketplace** that lets AI agent orchestrators query structured product and service data over the [A2A protocol](https://github.com/google/A2A) — no web scraping required.

Businesses pay for ad placement. Consumer agents get real, structured results. Everyone wins.

---

## Why This Exists

AI agents today have no clean way to shop. They scrape HTML, fight CAPTCHAs, and parse inconsistent formats. The A2A Sales Catalog gives agents a **single endpoint** that returns compact, machine-optimized product data they can reason over immediately.

**For consumer agents:** One query → structured results with prices, ratings, attributes.
**For businesses:** A new distribution channel — reach millions of AI agents directly.
**Revenue model:** Ad-supported. Sponsored results are always marked; organic results are never hidden.

---

## Architecture

```
Consumer Agent ──A2A/JSON-RPC──► Catalog Server ──► Search Index (SQLite FTS5)
                                       │
                                       ├──► Ad Engine (sponsored insertion)
                                       └──► Rate Limiter + Auth
```

## Wire Format — Compact Tuples

Responses use **positional arrays** instead of repeated key-value objects. A `fields` header defines the schema once, then each item is a tuple. ~60% smaller than equivalent named-key JSON.

```json
{
  "fields": ["id","name","desc","price_cents","vendor","rating","sponsored","ad_tag"],
  "items": [
    ["WE-001","SoundPod Pro","wireless earbuds, ANC, 30h battery",4999,"soundpod.com",4.6,1,"sp"],
    ["WE-002","BassX Buds","wireless earbuds, deep bass, IPX5",3499,"bassx.io",4.3,0,null]
  ],
  "currency": "USD",
  "total": 2
}
```

---

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Run the server (auto-seeds demo data)
uvicorn src.server.app:app --host 0.0.0.0 --port 8000

# Test with curl
curl -X POST http://localhost:8000/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"tasks/send",
    "params":{"id":"t1","message":{"role":"user","parts":[
      {"type":"data","data":{"skill":"catalog.search","q":"earbuds","max":3}}
    ]}}
  }'

# Or run the example client
python -m examples.consumer_agent
```

---

## Skills (API)

| Skill | Description |
|---|---|
| `catalog.search` | Full-text search with filters (category, price, vendor, sort) |
| `catalog.lookup` | Get full details for a single item by ID |
| `catalog.categories` | Browse product/service categories |
| `catalog.compare` | Side-by-side comparison of multiple items |
| `catalog.negotiate` | Multi-round price negotiation (reputation ≥ 40 required) |
| `catalog.purchase` | Complete a purchase with tokenized payment |
| `catalog.agent_profile` | View agent profile, interest scores, intent tier |
| `catalog.reputation` | Get agent reputation breakdown and trust tier |
| `catalog.embed` | Semantic embedding vectors for items/queries |
| `catalog.peers` | List federated catalog peers |
| `catalog.vendor_analytics` | Agent behavior analytics for vendors |

### Agent Card

The server publishes an A2A Agent Card at `GET /.well-known/agent.json` — this is how consumer agents discover the catalog's capabilities.

---

## Project Structure

```
a2asalescatalog/
├── docs/
│   └── SPEC.md                # Full specification sheet
├── schemas/
│   ├── agent-card.json        # A2A Agent Card definition
│   ├── search-request.json    # JSON Schema for search input
│   ├── search-response.json   # JSON Schema for search output
│   ├── lookup-request.json    # JSON Schema for lookup input
│   ├── categories-request.json
│   └── compare-request.json
├── src/
│   ├── common/
│   │   └── models.py            # Shared data models & tuple encoders
│   ├── server/
│   │   ├── app.py               # Starlette A2A server
│   │   ├── store.py             # SQLite FTS5 data store
│   │   ├── skills.py            # Skill handlers (11 skills)
│   │   ├── ads.py               # Ad engine — intent-tiered bidding
│   │   ├── agent_tracker.py     # Agent tracking & interest scoring
│   │   ├── negotiation.py       # Programmatic price negotiation
│   │   ├── purchase.py          # Purchase completion protocol
│   │   ├── federation.py        # Federated catalog network
│   │   ├── embeddings.py        # Semantic embeddings index
│   │   └── vendor_analytics.py  # Vendor-facing analytics
│   └── client/
│       └── catalog_client.py    # Consumer agent SDK
├── examples/
│   └── consumer_agent.py      # Example agent integration
├── tests/
├── pyproject.toml
└── README.md
```

---

## Advertising Model

1. Vendors list products for **free** (organic listings)
2. Advertisers **bid on keywords** for promoted placement
3. Sponsored items are **always marked** (`"sponsored": 1`)
4. Cap: max 20% of results can be sponsored
5. Agents can opt out of ads on the **Pro tier** ($49/mo)

---

## Auth & Rate Limits

| Tier | Rate Limit | Ads | Cost |
|---|---|---|---|
| Free | 100 req/min | Included | $0 |
| Pro | 1,000 req/min | Opt-out | $49/mo |
| Enterprise | Unlimited | Opt-out + SLA | Custom |

Set `CATALOG_API_KEYS=key1,key2` to enable API key auth. Without it, the server runs in open dev mode.

---

## Roadmap

See [docs/SPEC.md](docs/SPEC.md) for the full specification including milestones, data model, security considerations, and open questions.

---

## License

> **Copyright © 2026 A2A Sales Catalog Authors. All Rights Reserved.**
>
> **PROPRIETARY SOFTWARE — NOT OPEN SOURCE.**
>
> No license is granted to use, copy, modify, or distribute this software.
> The source code is publicly visible solely to establish prior art and
> timestamp intellectual property. See [LICENSE](LICENSE) for full terms.
>
> For licensing inquiries, contact the copyright holder(s).
