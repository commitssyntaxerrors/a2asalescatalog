# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""A2A Sales Catalog — Job postings skill handlers.

Skill namespace: jobs.* for searching, posting, and browsing jobs.
"""

from __future__ import annotations

import time
from typing import Any

from src.common.models import JOB_SEARCH_FIELDS, JOB_CATEGORY_FIELDS
from src.server.store import CatalogStore


class JobsSkillRouter:
    """Dispatches jobs.* skill invocations to handler methods."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store
        self._handlers: dict[str, Any] = {
            "jobs.search": self._handle_search,
            "jobs.lookup": self._handle_lookup,
            "jobs.post": self._handle_post,
            "jobs.categories": self._handle_categories,
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
    # jobs.search
    # ------------------------------------------------------------------

    def _handle_search(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        q = str(data.get("q", ""))
        limit = min(int(data.get("max", 10)), 50)
        location = data.get("location")
        remote_only = bool(data.get("remote_only", False))
        employment_type = data.get("employment_type")
        industry = data.get("industry")
        category = data.get("category")
        salary_min = data.get("salary_min")

        rows = self._store.search_jobs(
            q, location=location, remote_only=remote_only,
            employment_type=employment_type, industry=industry,
            category=category, salary_min=salary_min, limit=limit,
        )

        items = []
        for row in rows:
            items.append([
                row["id"],
                row["title"],
                row["company_id"],
                row["location"],
                bool(row["remote"]),
                row["employment_type"],
                row["salary_min_cents"],
                row["salary_max_cents"],
            ])

        return {
            "fields": JOB_SEARCH_FIELDS,
            "items": items,
            "total": len(items),
        }

    # ------------------------------------------------------------------
    # jobs.lookup
    # ------------------------------------------------------------------

    def _handle_lookup(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        job_id = str(data.get("id", ""))
        if not job_id:
            return {"error": "id required"}

        row = self._store.lookup_job(job_id)
        if not row:
            return {"error": f"Job not found: {job_id}"}

        import json
        skills_required = json.loads(row["skills_required"]) if isinstance(row["skills_required"], str) else row["skills_required"]

        return {
            "id": row["id"],
            "title": row["title"],
            "company_id": row["company_id"],
            "company_name": row.get("company_name", ""),
            "description": row["description"],
            "location": row["location"],
            "remote": bool(row["remote"]),
            "employment_type": row["employment_type"],
            "salary_min_cents": row["salary_min_cents"],
            "salary_max_cents": row["salary_max_cents"],
            "experience_min": row["experience_min"],
            "experience_max": row["experience_max"],
            "skills_required": skills_required,
            "industry": row["industry"],
            "category": row["category"],
            "apply_url": row["apply_url"],
            "active": bool(row["active"]),
            "posted_at": row["posted_at"],
            "expires_at": row["expires_at"],
        }

    # ------------------------------------------------------------------
    # jobs.post — create / update a job posting
    # ------------------------------------------------------------------

    def _handle_post(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        from src.common.models import JobPosting

        job_id = data.get("id")
        title = data.get("title")
        company_id = data.get("company_id")
        if not job_id or not title or not company_id:
            return {"error": "id, title, and company_id are required"}

        now = time.time()
        posting = JobPosting(
            id=job_id,
            title=title,
            company_id=company_id,
            description=data.get("description", ""),
            location=data.get("location", ""),
            remote=bool(data.get("remote", False)),
            employment_type=data.get("employment_type", "full-time"),
            salary_min_cents=int(data.get("salary_min_cents", 0)),
            salary_max_cents=int(data.get("salary_max_cents", 0)),
            experience_min=int(data.get("experience_min", 0)),
            experience_max=int(data.get("experience_max", 0)),
            skills_required=data.get("skills_required", []),
            industry=data.get("industry", ""),
            category=data.get("category", ""),
            apply_url=data.get("apply_url", ""),
            active=True,
            posted_at=now,
            expires_at=data.get("expires_at", now + 30 * 86400),
        )
        self._store.upsert_job(posting)
        return {
            "status": "posted",
            "id": posting.id,
            "title": posting.title,
        }

    # ------------------------------------------------------------------
    # jobs.categories
    # ------------------------------------------------------------------

    def _handle_categories(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        cats = self._store.list_job_categories()
        return {
            "fields": JOB_CATEGORY_FIELDS,
            "categories": [[c["id"], c["label"], c["job_count"]] for c in cats],
        }
