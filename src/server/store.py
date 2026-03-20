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
    AdCampaign, AffiliateLink, AgentEvent, AgentInterest, AgentProfile,
    AgentPreferences, AgentSegment, AgentSegmentMembership, CatalogItem,
    Category, ConversionAttribution, CrossSellRule, FrequencyRecord,
    NegotiationSession, Order, Promotion, Subscription, TouchPoint, Vendor,
    VideoCategory, VideoChannel, VideoItem, VideoPlaylist,
    BusinessProfile, IndustryCategory, JobCategory, JobPosting,
    PersonProfile,
    AgentService, ServiceReview, ServiceCategory,
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

            CREATE TABLE IF NOT EXISTS affiliate_links (
                referral_code TEXT PRIMARY KEY,
                referring_agent_id TEXT NOT NULL,
                vendor_id TEXT NOT NULL,
                commission_bps INTEGER DEFAULT 500,
                total_referrals INTEGER DEFAULT 0,
                total_earned_cents INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_aff_agent ON affiliate_links(referring_agent_id);

            CREATE TABLE IF NOT EXISTS frequency_records (
                agent_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL,
                impressions INTEGER DEFAULT 0,
                window_start REAL,
                PRIMARY KEY (agent_id, campaign_id)
            );

            CREATE TABLE IF NOT EXISTS ab_test_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ab_group TEXT NOT NULL,
                variant TEXT NOT NULL,
                event_type TEXT NOT NULL,
                campaign_id TEXT,
                revenue_cents INTEGER DEFAULT 0,
                timestamp REAL
            );

            CREATE TABLE IF NOT EXISTS agent_segments (
                segment_id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                description TEXT DEFAULT '',
                criteria TEXT DEFAULT '{}',
                agent_count INTEGER DEFAULT 0,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS agent_segment_memberships (
                agent_id TEXT NOT NULL,
                segment_id TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                assigned_at REAL,
                PRIMARY KEY (agent_id, segment_id)
            );

            CREATE TABLE IF NOT EXISTS touchpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                campaign_id TEXT DEFAULT '',
                item_id TEXT DEFAULT '',
                timestamp REAL
            );
            CREATE INDEX IF NOT EXISTS idx_tp_agent ON touchpoints(agent_id);

            CREATE TABLE IF NOT EXISTS conversion_attributions (
                order_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                touchpoints INTEGER DEFAULT 0,
                first_touch_campaign TEXT DEFAULT '',
                last_touch_campaign TEXT DEFAULT '',
                attributed_revenue_cents INTEGER DEFAULT 0,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS promotions (
                promo_id TEXT PRIMARY KEY,
                vendor_id TEXT NOT NULL,
                item_id TEXT DEFAULT '',
                code TEXT DEFAULT '',
                discount_type TEXT DEFAULT 'percent',
                discount_value INTEGER DEFAULT 0,
                min_price_cents INTEGER DEFAULT 0,
                max_uses INTEGER DEFAULT 0,
                used_count INTEGER DEFAULT 0,
                starts_at REAL DEFAULT 0,
                expires_at REAL DEFAULT 0,
                active INTEGER DEFAULT 1,
                bundle_item_ids TEXT DEFAULT '[]',
                promo_type TEXT DEFAULT 'coupon'
            );
            CREATE INDEX IF NOT EXISTS idx_promo_vendor ON promotions(vendor_id);
            CREATE INDEX IF NOT EXISTS idx_promo_code ON promotions(code);

            CREATE TABLE IF NOT EXISTS cross_sell_rules (
                source_item_id TEXT NOT NULL,
                target_item_id TEXT NOT NULL,
                relation_type TEXT DEFAULT 'cross_sell',
                vendor_id TEXT DEFAULT '',
                bid_cents INTEGER DEFAULT 0,
                priority INTEGER DEFAULT 0,
                PRIMARY KEY (source_item_id, target_item_id)
            );

            -- Video catalog tables
            CREATE TABLE IF NOT EXISTS video_channels (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                subscriber_count INTEGER DEFAULT 0,
                video_count INTEGER DEFAULT 0,
                description TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                verified INTEGER DEFAULT 0,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS video_categories (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                parent_id TEXT,
                video_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                channel_id TEXT NOT NULL REFERENCES video_channels(id),
                platform TEXT NOT NULL,
                category_id TEXT NOT NULL REFERENCES video_categories(id),
                duration_secs INTEGER DEFAULT 0,
                views INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                rating REAL DEFAULT 0.0,
                publish_ts REAL DEFAULT 0,
                thumbnail_url TEXT DEFAULT '',
                video_url TEXT DEFAULT '',
                transcript_summary TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                chapters TEXT DEFAULT '[]',
                resolution TEXT DEFAULT '',
                language TEXT DEFAULT 'en',
                sponsored INTEGER DEFAULT 0,
                ad_tag TEXT,
                active INTEGER DEFAULT 1,
                embedding TEXT DEFAULT '',
                created_at REAL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
                id, title, description, transcript_summary,
                content=videos, content_rowid=rowid
            );

            CREATE TABLE IF NOT EXISTS video_playlists (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                channel_id TEXT DEFAULT '',
                video_ids TEXT DEFAULT '[]',
                auto_generated INTEGER DEFAULT 0,
                created_at REAL
            );

            -- Agent directory tables (humans with discoverable agents)
            CREATE TABLE IF NOT EXISTS people (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                headline TEXT NOT NULL,
                agent_url TEXT DEFAULT '',
                agent_card_url TEXT DEFAULT '',
                agent_description TEXT DEFAULT '',
                agent_skills TEXT DEFAULT '[]',
                agent_verified INTEGER DEFAULT 0,
                location TEXT DEFAULT '',
                skills TEXT DEFAULT '[]',
                experience_years INTEGER DEFAULT 0,
                current_company TEXT DEFAULT '',
                current_title TEXT DEFAULT '',
                industry TEXT DEFAULT '',
                bio TEXT DEFAULT '',
                email TEXT DEFAULT '',
                website TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                available_for_hire INTEGER DEFAULT 0,
                verified INTEGER DEFAULT 0,
                created_at REAL,
                updated_at REAL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS people_fts USING fts5(
                id, name, headline, bio, skills, agent_description, agent_skills,
                content=people, content_rowid=rowid
            );

            CREATE TABLE IF NOT EXISTS directory_skill_tags (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                agent_count INTEGER DEFAULT 0
            );

            -- Business directory tables
            CREATE TABLE IF NOT EXISTS businesses (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                industry TEXT NOT NULL,
                location TEXT DEFAULT '',
                website TEXT DEFAULT '',
                employee_count INTEGER DEFAULT 0,
                founded_year INTEGER DEFAULT 0,
                revenue_range TEXT DEFAULT '',
                logo_url TEXT DEFAULT '',
                verified INTEGER DEFAULT 0,
                open_jobs INTEGER DEFAULT 0,
                specialties TEXT DEFAULT '[]',
                created_at REAL,
                updated_at REAL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS businesses_fts USING fts5(
                id, name, description, specialties,
                content=businesses, content_rowid=rowid
            );

            CREATE TABLE IF NOT EXISTS industry_categories (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                parent_id TEXT,
                business_count INTEGER DEFAULT 0
            );

            -- Job postings tables
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company_id TEXT NOT NULL REFERENCES businesses(id),
                description TEXT NOT NULL,
                location TEXT DEFAULT '',
                remote INTEGER DEFAULT 0,
                employment_type TEXT DEFAULT 'full_time',
                salary_min_cents INTEGER DEFAULT 0,
                salary_max_cents INTEGER DEFAULT 0,
                salary_currency TEXT DEFAULT 'USD',
                experience_min INTEGER DEFAULT 0,
                experience_max INTEGER DEFAULT 0,
                skills_required TEXT DEFAULT '[]',
                industry TEXT DEFAULT '',
                category TEXT DEFAULT '',
                apply_url TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                posted_at REAL,
                expires_at REAL DEFAULT 0
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
                id, title, description, skills_required,
                content=jobs, content_rowid=rowid
            );

            CREATE TABLE IF NOT EXISTS job_categories (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                parent_id TEXT,
                job_count INTEGER DEFAULT 0
            );

            -- Agent services marketplace tables
            CREATE TABLE IF NOT EXISTS agent_services (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                agent_url TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                pricing_model TEXT DEFAULT 'per_request',
                price_cents INTEGER DEFAULT 0,
                currency TEXT DEFAULT 'USD',
                avg_response_ms INTEGER DEFAULT 0,
                max_response_ms INTEGER DEFAULT 0,
                throughput_rpm INTEGER DEFAULT 0,
                uptime_pct REAL DEFAULT 0.0,
                input_modes TEXT DEFAULT '["application/json"]',
                output_modes TEXT DEFAULT '["application/json"]',
                sample_input TEXT DEFAULT '',
                sample_output TEXT DEFAULT '',
                terms_url TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                verified INTEGER DEFAULT 0,
                rating REAL DEFAULT 0.0,
                review_count INTEGER DEFAULT 0,
                total_transactions INTEGER DEFAULT 0,
                created_at REAL,
                updated_at REAL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS agent_services_fts USING fts5(
                id, name, description, tags, category,
                content=agent_services, content_rowid=rowid
            );

            CREATE TABLE IF NOT EXISTS service_reviews (
                id TEXT PRIMARY KEY,
                service_id TEXT NOT NULL REFERENCES agent_services(id),
                reviewer_agent_id TEXT NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT DEFAULT '',
                response_ms INTEGER DEFAULT 0,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS service_categories (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                parent_id TEXT,
                service_count INTEGER DEFAULT 0
            );

            -- Subscriptions & preferences
            CREATE TABLE IF NOT EXISTS subscriptions (
                agent_id TEXT PRIMARY KEY,
                tier TEXT DEFAULT 'free',
                status TEXT DEFAULT 'active',
                payment_token TEXT DEFAULT '',
                created_at REAL,
                expires_at REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS agent_preferences (
                agent_id TEXT PRIMARY KEY,
                max_price_cents INTEGER DEFAULT 0,
                min_rating REAL DEFAULT 0.0,
                preferred_vendors TEXT DEFAULT '[]',
                excluded_vendors TEXT DEFAULT '[]',
                sustainability_weight REAL DEFAULT 0.0,
                speed_weight REAL DEFAULT 0.0,
                price_weight REAL DEFAULT 0.0,
                brand_loyalty TEXT DEFAULT '[]',
                geo_preference TEXT DEFAULT '',
                categories_preferred TEXT DEFAULT '[]',
                categories_excluded TEXT DEFAULT '[]',
                updated_at REAL
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

    def get_all_active_campaigns(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM ad_campaigns WHERE active = 1"
        ).fetchall()
        return [dict(r) for r in rows]

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

    def remove_peer(self, url: str) -> None:
        self._conn.execute("DELETE FROM federation_peers WHERE url = ?", (url,))
        self._conn.commit()

    def update_peer_status(self, url: str, status: str) -> None:
        self._conn.execute(
            "UPDATE federation_peers SET status = ? WHERE url = ?",
            (status, url),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Affiliate links
    # ------------------------------------------------------------------

    def upsert_affiliate(self, link: AffiliateLink) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO affiliate_links
               (referral_code, referring_agent_id, vendor_id, commission_bps,
                total_referrals, total_earned_cents, active, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (link.referral_code, link.referring_agent_id, link.vendor_id,
             link.commission_bps, link.total_referrals, link.total_earned_cents,
             int(link.active), link.created_at),
        )
        self._conn.commit()

    def get_affiliate(self, referral_code: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM affiliate_links WHERE referral_code = ?", (referral_code,)
        ).fetchone()
        return dict(row) if row else None

    def get_agent_affiliates(self, agent_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM affiliate_links WHERE referring_agent_id = ? AND active = 1",
            (agent_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def record_affiliate_referral(self, referral_code: str, earned_cents: int) -> None:
        self._conn.execute(
            "UPDATE affiliate_links SET total_referrals = total_referrals + 1, "
            "total_earned_cents = total_earned_cents + ? WHERE referral_code = ?",
            (earned_cents, referral_code),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Frequency capping
    # ------------------------------------------------------------------

    def get_frequency(self, agent_id: str, campaign_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM frequency_records WHERE agent_id = ? AND campaign_id = ?",
            (agent_id, campaign_id),
        ).fetchone()
        return dict(row) if row else None

    def record_impression_freq(self, agent_id: str, campaign_id: str,
                               window_secs: int = 3600) -> None:
        import time as _t
        now = _t.time()
        existing = self.get_frequency(agent_id, campaign_id)
        if existing:
            if now - existing["window_start"] > window_secs:
                # Reset window
                self._conn.execute(
                    "UPDATE frequency_records SET impressions = 1, window_start = ? "
                    "WHERE agent_id = ? AND campaign_id = ?",
                    (now, agent_id, campaign_id),
                )
            else:
                self._conn.execute(
                    "UPDATE frequency_records SET impressions = impressions + 1 "
                    "WHERE agent_id = ? AND campaign_id = ?",
                    (agent_id, campaign_id),
                )
        else:
            self._conn.execute(
                "INSERT INTO frequency_records (agent_id, campaign_id, impressions, window_start) "
                "VALUES (?,?,1,?)", (agent_id, campaign_id, now),
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # A/B testing
    # ------------------------------------------------------------------

    def log_ab_event(self, ab_group: str, variant: str, event_type: str,
                     campaign_id: str = "", revenue_cents: int = 0) -> None:
        import time as _t
        self._conn.execute(
            "INSERT INTO ab_test_events (ab_group, variant, event_type, campaign_id, revenue_cents, timestamp) "
            "VALUES (?,?,?,?,?,?)",
            (ab_group, variant, event_type, campaign_id, revenue_cents, _t.time()),
        )
        self._conn.commit()

    def get_ab_results(self, ab_group: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT variant,
                  SUM(CASE WHEN event_type='impression' THEN 1 ELSE 0 END) as impressions,
                  SUM(CASE WHEN event_type='click' THEN 1 ELSE 0 END) as clicks,
                  SUM(CASE WHEN event_type='conversion' THEN 1 ELSE 0 END) as conversions,
                  SUM(revenue_cents) as revenue_cents
               FROM ab_test_events WHERE ab_group = ? GROUP BY variant""",
            (ab_group,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Audience segments
    # ------------------------------------------------------------------

    def upsert_segment(self, seg: AgentSegment) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO agent_segments
               (segment_id, label, description, criteria, agent_count, created_at)
               VALUES (?,?,?,?,?,?)""",
            (seg.segment_id, seg.label, seg.description, seg.criteria,
             seg.agent_count, seg.created_at),
        )
        self._conn.commit()

    def get_segment(self, segment_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM agent_segments WHERE segment_id = ?", (segment_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_segments(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM agent_segments").fetchall()
        return [dict(r) for r in rows]

    def assign_segment(self, agent_id: str, segment_id: str,
                       confidence: float = 1.0) -> None:
        import time as _t
        self._conn.execute(
            """INSERT OR REPLACE INTO agent_segment_memberships
               (agent_id, segment_id, confidence, assigned_at) VALUES (?,?,?,?)""",
            (agent_id, segment_id, confidence, _t.time()),
        )
        self._conn.commit()

    def get_agent_segments(self, agent_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT m.*, s.label FROM agent_segment_memberships m
               JOIN agent_segments s ON m.segment_id = s.segment_id
               WHERE m.agent_id = ?""",
            (agent_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_segment_agents(self, segment_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT agent_id FROM agent_segment_memberships WHERE segment_id = ?",
            (segment_id,),
        ).fetchall()
        return [r["agent_id"] for r in rows]

    # ------------------------------------------------------------------
    # Touchpoints & Attribution
    # ------------------------------------------------------------------

    def log_touchpoint(self, tp: TouchPoint) -> None:
        self._conn.execute(
            "INSERT INTO touchpoints (agent_id, event_id, event_type, campaign_id, item_id, timestamp) "
            "VALUES (?,?,?,?,?,?)",
            (tp.agent_id, tp.event_id, tp.event_type, tp.campaign_id,
             tp.item_id, tp.timestamp),
        )
        self._conn.commit()

    def get_agent_touchpoints(self, agent_id: str, *, item_id: str = "",
                              limit: int = 50) -> list[dict[str, Any]]:
        if item_id:
            rows = self._conn.execute(
                "SELECT * FROM touchpoints WHERE agent_id = ? AND item_id = ? "
                "ORDER BY timestamp ASC LIMIT ?",
                (agent_id, item_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM touchpoints WHERE agent_id = ? ORDER BY timestamp ASC LIMIT ?",
                (agent_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def save_attribution(self, attr: ConversionAttribution) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO conversion_attributions
               (order_id, agent_id, item_id, touchpoints, first_touch_campaign,
                last_touch_campaign, attributed_revenue_cents, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (attr.order_id, attr.agent_id, attr.item_id, attr.touchpoints,
             attr.first_touch_campaign, attr.last_touch_campaign,
             attr.attributed_revenue_cents, attr.created_at),
        )
        self._conn.commit()

    def get_campaign_attributions(self, campaign_id: str) -> dict[str, Any]:
        first = self._conn.execute(
            "SELECT COUNT(*) as cnt, SUM(attributed_revenue_cents) as rev "
            "FROM conversion_attributions WHERE first_touch_campaign = ?",
            (campaign_id,),
        ).fetchone()
        last = self._conn.execute(
            "SELECT COUNT(*) as cnt, SUM(attributed_revenue_cents) as rev "
            "FROM conversion_attributions WHERE last_touch_campaign = ?",
            (campaign_id,),
        ).fetchone()
        return {
            "campaign_id": campaign_id,
            "first_touch": {"conversions": first["cnt"] or 0, "revenue_cents": first["rev"] or 0},
            "last_touch": {"conversions": last["cnt"] or 0, "revenue_cents": last["rev"] or 0},
        }

    # ------------------------------------------------------------------
    # Promotions
    # ------------------------------------------------------------------

    def upsert_promotion(self, promo: Promotion) -> None:
        import json
        self._conn.execute(
            """INSERT OR REPLACE INTO promotions
               (promo_id, vendor_id, item_id, code, discount_type, discount_value,
                min_price_cents, max_uses, used_count, starts_at, expires_at,
                active, bundle_item_ids, promo_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (promo.promo_id, promo.vendor_id, promo.item_id, promo.code,
             promo.discount_type, promo.discount_value, promo.min_price_cents,
             promo.max_uses, promo.used_count, promo.starts_at, promo.expires_at,
             int(promo.active), json.dumps(promo.bundle_item_ids), promo.promo_type),
        )
        self._conn.commit()

    def get_promotion_by_code(self, code: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM promotions WHERE code = ? AND active = 1", (code,)
        ).fetchone()
        return dict(row) if row else None

    def get_active_promotions(self, *, vendor_id: str = "",
                              item_id: str = "") -> list[dict[str, Any]]:
        import time as _t
        now = _t.time()
        conditions = ["active = 1", "(expires_at = 0 OR expires_at > ?)", "(starts_at = 0 OR starts_at <= ?)"]
        params: list[Any] = [now, now]
        if vendor_id:
            conditions.append("vendor_id = ?")
            params.append(vendor_id)
        if item_id:
            conditions.append("(item_id = ? OR item_id = '')")
            params.append(item_id)
        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT * FROM promotions WHERE {where}", params
        ).fetchall()
        return [dict(r) for r in rows]

    def increment_promo_usage(self, promo_id: str) -> None:
        self._conn.execute(
            "UPDATE promotions SET used_count = used_count + 1 WHERE promo_id = ?",
            (promo_id,),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Cross-sell rules
    # ------------------------------------------------------------------

    def upsert_cross_sell(self, rule: CrossSellRule) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO cross_sell_rules
               (source_item_id, target_item_id, relation_type, vendor_id, bid_cents, priority)
               VALUES (?,?,?,?,?,?)""",
            (rule.source_item_id, rule.target_item_id, rule.relation_type,
             rule.vendor_id, rule.bid_cents, rule.priority),
        )
        self._conn.commit()

    def get_cross_sells(self, item_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT cs.*, i.name as target_name, i.price_cents as target_price_cents,
                      i.rating as target_rating
               FROM cross_sell_rules cs
               JOIN items i ON cs.target_item_id = i.id
               WHERE cs.source_item_id = ?
               ORDER BY cs.priority DESC, cs.bid_cents DESC""",
            (item_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Video catalog
    # ------------------------------------------------------------------

    def upsert_video_channel(self, ch: VideoChannel) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO video_channels
               (id, name, platform, subscriber_count, video_count,
                description, avatar_url, verified, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (ch.id, ch.name, ch.platform, ch.subscriber_count, ch.video_count,
             ch.description, ch.avatar_url, int(ch.verified), ch.created_at),
        )
        self._conn.commit()

    def upsert_video_category(self, cat: VideoCategory) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO video_categories (id, label, parent_id, video_count) "
            "VALUES (?,?,?,?)",
            (cat.id, cat.label, cat.parent_id, cat.video_count),
        )
        self._conn.commit()

    def upsert_video(self, v: VideoItem) -> None:
        import json
        self._conn.execute(
            """INSERT OR REPLACE INTO videos
               (id, title, description, channel_id, platform, category_id,
                duration_secs, views, likes, rating, publish_ts, thumbnail_url,
                video_url, transcript_summary, tags, chapters, resolution,
                language, sponsored, ad_tag, active, embedding, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (v.id, v.title, v.description, v.channel_id, v.platform,
             v.category_id, v.duration_secs, v.views, v.likes, v.rating,
             v.publish_ts, v.thumbnail_url, v.video_url, v.transcript_summary,
             json.dumps(v.tags), json.dumps(v.chapters), v.resolution,
             v.language, v.sponsored, v.ad_tag, int(v.active), v.embedding,
             v.created_at),
        )
        # Update FTS
        self._conn.execute(
            "INSERT OR REPLACE INTO videos_fts (rowid, id, title, description, transcript_summary) "
            "SELECT rowid, id, title, description, transcript_summary FROM videos WHERE id = ?",
            (v.id,),
        )
        self._conn.commit()

    def upsert_video_playlist(self, pl: VideoPlaylist) -> None:
        import json
        self._conn.execute(
            """INSERT OR REPLACE INTO video_playlists
               (id, title, description, channel_id, video_ids, auto_generated, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (pl.id, pl.title, pl.description, pl.channel_id,
             json.dumps(pl.video_ids), int(pl.auto_generated), pl.created_at),
        )
        self._conn.commit()

    def search_videos(
        self,
        query: str,
        *,
        category: str | None = None,
        platform: str | None = None,
        channel_id: str | None = None,
        duration_min: int | None = None,
        duration_max: int | None = None,
        sort: str = "relevance",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        conditions = ["v.active = 1"]
        params: list[Any] = []
        if category:
            conditions.append("v.category_id = ?")
            params.append(category)
        if platform:
            conditions.append("v.platform = ?")
            params.append(platform)
        if channel_id:
            conditions.append("v.channel_id = ?")
            params.append(channel_id)
        if duration_min is not None:
            conditions.append("v.duration_secs >= ?")
            params.append(duration_min)
        if duration_max is not None:
            conditions.append("v.duration_secs <= ?")
            params.append(duration_max)

        where = " AND ".join(conditions)
        if query.strip():
            fts_clause = "v.rowid IN (SELECT rowid FROM videos_fts WHERE videos_fts MATCH ?)"
            where = f"{where} AND {fts_clause}"
            params.append(query)

        order = {
            "views": "v.views DESC",
            "rating": "v.rating DESC",
            "newest": "v.publish_ts DESC",
            "duration_asc": "v.duration_secs ASC",
            "duration_desc": "v.duration_secs DESC",
        }.get(sort, "v.sponsored DESC, v.views DESC")

        params.append(limit)
        rows = self._conn.execute(
            f"SELECT v.*, c.name as channel_name FROM videos v "
            f"JOIN video_channels c ON v.channel_id = c.id "
            f"WHERE {where} ORDER BY {order} LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def lookup_video(self, video_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT v.*, c.name as channel_name FROM videos v "
            "JOIN video_channels c ON v.channel_id = c.id WHERE v.id = ?",
            (video_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_video_categories(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        if parent_id is None:
            rows = self._conn.execute(
                "SELECT * FROM video_categories WHERE parent_id IS NULL ORDER BY label"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM video_categories WHERE parent_id = ? ORDER BY label",
                (parent_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM video_channels WHERE id = ?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_channel_videos(self, channel_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT v.*, c.name as channel_name FROM videos v "
            "JOIN video_channels c ON v.channel_id = c.id "
            "WHERE v.channel_id = ? AND v.active = 1 ORDER BY v.publish_ts DESC LIMIT ?",
            (channel_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_trending_videos(self, *, category: str | None = None,
                            limit: int = 10) -> list[dict[str, Any]]:
        conditions = ["v.active = 1"]
        params: list[Any] = []
        if category:
            conditions.append("v.category_id = ?")
            params.append(category)
        where = " AND ".join(conditions)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT v.*, c.name as channel_name FROM videos v "
            f"JOIN video_channels c ON v.channel_id = c.id "
            f"WHERE {where} ORDER BY v.views DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_video_playlist(self, playlist_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM video_playlists WHERE id = ?", (playlist_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_video_playlists(self, *, channel_id: str | None = None,
                             limit: int = 20) -> list[dict[str, Any]]:
        if channel_id:
            rows = self._conn.execute(
                "SELECT * FROM video_playlists WHERE channel_id = ? ORDER BY created_at DESC LIMIT ?",
                (channel_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM video_playlists ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
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

    # ------------------------------------------------------------------
    # Agent Directory (People) operations
    # ------------------------------------------------------------------

    def upsert_person(self, p: PersonProfile) -> None:
        import json as _json
        self._conn.execute(
            """INSERT OR REPLACE INTO people
            (id, name, headline, agent_url, agent_card_url, agent_description,
             agent_skills, agent_verified, location, skills, experience_years,
             current_company, current_title, industry, bio, email, website,
             avatar_url, available_for_hire, verified, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (p.id, p.name, p.headline, p.agent_url, p.agent_card_url,
             p.agent_description, _json.dumps(p.agent_skills),
             int(p.agent_verified), p.location, _json.dumps(p.skills),
             p.experience_years, p.current_company, p.current_title,
             p.industry, p.bio, p.email, p.website, p.avatar_url,
             int(p.available_for_hire), int(p.verified),
             p.created_at, p.updated_at),
        )
        # Update FTS index
        rid = self._conn.execute("SELECT rowid FROM people WHERE id = ?", (p.id,)).fetchone()
        if rid:
            self._conn.execute(
                "INSERT OR REPLACE INTO people_fts (rowid, id, name, headline, bio, skills, agent_description, agent_skills) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (rid[0], p.id, p.name, p.headline, p.bio,
                 " ".join(p.skills), p.agent_description,
                 " ".join(p.agent_skills)),
            )
        self._conn.commit()

    def search_people(self, q: str, *, location: str | None = None,
                      skill: str | None = None, available_only: bool = False,
                      industry: str | None = None,
                      limit: int = 10) -> list[dict[str, Any]]:
        conditions: list[str] = ["p.id IS NOT NULL"]
        params: list[Any] = []
        if q:
            fts_clause = "p.rowid IN (SELECT rowid FROM people_fts WHERE people_fts MATCH ?)"
            conditions.append(fts_clause)
            params.append(q)
        if location:
            conditions.append("p.location LIKE ?")
            params.append(f"%{location}%")
        if skill:
            conditions.append("(p.skills LIKE ? OR p.agent_skills LIKE ?)")
            params.append(f"%{skill}%")
            params.append(f"%{skill}%")
        if available_only:
            conditions.append("p.available_for_hire = 1")
        if industry:
            conditions.append("p.industry = ?")
            params.append(industry)
        where = " AND ".join(conditions)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM people p WHERE {where} LIMIT ?", params
        ).fetchall()
        return [dict(r) for r in rows]

    def lookup_person(self, person_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM people WHERE id = ?", (person_id,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_directory_skill(self, skill_id: str, label: str, agent_count: int = 0) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO directory_skill_tags (id, label, agent_count) VALUES (?,?,?)",
            (skill_id, label, agent_count),
        )
        self._conn.commit()

    def list_directory_skills(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM directory_skill_tags ORDER BY label"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Business directory operations
    # ------------------------------------------------------------------

    def upsert_business(self, b: BusinessProfile) -> None:
        import json as _json
        self._conn.execute(
            """INSERT OR REPLACE INTO businesses
            (id, name, description, industry, location, website, employee_count,
             founded_year, revenue_range, logo_url, verified, open_jobs,
             specialties, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (b.id, b.name, b.description, b.industry, b.location, b.website,
             b.employee_count, b.founded_year, b.revenue_range, b.logo_url,
             int(b.verified), b.open_jobs, _json.dumps(b.specialties),
             b.created_at, b.updated_at),
        )
        rid = self._conn.execute("SELECT rowid FROM businesses WHERE id = ?", (b.id,)).fetchone()
        if rid:
            self._conn.execute(
                "INSERT OR REPLACE INTO businesses_fts (rowid, id, name, description, specialties) "
                "VALUES (?,?,?,?,?)",
                (rid[0], b.id, b.name, b.description, " ".join(b.specialties)),
            )
        self._conn.commit()

    def search_businesses(self, q: str, *, industry: str | None = None,
                          location: str | None = None,
                          limit: int = 10) -> list[dict[str, Any]]:
        conditions: list[str] = ["b.id IS NOT NULL"]
        params: list[Any] = []
        if q:
            conditions.append("b.rowid IN (SELECT rowid FROM businesses_fts WHERE businesses_fts MATCH ?)")
            params.append(q)
        if industry:
            conditions.append("b.industry = ?")
            params.append(industry)
        if location:
            conditions.append("b.location LIKE ?")
            params.append(f"%{location}%")
        where = " AND ".join(conditions)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM businesses b WHERE {where} LIMIT ?", params
        ).fetchall()
        return [dict(r) for r in rows]

    def lookup_business(self, biz_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM businesses WHERE id = ?", (biz_id,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_industry(self, cat: IndustryCategory) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO industry_categories (id, label, parent_id, business_count) "
            "VALUES (?,?,?,?)",
            (cat.id, cat.label, cat.parent_id, cat.business_count),
        )
        self._conn.commit()

    def list_industries(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        if parent_id is None:
            rows = self._conn.execute(
                "SELECT * FROM industry_categories WHERE parent_id IS NULL ORDER BY label"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM industry_categories WHERE parent_id = ? ORDER BY label",
                (parent_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Job postings operations
    # ------------------------------------------------------------------

    def upsert_job(self, j: JobPosting) -> None:
        import json as _json
        self._conn.execute(
            """INSERT OR REPLACE INTO jobs
            (id, title, company_id, description, location, remote,
             employment_type, salary_min_cents, salary_max_cents, salary_currency,
             experience_min, experience_max, skills_required, industry,
             category, apply_url, active, posted_at, expires_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (j.id, j.title, j.company_id, j.description, j.location,
             int(j.remote), j.employment_type, j.salary_min_cents,
             j.salary_max_cents, j.salary_currency, j.experience_min,
             j.experience_max, _json.dumps(j.skills_required), j.industry,
             j.category, j.apply_url, int(j.active), j.posted_at, j.expires_at),
        )
        rid = self._conn.execute("SELECT rowid FROM jobs WHERE id = ?", (j.id,)).fetchone()
        if rid:
            self._conn.execute(
                "INSERT OR REPLACE INTO jobs_fts (rowid, id, title, description, skills_required) "
                "VALUES (?,?,?,?,?)",
                (rid[0], j.id, j.title, j.description, " ".join(j.skills_required)),
            )
        self._conn.commit()

    def search_jobs(self, q: str, *, location: str | None = None,
                    remote_only: bool = False, employment_type: str | None = None,
                    industry: str | None = None, category: str | None = None,
                    salary_min: int | None = None,
                    limit: int = 10) -> list[dict[str, Any]]:
        conditions: list[str] = ["j.active = 1"]
        params: list[Any] = []
        if q:
            conditions.append("j.rowid IN (SELECT rowid FROM jobs_fts WHERE jobs_fts MATCH ?)")
            params.append(q)
        if location:
            conditions.append("j.location LIKE ?")
            params.append(f"%{location}%")
        if remote_only:
            conditions.append("j.remote = 1")
        if employment_type:
            conditions.append("j.employment_type = ?")
            params.append(employment_type)
        if industry:
            conditions.append("j.industry = ?")
            params.append(industry)
        if category:
            conditions.append("j.category = ?")
            params.append(category)
        if salary_min is not None:
            conditions.append("j.salary_max_cents >= ?")
            params.append(salary_min)
        where = " AND ".join(conditions)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT j.*, b.name as company_name FROM jobs j "
            f"JOIN businesses b ON j.company_id = b.id "
            f"WHERE {where} ORDER BY j.posted_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def lookup_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT j.*, b.name as company_name FROM jobs j "
            "JOIN businesses b ON j.company_id = b.id WHERE j.id = ?",
            (job_id,),
        ).fetchone()
        return dict(row) if row else None

    def upsert_job_category(self, cat: JobCategory) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO job_categories (id, label, parent_id, job_count) "
            "VALUES (?,?,?,?)",
            (cat.id, cat.label, cat.parent_id, cat.job_count),
        )
        self._conn.commit()

    def list_job_categories(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        if parent_id is None:
            rows = self._conn.execute(
                "SELECT * FROM job_categories WHERE parent_id IS NULL ORDER BY label"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM job_categories WHERE parent_id = ? ORDER BY label",
                (parent_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_company_jobs(self, company_id: str, *, active_only: bool = True,
                         limit: int = 20) -> list[dict[str, Any]]:
        conditions = ["j.company_id = ?"]
        params: list[Any] = [company_id]
        if active_only:
            conditions.append("j.active = 1")
        where = " AND ".join(conditions)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT j.*, b.name as company_name FROM jobs j "
            f"JOIN businesses b ON j.company_id = b.id "
            f"WHERE {where} ORDER BY j.posted_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Agent services marketplace CRUD
    # ------------------------------------------------------------------

    def upsert_agent_service(self, svc: AgentService) -> None:
        import json as _json
        self._conn.execute(
            "INSERT OR REPLACE INTO agent_services "
            "(id, agent_id, agent_url, name, description, category, tags, "
            "pricing_model, price_cents, currency, avg_response_ms, max_response_ms, "
            "throughput_rpm, uptime_pct, input_modes, output_modes, sample_input, "
            "sample_output, terms_url, active, verified, rating, review_count, "
            "total_transactions, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (svc.id, svc.agent_id, svc.agent_url, svc.name, svc.description,
             svc.category, _json.dumps(svc.tags), svc.pricing_model, svc.price_cents,
             svc.currency, svc.avg_response_ms, svc.max_response_ms,
             svc.throughput_rpm, svc.uptime_pct,
             _json.dumps(svc.input_modes), _json.dumps(svc.output_modes),
             svc.sample_input, svc.sample_output, svc.terms_url,
             int(svc.active), int(svc.verified), svc.rating, svc.review_count,
             svc.total_transactions, svc.created_at, svc.updated_at),
        )
        # FTS index
        self._conn.execute(
            "INSERT OR REPLACE INTO agent_services_fts "
            "(rowid, id, name, description, tags, category) "
            "VALUES ((SELECT rowid FROM agent_services WHERE id = ?), ?,?,?,?,?)",
            (svc.id, svc.id, svc.name, svc.description,
             " ".join(svc.tags), svc.category),
        )
        self._conn.commit()

    def search_agent_services(self, q: str, *, category: str | None = None,
                              pricing_model: str | None = None,
                              max_price: int | None = None,
                              verified_only: bool = False,
                              min_rating: float | None = None,
                              limit: int = 10) -> list[dict[str, Any]]:
        conditions = ["s.active = 1"]
        params: list[Any] = []
        if q:
            conditions.append(
                "s.id IN (SELECT id FROM agent_services_fts WHERE agent_services_fts MATCH ?)"
            )
            params.append(q)
        if category:
            conditions.append("s.category = ?")
            params.append(category)
        if pricing_model:
            conditions.append("s.pricing_model = ?")
            params.append(pricing_model)
        if max_price is not None:
            conditions.append("s.price_cents <= ?")
            params.append(max_price)
        if verified_only:
            conditions.append("s.verified = 1")
        if min_rating is not None:
            conditions.append("s.rating >= ?")
            params.append(min_rating)
        where = " AND ".join(conditions)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM agent_services s WHERE {where} "
            f"ORDER BY s.rating DESC, s.total_transactions DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def lookup_agent_service(self, service_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM agent_services WHERE id = ?", (service_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_agent_services(self, agent_id: str, *, active_only: bool = True,
                           limit: int = 50) -> list[dict[str, Any]]:
        conditions = ["agent_id = ?"]
        params: list[Any] = [agent_id]
        if active_only:
            conditions.append("active = 1")
        where = " AND ".join(conditions)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM agent_services WHERE {where} ORDER BY rating DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_service_review(self, rev: ServiceReview) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO service_reviews "
            "(id, service_id, reviewer_agent_id, rating, comment, response_ms, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (rev.id, rev.service_id, rev.reviewer_agent_id,
             rev.rating, rev.comment, rev.response_ms, rev.created_at),
        )
        # Update aggregate rating on the service
        agg = self._conn.execute(
            "SELECT AVG(rating) as avg_r, COUNT(*) as cnt FROM service_reviews WHERE service_id = ?",
            (rev.service_id,),
        ).fetchone()
        if agg:
            self._conn.execute(
                "UPDATE agent_services SET rating = ?, review_count = ?, updated_at = ? WHERE id = ?",
                (round(agg["avg_r"], 2), agg["cnt"], rev.created_at, rev.service_id),
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def upsert_subscription(self, sub: Subscription) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO subscriptions
               (agent_id, tier, status, payment_token, created_at, expires_at)
               VALUES (?,?,?,?,?,?)""",
            (sub.agent_id, sub.tier, sub.status, sub.payment_token,
             sub.created_at, sub.expires_at),
        )
        self._conn.commit()

    def get_subscription(self, agent_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM subscriptions WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return dict(row) if row else None

    def cancel_subscription(self, agent_id: str) -> None:
        self._conn.execute(
            "UPDATE subscriptions SET status = 'cancelled' WHERE agent_id = ?",
            (agent_id,),
        )
        self._conn.commit()

    def is_premium(self, agent_id: str) -> bool:
        """Check if agent has an active premium subscription."""
        import time as _t
        row = self._conn.execute(
            "SELECT * FROM subscriptions WHERE agent_id = ? AND tier = 'premium' AND status = 'active'",
            (agent_id,),
        ).fetchone()
        if not row:
            return False
        if row["expires_at"] and row["expires_at"] < _t.time():
            return False
        return True

    # ------------------------------------------------------------------
    # Agent Preferences
    # ------------------------------------------------------------------

    def upsert_preferences(self, prefs: AgentPreferences) -> None:
        import json
        self._conn.execute(
            """INSERT OR REPLACE INTO agent_preferences
               (agent_id, max_price_cents, min_rating, preferred_vendors,
                excluded_vendors, sustainability_weight, speed_weight,
                price_weight, brand_loyalty, geo_preference,
                categories_preferred, categories_excluded, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (prefs.agent_id, prefs.max_price_cents, prefs.min_rating,
             json.dumps(prefs.preferred_vendors),
             json.dumps(prefs.excluded_vendors),
             prefs.sustainability_weight, prefs.speed_weight,
             prefs.price_weight, json.dumps(prefs.brand_loyalty),
             prefs.geo_preference,
             json.dumps(prefs.categories_preferred),
             json.dumps(prefs.categories_excluded),
             prefs.updated_at),
        )
        self._conn.commit()

    def get_preferences(self, agent_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM agent_preferences WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if not row:
            return None
        import json
        d = dict(row)
        for k in ("preferred_vendors", "excluded_vendors", "brand_loyalty",
                   "categories_preferred", "categories_excluded"):
            if isinstance(d[k], str):
                d[k] = json.loads(d[k])
        return d

    def delete_preferences(self, agent_id: str) -> None:
        self._conn.execute(
            "DELETE FROM agent_preferences WHERE agent_id = ?", (agent_id,)
        )
        self._conn.commit()

    def get_service_reviews(self, service_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM service_reviews WHERE service_id = ? ORDER BY created_at DESC LIMIT ?",
            (service_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_service_category(self, cat: ServiceCategory) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO service_categories (id, label, parent_id, service_count) "
            "VALUES (?,?,?,?)",
            (cat.id, cat.label, cat.parent_id, cat.service_count),
        )
        self._conn.commit()

    def list_service_categories(self, parent_id: str | None = None) -> list[dict[str, Any]]:
        if parent_id is None:
            rows = self._conn.execute(
                "SELECT * FROM service_categories WHERE parent_id IS NULL ORDER BY label"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM service_categories WHERE parent_id = ? ORDER BY label",
                (parent_id,),
            ).fetchall()
        return [dict(r) for r in rows]
