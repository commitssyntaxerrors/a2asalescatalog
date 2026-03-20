"""A2A Sales Catalog — in-memory store for MVP phase.

Uses SQLite FTS5 for full-text search. Upgradeable to PostgreSQL + Meilisearch.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from src.common.models import AdCampaign, CatalogItem, Category, Vendor

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
                budget_cents INTEGER DEFAULT 0,
                spent_cents INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                ad_tag TEXT DEFAULT ''
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
                active, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item.id, item.name, item.desc, item.price_cents, item.currency,
                item.vendor_id, item.category_id, item.rating, item.review_count,
                json.dumps(item.attrs), item.buy_url, json.dumps(item.images),
                item.sponsored, item.ad_tag, int(item.active),
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
               (id, vendor_id, keywords, categories, bid_cents, budget_cents,
                spent_cents, active, ad_tag)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                camp.id, camp.vendor_id, json.dumps(camp.keywords),
                json.dumps(camp.categories), camp.bid_cents, camp.budget_cents,
                camp.spent_cents, int(camp.active), camp.ad_tag,
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
