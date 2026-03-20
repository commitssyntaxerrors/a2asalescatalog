# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""A2A Sales Catalog — Business directory skill handlers.

Skill namespace: business.* for company profiles and industry browsing.
"""

from __future__ import annotations

import json
from typing import Any

from src.common.models import BUSINESS_SEARCH_FIELDS, INDUSTRY_FIELDS
from src.server.store import CatalogStore


class BusinessSkillRouter:
    """Dispatches business.* skill invocations to handler methods."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store
        self._handlers: dict[str, Any] = {
            "business.search": self._handle_search,
            "business.lookup": self._handle_lookup,
            "business.industries": self._handle_industries,
        }

    @property
    def skill_ids(self) -> list[str]:
        return list(self._handlers.keys())

    def can_handle(self, skill: str) -> bool:
        return skill in self._handlers

    def handle(self, data: dict[str, Any], agent_id: str = "") -> dict[str, Any]:
        skill = data.get("skill", "")
        handler = self._handlers.get(skill)
        if not handler:
            return {"error": f"Unknown skill: {skill}"}
        return handler(data, agent_id)

    # ------------------------------------------------------------------
    # business.search
    # ------------------------------------------------------------------

    def _handle_search(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        q = str(data.get("q", ""))
        limit = min(int(data.get("max", 10)), 50)
        industry = data.get("industry")
        location = data.get("location")

        rows = self._store.search_businesses(
            q, industry=industry, location=location, limit=limit,
        )

        items = []
        for row in rows:
            items.append([
                row["id"],
                row["name"],
                row["industry"],
                row["location"],
                row["employee_count"],
                row["open_jobs"],
                bool(row["verified"]),
            ])

        return {
            "fields": BUSINESS_SEARCH_FIELDS,
            "items": items,
            "total": len(items),
        }

    # ------------------------------------------------------------------
    # business.lookup
    # ------------------------------------------------------------------

    def _handle_lookup(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        biz_id = str(data.get("id", ""))
        if not biz_id:
            return {"error": "id required"}

        row = self._store.lookup_business(biz_id)
        if not row:
            return {"error": f"Business not found: {biz_id}"}

        specialties = json.loads(row["specialties"]) if isinstance(row["specialties"], str) else row["specialties"]

        # Also pull active jobs for this company
        jobs = self._store.get_company_jobs(biz_id)
        job_list = [{"id": j["id"], "title": j["title"]} for j in jobs]

        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "industry": row["industry"],
            "location": row["location"],
            "website": row["website"],
            "employee_count": row["employee_count"],
            "founded_year": row["founded_year"],
            "revenue_range": row["revenue_range"],
            "specialties": specialties,
            "verified": bool(row["verified"]),
            "open_jobs": len(job_list),
            "jobs": job_list,
        }

    # ------------------------------------------------------------------
    # business.industries
    # ------------------------------------------------------------------

    def _handle_industries(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        industries = self._store.list_industries()
        return {
            "fields": INDUSTRY_FIELDS,
            "industries": [[i["id"], i["label"], i["business_count"]] for i in industries],
        }
