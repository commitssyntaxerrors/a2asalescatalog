# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Negotiation protocol — programmatic price haggling between agents.

Implements the first structured negotiation protocol between AI agents
for e-commerce. Agents submit offers, the catalog counters on behalf
of vendors using configurable floor prices and auto-accept thresholds.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from src.common.models import NegotiationSession
from src.server.store import CatalogStore

# Negotiation rules
MAX_ROUNDS = 5
MIN_OFFER_RATIO = 0.60   # min offer = 60% of list price
AUTO_ACCEPT_RATIO = 0.05  # within 5% of floor → auto-accept
MIN_REPUTATION = 40       # minimum reputation to negotiate
SESSION_TTL = 3600         # 1 hour


class NegotiationEngine:
    """Handles price negotiation sessions between agents and vendor floors."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def negotiate(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Process a negotiation request — new session or continuation."""
        item_id = data.get("item_id", "")
        offer_cents = int(data.get("offer_cents", 0))
        session_id = data.get("session_id")

        # Premium negotiation params (injected by SkillRouter)
        pp = data.pop("_premium_params", None) or {}
        max_rounds = int(pp.get("max_rounds", MAX_ROUNDS))
        floor_ratio = float(pp.get("floor_ratio", 0.70))
        is_premium = bool(pp.get("premium_agent", False))

        # Check agent reputation
        profile = self._store.get_or_create_agent(agent_id)
        if profile["reputation"] < MIN_REPUTATION:
            return {"error": f"Reputation {profile['reputation']:.0f} below minimum {MIN_REPUTATION} for negotiation"}

        # Lookup item
        item = self._store.lookup(item_id)
        if not item:
            return {"error": f"Item not found: {item_id}"}

        list_price = item["price_cents"]
        floor = item.get("vendor_floor_cents") or int(list_price * floor_ratio)

        # Validate offer
        min_offer_ratio = pp.get("min_offer_ratio", MIN_OFFER_RATIO)
        min_offer = int(list_price * min_offer_ratio)
        if offer_cents < min_offer:
            return {"error": f"Offer {offer_cents} below minimum {min_offer} ({int(min_offer_ratio*100)}% of list price)"}

        if session_id:
            return self._continue_session(session_id, agent_id, offer_cents,
                                          floor, list_price, max_rounds, is_premium)
        else:
            return self._new_session(agent_id, item_id, offer_cents,
                                     floor, list_price, max_rounds, is_premium)

    def _new_session(self, agent_id: str, item_id: str, offer_cents: int,
                     floor: int, list_price: int,
                     max_rounds: int = MAX_ROUNDS,
                     is_premium: bool = False) -> dict[str, Any]:
        session_id = f"neg-{uuid.uuid4().hex[:8]}"
        now = time.time()

        # Decide: accept or counter
        status, counter = self._decide(offer_cents, floor, list_price, rounds_used=0)

        session = NegotiationSession(
            session_id=session_id,
            agent_id=agent_id,
            item_id=item_id,
            status=status,
            agent_offer_cents=offer_cents,
            vendor_floor_cents=floor,
            current_price_cents=counter if status == "counter" else offer_cents,
            rounds_used=1,
            max_rounds=max_rounds,
            expires_at=now + SESSION_TTL,
            created_at=now,
        )
        self._store.create_negotiation(session)

        resp = self._format_response(session_id, status, counter, offer_cents,
                                     list_price, max_rounds - 1)
        if is_premium:
            resp["premium_agent"] = True
        return resp

    def _continue_session(self, session_id: str, agent_id: str,
                          offer_cents: int, floor: int, list_price: int,
                          max_rounds: int = MAX_ROUNDS,
                          is_premium: bool = False) -> dict[str, Any]:
        sess = self._store.get_negotiation(session_id)
        if not sess:
            return {"error": f"Session not found: {session_id}"}
        if sess["agent_id"] != agent_id:
            return {"error": "Session belongs to a different agent"}
        if sess["status"] in ("accepted", "rejected", "expired"):
            return {"error": f"Session already {sess['status']}"}
        if time.time() > sess["expires_at"]:
            self._store.update_negotiation(session_id, status="expired")
            return {"error": "Session expired"}
        if sess["rounds_used"] >= sess["max_rounds"]:
            self._store.update_negotiation(session_id, status="rejected")
            return {"error": "Maximum negotiation rounds exceeded"}

        rounds_used = sess["rounds_used"] + 1
        status, counter = self._decide(offer_cents, floor, list_price, rounds_used=rounds_used)
        rounds_left = sess["max_rounds"] - rounds_used

        self._store.update_negotiation(
            session_id,
            status=status,
            agent_offer_cents=offer_cents,
            current_price_cents=counter if status == "counter" else offer_cents,
            rounds_used=rounds_used,
        )

        resp = self._format_response(session_id, status, counter, offer_cents,
                                     list_price, rounds_left)
        if is_premium:
            resp["premium_agent"] = True
        return resp

    def _decide(self, offer: int, floor: int, list_price: int,
                rounds_used: int) -> tuple[str, int]:
        """Decide whether to accept, counter, or reject."""
        if offer >= floor:
            return "accepted", offer
        # Auto-accept if within threshold of floor
        if abs(offer - floor) <= floor * AUTO_ACCEPT_RATIO:
            return "accepted", offer
        # Counter: split the difference, favoring vendor as rounds increase
        vendor_weight = 0.5 + (rounds_used * 0.1)  # progressively less generous
        counter = int(offer + (floor - offer) * min(vendor_weight, 0.9))
        if counter >= list_price:
            counter = floor  # never counter above list price
        return "counter", counter

    def _format_response(self, session_id: str, status: str, counter: int,
                         offer: int, list_price: int, rounds_left: int) -> dict[str, Any]:
        resp: dict[str, Any] = {
            "session_id": session_id,
            "status": status,
            "your_offer_cents": offer,
            "list_price_cents": list_price,
            "rounds_left": rounds_left,
        }
        if status == "counter":
            resp["their_offer_cents"] = counter
        elif status == "accepted":
            resp["agreed_price_cents"] = offer
        return resp
