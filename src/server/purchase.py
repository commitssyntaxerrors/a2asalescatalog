# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Purchase completion protocol — close the sale agent-to-agent.

Handles order creation with tokenized payment and shipping,
enforcing price locks from negotiation sessions.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from src.common.models import Order
from src.server.store import CatalogStore

# Minimum reputation to purchase
MIN_REPUTATION_PURCHASE = 20


class PurchaseEngine:
    """Processes agent purchase requests."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def purchase(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Execute a purchase."""
        item_id = data.get("item_id", "")
        quantity = max(1, int(data.get("quantity", 1)))
        negotiate_session_id = data.get("negotiate_session_id")
        payment_token = data.get("payment_token", "")
        shipping = data.get("shipping", {})

        # Validate agent
        profile = self._store.get_or_create_agent(agent_id)
        if profile["reputation"] < MIN_REPUTATION_PURCHASE:
            return {"error": f"Reputation {profile['reputation']:.0f} below minimum {MIN_REPUTATION_PURCHASE}"}

        # Validate item
        item = self._store.lookup(item_id)
        if not item:
            return {"error": f"Item not found: {item_id}"}

        # Determine price
        unit_price = item["price_cents"]
        if negotiate_session_id:
            sess = self._store.get_negotiation(negotiate_session_id)
            if not sess:
                return {"error": f"Negotiation session not found: {negotiate_session_id}"}
            if sess["agent_id"] != agent_id:
                return {"error": "Negotiation session belongs to a different agent"}
            if sess["status"] != "accepted":
                return {"error": f"Negotiation not accepted (status: {sess['status']})"}
            if sess["item_id"] != item_id:
                return {"error": "Negotiation session is for a different item"}
            unit_price = sess["current_price_cents"]
        elif item.get("trusted_price_cents") and profile["reputation"] >= (item.get("reputation_threshold") or 0):
            unit_price = item["trusted_price_cents"]

        # Validate payment token (stub — in production, delegate to payment gateway)
        if not payment_token:
            return {"error": "payment_token is required"}

        total = unit_price * quantity
        order_id = f"ord-{uuid.uuid4().hex[:8]}"
        shipping_method = shipping.get("method") if isinstance(shipping, dict) else None

        order = Order(
            order_id=order_id,
            agent_id=agent_id,
            item_id=item_id,
            vendor_id=item["vendor_id"],
            quantity=quantity,
            unit_price_cents=unit_price,
            total_cents=total,
            negotiate_session_id=negotiate_session_id,
            payment_status="captured",
            shipping_method=shipping_method,
            status="confirmed",
            created_at=time.time(),
        )
        self._store.create_order(order)

        # Boost reputation for completed purchase
        self._store.update_agent_reputation(agent_id, 5.0)
        self._store.update_agent_stats(agent_id, purchases=1)

        return {
            "order_id": order_id,
            "status": "confirmed",
            "item_id": item_id,
            "quantity": quantity,
            "unit_price_cents": unit_price,
            "total_cents": total,
            "payment_status": "captured",
        }
