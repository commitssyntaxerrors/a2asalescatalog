# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Affiliate / referral program — agents earn commission for referrals.

Agents generate unique referral codes. When another agent purchases
through a referral, the referring agent earns a commission. The first
agent-earns-commission model in autonomous commerce.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from src.common.models import AffiliateLink
from src.server.store import CatalogStore

_DEFAULT_COMMISSION_BPS = 500  # 5% default


class AffiliateEngine:
    """Manages affiliate referral codes and commission tracking."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def create_referral(self, agent_id: str, vendor_id: str,
                        commission_bps: int = _DEFAULT_COMMISSION_BPS) -> dict[str, Any]:
        """Generate a referral code for an agent to share."""
        code = f"ref-{uuid.uuid4().hex[:8]}"
        link = AffiliateLink(
            referral_code=code,
            referring_agent_id=agent_id,
            vendor_id=vendor_id,
            commission_bps=commission_bps,
            created_at=time.time(),
        )
        self._store.upsert_affiliate(link)
        return {
            "referral_code": code,
            "vendor_id": vendor_id,
            "commission_pct": round(commission_bps / 100, 2),
        }

    def record_sale(self, referral_code: str, sale_cents: int) -> dict[str, Any] | None:
        """Record a sale attributed to a referral code."""
        link = self._store.get_affiliate(referral_code)
        if not link or not link["active"]:
            return None
        commission = int(sale_cents * link["commission_bps"] / 10000)
        self._store.record_affiliate_referral(referral_code, commission)
        return {
            "referral_code": referral_code,
            "sale_cents": sale_cents,
            "commission_cents": commission,
            "referring_agent_id": link["referring_agent_id"],
        }

    def handle(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Handle the catalog.affiliate skill."""
        if not agent_id:
            return {"error": "Authentication required"}

        action = data.get("action", "status")

        if action == "create":
            vendor_id = data.get("vendor_id", "")
            if not vendor_id:
                return {"error": "vendor_id required to create referral"}
            return self.create_referral(agent_id, vendor_id)

        # Default: return agent's affiliate status
        links = self._store.get_agent_affiliates(agent_id)
        return {
            "agent_id": agent_id,
            "referrals": [
                {
                    "referral_code": l["referral_code"],
                    "vendor_id": l["vendor_id"],
                    "commission_pct": round(l["commission_bps"] / 100, 2),
                    "total_referrals": l["total_referrals"],
                    "total_earned_cents": l["total_earned_cents"],
                }
                for l in links
            ],
            "count": len(links),
        }
