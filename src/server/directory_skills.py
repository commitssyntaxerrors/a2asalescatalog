# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""A2A Sales Catalog — Agent Directory skill handlers.

Skill namespace: directory.* for discovering humans' agents.
Humans register profiles with their agent endpoints; other agents
search the directory to find specialists and transact over A2A.
"""

from __future__ import annotations

import json
from typing import Any

from src.common.models import DIRECTORY_SEARCH_FIELDS, DIRECTORY_SKILL_FIELDS
from src.server.store import CatalogStore


class DirectorySkillRouter:
    """Dispatches directory.* skill invocations to handler methods."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store
        self._handlers: dict[str, Any] = {
            "directory.search": self._handle_search,
            "directory.lookup": self._handle_lookup,
            "directory.skills": self._handle_skills,
            "directory.register": self._handle_register,
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
    # directory.search — find agents by capability, skill, location
    # ------------------------------------------------------------------

    def _handle_search(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        q = str(data.get("q", ""))
        limit = min(int(data.get("max", 10)), 50)
        location = data.get("location")
        skill = data.get("skill_tag")
        available_only = bool(data.get("available_only", False))
        industry = data.get("industry")

        rows = self._store.search_people(
            q, location=location, skill=skill,
            available_only=available_only, industry=industry,
            limit=limit,
        )

        items = []
        for row in rows:
            items.append([
                row["id"],
                row["name"],
                row["headline"],
                row["agent_url"],
                row["location"],
                bool(row["agent_verified"]),
                bool(row["available_for_hire"]),
                bool(row["verified"]),
            ])

        return {
            "fields": DIRECTORY_SEARCH_FIELDS,
            "items": items,
            "total": len(items),
        }

    # ------------------------------------------------------------------
    # directory.lookup — full profile + agent endpoint details
    # ------------------------------------------------------------------

    def _handle_lookup(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        person_id = str(data.get("id", ""))
        if not person_id:
            return {"error": "id required"}

        row = self._store.lookup_person(person_id)
        if not row:
            return {"error": f"Person not found: {person_id}"}

        skills = json.loads(row["skills"]) if isinstance(row["skills"], str) else row["skills"]
        agent_skills = json.loads(row["agent_skills"]) if isinstance(row["agent_skills"], str) else row["agent_skills"]

        return {
            "id": row["id"],
            "name": row["name"],
            "headline": row["headline"],
            "agent": {
                "url": row["agent_url"],
                "card_url": row["agent_card_url"],
                "description": row["agent_description"],
                "skills": agent_skills,
                "verified": bool(row["agent_verified"]),
            },
            "location": row["location"],
            "skills": skills,
            "experience_years": row["experience_years"],
            "current_company": row["current_company"],
            "current_title": row["current_title"],
            "industry": row["industry"],
            "bio": row["bio"],
            "website": row["website"],
            "available_for_hire": bool(row["available_for_hire"]),
            "verified": bool(row["verified"]),
        }

    # ------------------------------------------------------------------
    # directory.skills — browse capability tags
    # ------------------------------------------------------------------

    def _handle_skills(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        skills = self._store.list_directory_skills()
        return {
            "fields": DIRECTORY_SKILL_FIELDS,
            "skills": [[s["id"], s["label"], s["agent_count"]] for s in skills],
        }

    # ------------------------------------------------------------------
    # directory.register — register/update a person + agent profile
    # ------------------------------------------------------------------

    def _handle_register(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        from src.common.models import PersonProfile
        import time

        person_id = data.get("id")
        name = data.get("name")
        headline = data.get("headline")
        if not person_id or not name or not headline:
            return {"error": "id, name, and headline are required"}

        profile = PersonProfile(
            id=person_id,
            name=name,
            headline=headline,
            agent_url=data.get("agent_url", ""),
            agent_card_url=data.get("agent_card_url", ""),
            agent_description=data.get("agent_description", ""),
            agent_skills=data.get("agent_skills", []),
            agent_verified=False,  # verification is server-side
            location=data.get("location", ""),
            skills=data.get("skills", []),
            experience_years=int(data.get("experience_years", 0)),
            current_company=data.get("current_company", ""),
            current_title=data.get("current_title", ""),
            industry=data.get("industry", ""),
            bio=data.get("bio", ""),
            email=data.get("email", ""),
            website=data.get("website", ""),
            available_for_hire=bool(data.get("available_for_hire", False)),
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._store.upsert_person(profile)
        return {
            "status": "registered",
            "id": profile.id,
            "agent_url": profile.agent_url,
        }
