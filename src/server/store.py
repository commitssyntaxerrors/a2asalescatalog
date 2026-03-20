# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""A2A Sales Catalog — in-memory store for MVP phase.

Uses SQLite FTS5 for full-text search. Upgradeable to PostgreSQL + Meilisearch.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from src.common.models import (
    AdCampaign, AgentEvent, AgentInterest, AgentProfile,
    CatalogItem, Category, NegotiationSession, Order, Vendor,
    classify_intent,
)

_DEFAULT_DB = ":memory:"


class CatalogStore:
    """Thin wrapper around SQLite for catalog data with FTS5 search."""

    def __init__(self, db_path: str = _DEFAULT_DB) -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._bootstrap()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _bootstrap(self) -> None:
        c = self._conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS vendors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                domain TEXT NOT NULL,
                verified INTEGER DEFAULT 0,
                tier TEXT DEFAULT 'free'
            );

            CREATE TABLE IF NOT EXISTS categories (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                parent_id TEXT,
                item_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                desc TEXT NOT NULL,
                price_cents INTEGER NOT NULL,
                currency TEXT DEFAULT 'USD',
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                category_id TEXT NOT NULL REFERENCES categories(id),
                rating REAL DEFAULT 0.0,
                review_count INTEGER DEFAULT 0,
                attrs TEXT DEFAULT '[]',
                buy_url TEXT DEFAULT '',
                images TEXT DEFAULT '[]',
                sponsored INTEGER DEFAULT 0,
                ad_tag TEXT,
                active INTEGER DEFAULT 1,
                vendor_floor_cents INTEGER,
                trusted_price_cents INTEGER,
                reputation_threshold INTEGER DEFAULT 0,
                embedding TEXT DEFAULT '',
                created_at REAL,
                updated_at REAL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                id, name, desc, content=items, content_rowid=rowid
            );

            CREATE TABLE IF NOT EXISTS ad_campaigns (
                id TEXT PRIMARY KEY,
                vendor_id TEXT NOT NULL REFERENCES vendors(id),
                keywords TEXT DEFAULT '[]',
                categories TEXT DEFAULT '[]',
                bid_cents INTEGER DEFAULT 0,
                bid_cents_browse INTEGER DEFAULT 0,
                bid_cents_consider INTEGER DEFAULT 0,
                bid_cents_high_intent INTEGER DEFAULT 0,
                bid_cents_ready_to_buy INTEGER DEFAULT 0,
                budget_cents INTEGER DEFAULT 0,
                spent_cents INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                ad_tag TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS agent_profiles (
                agent_id TEXT PRIMARY KEY,
                reputation REAL DEFAULT 50.0,
                total_queries INTEGER DEFAULT 0,
                total_purchases INTEGER DEFAULT 0,
                created_at REAL,
                last_seen_at REAL
            );

            CREATE TABLE IF NOT EXISTS agent_events (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                item_id TEXT,
                query TEXT,
                category TEXT,
                metadata TEXT DEFAULT '{}',
                timestamp REAL
            );
            CREATE INDEX IF NOT EXISTS idx_events_agent ON agent_events(agent_id);
            CREATE INDEX IF NOT EXISTS idx_events_item ON agent_events(item_id);

            CREATE TABLE IF NOT EXISTS agent_interests (
                agent_id TEXT NOT NULL,
                item_id TEXT,
                category TEXT,
                score REAL DEFAULT 0.0,
                intent_tier TEXT DEFAULT 'browse',
                visit_count INTEGER DEFAULT 0,
                last_event_at REAL,
                PRIMARY KEY (agent_id, item_id, category)
            );

            CREATE TABLE IF NOT EXISTS negotiation_sessions (
                session_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                agent_offer_cents INTEGER DEFAULT 0,
                vendor_floor_cents INTEGER DEFAULT 0,
                current_price_cents INTEGER DEFAULT 0,
                rounds_used INTEGER DEFAULT 0,
                max_rounds INTEGER DEFAULT 5,
                expires_at REAL,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                vendor_id TEXT NOT NULL,
                quantity INTEGER DEFAULT 1,
                unit_price_cents INTEGER DEFAULT 0,
                total_cents INTEGER DEFAULT 0,
                negotiate_session_id TEXT,
                payment_status TEXT DEFAULT 'pending',
                shipping_method TEXT,
                status TEXT DEFAULT 'confirmed',
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS federation_peers (
                url TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                categories TEXT DEFAULT '[]',
                items_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'online',
                last_seen_at REAL
            );
        """)
        c.commit()

    # ------------------------------------------------------------------
    # Write ops
    # ------------------------------------------------------------------

    def upsert_vendor(self, v: Vendor) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO vendors (id, name, domain, verified, tier) VALUES (?,?,?,?,?)",
            (v.id, v.name, v.domain, int(v.verified), v.tier),
        )
        self._conn.commit()

    def upsert_category(self, cat: Category) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO categories (id, label, parent_id, item_count) VALUES (?,?,?,?)",
            (cat.id, cat.label, cat.parent_id, cat.item_count),
        )
        self._conn.commit()

    def upsert_item(self, item: CatalogItem) -> None:
        import json
        self._conn.execute(
            """INSERT OR REPLACE INTO items
               (id, name, desc, price_cents, currency, vendor_id, category_id,
                rating, review_count, attrs, buy_url, images, sponsored, ad_tag,
                active, vendor_floor_cents, trusted_price_cents,
                reputation_threshold, embedding, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item.id, item.name, item.desc, item.price_cents, item.currency,
                item.vendor_id, item.category_id, item.rating, item.review_count,
                json.dumps(item.attrs), item.buy_url, json.dumps(item.images),
                item.sponsored, item.ad_tag, int(item.active),
                item.vendor_floor_cents, item.trusted_price_cents,
                item.reputation_threshold, item.embedding,
                item.created_at, item.updated_at,
            ),
        )
        # Update FTS index
        self._conn.execute(
            "INSERT OR REPLACE INTO items_fts (rowid, id, name, desc) "
            "SELECT rowid, id, name, desc FROM items WHERE id = ?",
            (item.id,),
        )
        self._conn.commit()

    def upsert_campaign(self, camp: AdCampaign) -> None:
        import json
        self._conn.execute(
            """INSERT OR REPLACE INTO ad_campaigns
               (id, vendor_id, keywords, categories, bid_cents,
                bid_cents_browse, bid_cents_consider, bid_cents_high_intent,
                bid_cents_ready_to_buy, budget_cents, spent_cents, active, ad_tag)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                camp.id, camp.vendor_id, json.dumps(camp.keywords),
                json.dumps(camp.categories), camp.bid_cents,
                camp.bid_cents_browse, camp.bid_cents_consider,
                camp.bid_cents_high_intent, camp.bid_cents_ready_to_buy,
                camp.budget_cents, camp.spent_cents, int(camp.active), camp.ad_tag,
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read ops
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        category: str | None = None,
        vendor: str | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        sort: str = "relevance",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Full-text search with optional filters. Returns dicts."""
        # Build WHERE clauses
        conditions = ["i.active = 1"]
        params: list[Any] = []

        if category:
            conditions.append("i.category_id = ?")
            params.append(category)
        if vendor:
            conditions.append("v.domain = ?")
            params.append(vendor)
        if price_min is not None:
            conditions.append("i.price_cents >= ?")
            params.append(price_min)
        if price_max is not None:
            conditions.append("i.price_cents <= ?")
            params.append(price_max)

        where = " AND ".join(conditions)

        # FTS match
        if query.strip():
            fts_clause = "i.rowid IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)"
            conditions_with_fts = f"{where} AND {fts_clause}"
            params_with_fts = params + [query]
        else:
            conditions_with_fts = where
            params_with_fts = params

        order = {
            "price_asc": "i.price_cents ASC",
            "price_desc": "i.price_cents DESC",
            "rating": "i.rating DESC",
        }.get(sort, "i.sponsored DESC, i.rating DESC")

        sql = f"""
            SELECT i.*, v.domain as vendor_domain
            FROM items i
            JOIN vendors v ON i.vendor_id = v.id
            WHERE {conditions_with_fts}
            ORDER BY {order}
            LIMIT ?
        """
        params_with_fts.append(limit)

        rows = self._conn.execute(sql, params_with_fts).fetchall()
        return [dict(r) for r in rows]

    def lookup(self, item_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT i.*, v.domain as vendor_domain FROM items i "
            "JOIN vendors v ON i.vendor_id = v.id WHERE i.id = ?",
            (item_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_categories(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        if parent_id is None:
            rows = self._conn.execute(
                "SELECT * FROM categories WHERE parent_id IS NULL ORDER BY label"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM categories WHERE parent_id = ? ORDER BY label",
                (parent_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_items_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT i.*, v.domain as vendor_domain FROM items i "
            f"JOIN vendors v ON i.vendor_id = v.id "
            f"WHERE i.id IN ({placeholders}) AND i.active = 1",
            ids,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_matching_campaigns(self, query: str, category: str | None = None) -> list[dict[str, Any]]:
        """Find active ad campaigns that match the query keywords or category."""
        rows = self._conn.execute(
            "SELECT * FROM ad_campaigns WHERE active = 1"
        ).fetchall()
        results = []
        import json
        q_lower = query.lower()
        for r in rows:
            row = dict(r)
            kws = json.loads(row["keywords"])
            cats = json.loads(row["categories"])
            if any(kw.lower() in q_lower for kw in kws):
                results.append(row)
            elif category and category in cats:
                results.append(row)
        results.sort(key=lambda x: x["bid_cents"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Agent profiles
    # ------------------------------------------------------------------

    def get_or_create_agent(self, agent_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM agent_profiles WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row:
            return dict(row)
        import time as _t
        now = _t.time()
        self._conn.execute(
            "INSERT INTO agent_profiles (agent_id, reputation, total_queries, total_purchases, created_at, last_seen_at) "
            "VALUES (?,50.0,0,0,?,?)", (agent_id, now, now),
        )
        self._conn.commit()
        return {"agent_id": agent_id, "reputation": 50.0, "total_queries": 0,
                "total_purchases": 0, "created_at": now, "last_seen_at": now}

    def update_agent_stats(self, agent_id: str, *, queries: int = 0, purchases: int = 0) -> None:
        import time as _t
        self._conn.execute(
            "UPDATE agent_profiles SET total_queries = total_queries + ?, "
            "total_purchases = total_purchases + ?, last_seen_at = ? WHERE agent_id = ?",
            (queries, purchases, _t.time(), agent_id),
        )
        self._conn.commit()

    def update_agent_reputation(self, agent_id: str, delta: float) -> None:
        self._conn.execute(
            "UPDATE agent_profiles SET reputation = MIN(100, MAX(0, reputation + ?)) WHERE agent_id = ?",
            (delta, agent_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Agent events
    # ------------------------------------------------------------------

    def log_event(self, event: AgentEvent) -> None:
        self._conn.execute(
            "INSERT INTO agent_events (id, agent_id, event_type, item_id, query, category, metadata, timestamp) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (event.id, event.agent_id, event.event_type, event.item_id,
             event.query, event.category, event.metadata, event.timestamp),
        )
        self._conn.commit()

    def get_agent_events(self, agent_id: str, *, event_type: str | None = None,
                         item_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        conditions = ["agent_id = ?"]
        params: list[Any] = [agent_id]
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if item_id:
            conditions.append("item_id = ?")
            params.append(item_id)
        where = " AND ".join(conditions)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM agent_events WHERE {where} ORDER BY timestamp DESC LIMIT ?", params
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Agent interests
    # ------------------------------------------------------------------

    def upsert_interest(self, interest: AgentInterest) -> None:
        item_key = interest.item_id or ""
        cat_key = interest.category or ""
        self._conn.execute(
            """INSERT INTO agent_interests (agent_id, item_id, category, score, intent_tier, visit_count, last_event_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(agent_id, item_id, category) DO UPDATE SET
                 score = excluded.score,
                 intent_tier = excluded.intent_tier,
                 visit_count = excluded.visit_count,
                 last_event_at = excluded.last_event_at""",
            (interest.agent_id, item_key, cat_key, interest.score,
             interest.intent_tier, interest.visit_count, interest.last_event_at),
        )
        self._conn.commit()

    def get_interests(self, agent_id: str, *, top_n: int = 10) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM agent_interests WHERE agent_id = ? ORDER BY score DESC LIMIT ?",
            (agent_id, top_n),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_interest(self, agent_id: str, item_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM agent_interests WHERE agent_id = ? AND item_id = ?",
            (agent_id, item_id),
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Negotiation sessions
    # ------------------------------------------------------------------

    def create_negotiation(self, session: NegotiationSession) -> None:
        self._conn.execute(
            """INSERT INTO negotiation_sessions
               (session_id, agent_id, item_id, status, agent_offer_cents,
                vendor_floor_cents, current_price_cents, rounds_used, max_rounds,
                expires_at, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (session.session_id, session.agent_id, session.item_id, session.status,
             session.agent_offer_cents, session.vendor_floor_cents,
             session.current_price_cents, session.rounds_used, session.max_rounds,
             session.expires_at, session.created_at),
        )
        self._conn.commit()

    def get_negotiation(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM negotiation_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_negotiation(self, session_id: str, **kwargs: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [session_id]
        self._conn.execute(
            f"UPDATE negotiation_sessions SET {sets} WHERE session_id = ?", vals
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def create_order(self, order: Order) -> None:
        self._conn.execute(
            """INSERT INTO orders
               (order_id, agent_id, item_id, vendor_id, quantity, unit_price_cents,
                total_cents, negotiate_session_id, payment_status, shipping_method,
                status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order.order_id, order.agent_id, order.item_id, order.vendor_id,
             order.quantity, order.unit_price_cents, order.total_cents,
             order.negotiate_session_id, order.payment_status, order.shipping_method,
             order.status, order.created_at),
        )
        self._conn.commit()

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_vendor_orders(self, vendor_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE vendor_id = ? ORDER BY created_at DESC LIMIT ?",
            (vendor_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Federation peers
    # ------------------------------------------------------------------

    def upsert_peer(self, url: str, name: str, categories: list[str],
                    items_count: int = 0) -> None:
        import json, time as _t
        self._conn.execute(
            """INSERT OR REPLACE INTO federation_peers
               (url, name, categories, items_count, status, last_seen_at)
               VALUES (?,?,?,?,?,?)""",
            (url, name, json.dumps(categories), items_count, "online", _t.time()),
        )
        self._conn.commit()

    def list_peers(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM federation_peers").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Vendor analytics queries
    # ------------------------------------------------------------------

    def vendor_event_summary(self, vendor_id: str, since: float) -> dict[str, Any]:
        """Aggregate agent event stats for a vendor's items since timestamp."""
        items = self._conn.execute(
            "SELECT id FROM items WHERE vendor_id = ?", (vendor_id,)
        ).fetchall()
        item_ids = [r["id"] for r in items]
        if not item_ids:
            return {"impressions": 0, "unique_agents": 0, "lookups": 0,
                    "compares": 0, "negotiations": 0, "purchases": 0}
        ph = ",".join("?" for _ in item_ids)
        row = self._conn.execute(
            f"""SELECT
                COUNT(*) as impressions,
                COUNT(DISTINCT agent_id) as unique_agents,
                SUM(CASE WHEN event_type='lookup' THEN 1 ELSE 0 END) as lookups,
                SUM(CASE WHEN event_type='compare' THEN 1 ELSE 0 END) as compares,
                SUM(CASE WHEN event_type='negotiate' THEN 1 ELSE 0 END) as negotiations,
                SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) as purchases
              FROM agent_events
              WHERE item_id IN ({ph}) AND timestamp >= ?""",
            item_ids + [since],
        ).fetchone()
        return dict(row) if row else {}

    def vendor_top_queries(self, vendor_id: str, since: float, limit: int = 10) -> list[tuple[str, int]]:
        items = self._conn.execute(
            "SELECT id FROM items WHERE vendor_id = ?", (vendor_id,)
        ).fetchall()
        item_ids = [r["id"] for r in items]
        if not item_ids:
            return []
        # Get searches that led to lookups on these items
        ph = ",".join("?" for _ in item_ids)
        rows = self._conn.execute(
            f"""SELECT query, COUNT(*) as cnt FROM agent_events
                WHERE event_type='search' AND category IN (
                    SELECT category_id FROM items WHERE id IN ({ph})
                ) AND timestamp >= ?
                GROUP BY query ORDER BY cnt DESC LIMIT ?""",
            item_ids + [since, limit],
        ).fetchall()
        return [(r["query"], r["cnt"]) for r in rows if r["query"]]

    def vendor_intent_breakdown(self, vendor_id: str) -> dict[str, int]:
        items = self._conn.execute(
            "SELECT id FROM items WHERE vendor_id = ?", (vendor_id,)
        ).fetchall()
        item_ids = [r["id"] for r in items]
        if not item_ids:
            return {"browse": 0, "consider": 0, "high_intent": 0, "ready_to_buy": 0}
        ph = ",".join("?" for _ in item_ids)
        rows = self._conn.execute(
            f"SELECT intent_tier, COUNT(*) as cnt FROM agent_interests WHERE item_id IN ({ph}) GROUP BY intent_tier",
            item_ids,
        ).fetchall()
        result = {"browse": 0, "consider": 0, "high_intent": 0, "ready_to_buy": 0}
        for r in rows:
            result[r["intent_tier"]] = r["cnt"]
        return result
