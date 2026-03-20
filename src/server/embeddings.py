# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Semantic embeddings index — vector representations for catalog items.

Each item has a pre-computed embedding vector. Consumer agents can request
embeddings alongside search results to perform local re-ranking, clustering,
or recommendation without extra round-trips.

MVP uses a deterministic hash-based pseudo-embedding. Production would
plug in a real model (e.g. sentence-transformers, OpenAI, Cohere).
"""

from __future__ import annotations

import base64
import hashlib
import struct
from typing import Any

from src.server.store import CatalogStore

EMBEDDING_DIM = 128


def _hash_embedding(text: str, dim: int = EMBEDDING_DIM) -> str:
    """Generate a deterministic pseudo-embedding from text via SHA-512 hashing.

    Not a real semantic embedding — used for MVP wire format testing.
    Production replaces this with a real model call.
    """
    h = hashlib.sha512(text.encode()).digest()
    # Expand hash to fill dim floats
    floats = []
    for i in range(dim):
        byte_val = h[i % len(h)]
        floats.append((byte_val / 255.0) * 2 - 1)  # normalize to [-1, 1]
    raw = struct.pack(f"{dim}f", *floats)
    return base64.b64encode(raw).decode()


class EmbeddingIndex:
    """Manages item embeddings and query embedding generation."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store

    def get_item_embeddings(self, item_ids: list[str]) -> list[list]:
        """Get embeddings for specific items. Returns [[id, emb_b64], ...]."""
        results = []
        for iid in item_ids:
            item = self._store.lookup(iid)
            if not item:
                continue
            emb = item.get("embedding", "")
            if not emb:
                # Generate on-the-fly for MVP
                emb = _hash_embedding(f"{item['name']} {item['desc']}")
            results.append([iid, emb])
        return results

    def get_query_embedding(self, query: str) -> str:
        """Generate an embedding for a free-text query."""
        return _hash_embedding(query)

    def embed(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle the catalog.embed skill request."""
        ids = data.get("ids", [])
        query = data.get("query", "")

        resp: dict[str, Any] = {"dim": EMBEDDING_DIM}
        if query:
            resp["query_emb"] = self.get_query_embedding(query)
        if ids:
            resp["items"] = self.get_item_embeddings(ids)
        return resp
