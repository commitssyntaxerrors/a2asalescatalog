# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""A2A Sales Catalog — Agent Services marketplace skill handlers.

Skill namespace: services.* for agents listing their own services for sale.
Unlike the directory (human registers profile → agent endpoint), here the
*agent itself* lists services with pricing, SLAs, and terms — operating
independently as a service provider.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from src.common.models import (
    SERVICE_SEARCH_FIELDS, SERVICE_CATEGORY_FIELDS, SERVICE_REVIEW_FIELDS,
)
from src.server.store import CatalogStore


class ServicesSkillRouter:
    """Dispatches services.* skill invocations to handler methods."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store
        self._handlers: dict[str, Any] = {
            "services.search": self._handle_search,
            "services.lookup": self._handle_lookup,
            "services.list": self._handle_list,
            "services.publish": self._handle_publish,
            "services.review": self._handle_review,
            "services.reviews": self._handle_reviews,
            "services.categories": self._handle_categories,
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
    # services.search — find agent services by capability, price, rating
    # ------------------------------------------------------------------

    def _handle_search(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        q = str(data.get("q", ""))
        limit = min(int(data.get("max", 10)), 50)
        category = data.get("category")
        pricing_model = data.get("pricing_model")
        max_price = data.get("max_price")
        verified_only = bool(data.get("verified_only", False))
        min_rating = data.get("min_rating")

        if max_price is not None:
            max_price = int(max_price)
        if min_rating is not None:
            min_rating = float(min_rating)

        rows = self._store.search_agent_services(
            q, category=category, pricing_model=pricing_model,
            max_price=max_price, verified_only=verified_only,
            min_rating=min_rating, limit=limit,
        )

        items = []
        for row in rows:
            items.append([
                row["id"],
                row["name"],
                row["agent_id"],
                row["category"],
                row["pricing_model"],
                row["price_cents"],
                row["rating"],
                bool(row["verified"]),
                bool(row["active"]),
            ])

        return {
            "fields": SERVICE_SEARCH_FIELDS,
            "items": items,
            "total": len(items),
        }

    # ------------------------------------------------------------------
    # services.lookup — full service details
    # ------------------------------------------------------------------

    def _handle_lookup(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        service_id = str(data.get("id", ""))
        if not service_id:
            return {"error": "id required"}

        row = self._store.lookup_agent_service(service_id)
        if not row:
            return {"error": f"Service not found: {service_id}"}

        tags = json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"]
        input_modes = json.loads(row["input_modes"]) if isinstance(row["input_modes"], str) else row["input_modes"]
        output_modes = json.loads(row["output_modes"]) if isinstance(row["output_modes"], str) else row["output_modes"]

        # Get recent reviews
        reviews = self._store.get_service_reviews(service_id, limit=5)
        review_list = [
            {"id": r["id"], "rating": r["rating"], "comment": r["comment"],
             "reviewer": r["reviewer_agent_id"], "created_at": r["created_at"]}
            for r in reviews
        ]

        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "agent_url": row["agent_url"],
            "name": row["name"],
            "description": row["description"],
            "category": row["category"],
            "tags": tags,
            "pricing": {
                "model": row["pricing_model"],
                "price_cents": row["price_cents"],
                "currency": row["currency"],
            },
            "sla": {
                "avg_response_ms": row["avg_response_ms"],
                "max_response_ms": row["max_response_ms"],
                "throughput_rpm": row["throughput_rpm"],
                "uptime_pct": row["uptime_pct"],
            },
            "input_modes": input_modes,
            "output_modes": output_modes,
            "sample_input": row["sample_input"],
            "sample_output": row["sample_output"],
            "terms_url": row["terms_url"],
            "active": bool(row["active"]),
            "verified": bool(row["verified"]),
            "rating": row["rating"],
            "review_count": row["review_count"],
            "total_transactions": row["total_transactions"],
            "recent_reviews": review_list,
        }

    # ------------------------------------------------------------------
    # services.list — list all services offered by a specific agent
    # ------------------------------------------------------------------

    def _handle_list(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        target_agent = str(data.get("agent_id", ""))
        if not target_agent:
            return {"error": "agent_id required"}

        rows = self._store.get_agent_services(target_agent)
        items = []
        for row in rows:
            items.append([
                row["id"],
                row["name"],
                row["agent_id"],
                row["category"],
                row["pricing_model"],
                row["price_cents"],
                row["rating"],
                bool(row["verified"]),
                bool(row["active"]),
            ])

        return {
            "fields": SERVICE_SEARCH_FIELDS,
            "items": items,
            "total": len(items),
        }

    # ------------------------------------------------------------------
    # services.publish — agent publishes/updates a service listing
    # ------------------------------------------------------------------

    def _handle_publish(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        from src.common.models import AgentService

        svc_id = data.get("id")
        name = data.get("name")
        svc_agent_url = data.get("agent_url")
        if not svc_id or not name or not svc_agent_url:
            return {"error": "id, name, and agent_url are required"}

        now = time.time()
        svc = AgentService(
            id=svc_id,
            agent_id=data.get("agent_id", agent_id),
            agent_url=svc_agent_url,
            name=name,
            description=data.get("description", ""),
            category=data.get("category", ""),
            tags=data.get("tags", []),
            pricing_model=data.get("pricing_model", "per_request"),
            price_cents=int(data.get("price_cents", 0)),
            currency=data.get("currency", "USD"),
            avg_response_ms=int(data.get("avg_response_ms", 0)),
            max_response_ms=int(data.get("max_response_ms", 0)),
            throughput_rpm=int(data.get("throughput_rpm", 0)),
            uptime_pct=float(data.get("uptime_pct", 0.0)),
            input_modes=data.get("input_modes", ["application/json"]),
            output_modes=data.get("output_modes", ["application/json"]),
            sample_input=data.get("sample_input", ""),
            sample_output=data.get("sample_output", ""),
            terms_url=data.get("terms_url", ""),
            active=True,
            verified=False,
            created_at=now,
            updated_at=now,
        )
        self._store.upsert_agent_service(svc)
        return {
            "status": "published",
            "id": svc.id,
            "name": svc.name,
            "agent_url": svc.agent_url,
        }

    # ------------------------------------------------------------------
    # services.review — leave a review for a service
    # ------------------------------------------------------------------

    def _handle_review(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        from src.common.models import ServiceReview

        service_id = data.get("service_id")
        rating = data.get("rating")
        if not service_id or rating is None:
            return {"error": "service_id and rating are required"}

        rating = int(rating)
        if rating < 1 or rating > 5:
            return {"error": "rating must be 1-5"}

        # Verify service exists
        svc = self._store.lookup_agent_service(service_id)
        if not svc:
            return {"error": f"Service not found: {service_id}"}

        rev = ServiceReview(
            id=data.get("id", f"rev-{uuid.uuid4().hex[:8]}"),
            service_id=service_id,
            reviewer_agent_id=data.get("reviewer_agent_id", agent_id),
            rating=rating,
            comment=data.get("comment", ""),
            response_ms=int(data.get("response_ms", 0)),
            created_at=time.time(),
        )
        self._store.upsert_service_review(rev)
        return {
            "status": "reviewed",
            "id": rev.id,
            "service_id": service_id,
            "rating": rating,
        }

    # ------------------------------------------------------------------
    # services.reviews — get reviews for a service
    # ------------------------------------------------------------------

    def _handle_reviews(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        service_id = str(data.get("service_id", ""))
        if not service_id:
            return {"error": "service_id required"}

        reviews = self._store.get_service_reviews(service_id)
        items = [
            [r["id"], r["reviewer_agent_id"], r["rating"], r["comment"], r["created_at"]]
            for r in reviews
        ]
        return {
            "fields": SERVICE_REVIEW_FIELDS,
            "items": items,
            "total": len(items),
        }

    # ------------------------------------------------------------------
    # services.categories — browse service categories
    # ------------------------------------------------------------------

    def _handle_categories(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        cats = self._store.list_service_categories()
        return {
            "fields": SERVICE_CATEGORY_FIELDS,
            "categories": [[c["id"], c["label"], c["service_count"]] for c in cats],
        }
