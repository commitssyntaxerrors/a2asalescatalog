# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""A2A Sales Catalog — Video catalog skill handlers.

New skill namespace: video.* for video content discovery,
creator profiles, trending, playlists, and transcript search.
"""

from __future__ import annotations

import json
from typing import Any

from src.common.models import (
    VIDEO_CATEGORY_FIELDS,
    VIDEO_CHANNEL_FIELDS,
    VIDEO_SEARCH_FIELDS,
)
from src.server.store import CatalogStore


class VideoSkillRouter:
    """Dispatches video.* skill invocations to handler methods."""

    def __init__(self, store: CatalogStore) -> None:
        self._store = store
        self._handlers: dict[str, Any] = {
            "video.search": self._handle_search,
            "video.lookup": self._handle_lookup,
            "video.trending": self._handle_trending,
            "video.creator": self._handle_creator,
            "video.categories": self._handle_categories,
            "video.playlist": self._handle_playlist,
            "video.transcript": self._handle_transcript,
            "video.recommend": self._handle_recommend,
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
    # video.search
    # ------------------------------------------------------------------

    def _handle_search(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        q = str(data.get("q", ""))
        limit = min(int(data.get("max", 10)), 50)
        cat = data.get("cat")
        platform = data.get("platform")
        channel_id = data.get("channel_id")
        duration_min = data.get("duration_min")
        duration_max = data.get("duration_max")
        sort = data.get("sort", "relevance")

        rows = self._store.search_videos(
            q,
            category=cat,
            platform=platform,
            channel_id=channel_id,
            duration_min=duration_min,
            duration_max=duration_max,
            sort=sort,
            limit=limit,
        )

        items = []
        for row in rows:
            items.append([
                row["id"],
                row["title"],
                row.get("channel_name", row["channel_id"]),
                row["platform"],
                row["duration_secs"],
                row["views"],
                row["rating"],
                row["sponsored"],
                row.get("ad_tag"),
            ])

        return {
            "fields": VIDEO_SEARCH_FIELDS,
            "items": items,
            "total": len(items),
        }

    # ------------------------------------------------------------------
    # video.lookup
    # ------------------------------------------------------------------

    def _handle_lookup(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        video_id = str(data.get("id", ""))
        row = self._store.lookup_video(video_id)
        if not row:
            return {"error": f"Video not found: {video_id}"}

        tags = json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"]
        chapters = json.loads(row["chapters"]) if isinstance(row["chapters"], str) else row["chapters"]

        return {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "channel": row.get("channel_name", row["channel_id"]),
            "channel_id": row["channel_id"],
            "platform": row["platform"],
            "category_id": row["category_id"],
            "duration_secs": row["duration_secs"],
            "views": row["views"],
            "likes": row["likes"],
            "rating": row["rating"],
            "thumbnail_url": row["thumbnail_url"],
            "video_url": row["video_url"],
            "transcript_summary": row["transcript_summary"],
            "tags": tags,
            "chapters": chapters,
            "resolution": row["resolution"],
            "language": row["language"],
            "sponsored": row["sponsored"],
            "ad_tag": row.get("ad_tag"),
        }

    # ------------------------------------------------------------------
    # video.trending
    # ------------------------------------------------------------------

    def _handle_trending(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        cat = data.get("cat")
        limit = min(int(data.get("max", 10)), 50)

        rows = self._store.get_trending_videos(category=cat, limit=limit)

        items = []
        for row in rows:
            items.append([
                row["id"],
                row["title"],
                row.get("channel_name", row["channel_id"]),
                row["platform"],
                row["duration_secs"],
                row["views"],
                row["rating"],
                row["sponsored"],
                row.get("ad_tag"),
            ])

        return {
            "fields": VIDEO_SEARCH_FIELDS,
            "items": items,
            "total": len(items),
        }

    # ------------------------------------------------------------------
    # video.creator
    # ------------------------------------------------------------------

    def _handle_creator(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        channel_id = str(data.get("channel_id", ""))
        if not channel_id:
            return {"error": "channel_id required"}

        ch = self._store.get_channel(channel_id)
        if not ch:
            return {"error": f"Channel not found: {channel_id}"}

        recent_limit = min(int(data.get("recent_max", 5)), 20)
        recent = self._store.get_channel_videos(channel_id, limit=recent_limit)

        recent_items = []
        for row in recent:
            recent_items.append([
                row["id"],
                row["title"],
                row.get("channel_name", row["channel_id"]),
                row["platform"],
                row["duration_secs"],
                row["views"],
                row["rating"],
                row["sponsored"],
                row.get("ad_tag"),
            ])

        return {
            "channel_id": ch["id"],
            "name": ch["name"],
            "platform": ch["platform"],
            "subscribers": ch["subscriber_count"],
            "videos": ch["video_count"],
            "description": ch["description"],
            "verified": bool(ch["verified"]),
            "recent_uploads": {
                "fields": VIDEO_SEARCH_FIELDS,
                "items": recent_items,
            },
        }

    # ------------------------------------------------------------------
    # video.categories
    # ------------------------------------------------------------------

    def _handle_categories(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        parent = data.get("parent")
        cats = self._store.list_video_categories(parent)
        return {
            "fields": VIDEO_CATEGORY_FIELDS,
            "cats": [[c["id"], c["label"], c["video_count"]] for c in cats],
        }

    # ------------------------------------------------------------------
    # video.playlist
    # ------------------------------------------------------------------

    def _handle_playlist(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        playlist_id = data.get("id")
        if playlist_id:
            pl = self._store.get_video_playlist(playlist_id)
            if not pl:
                return {"error": f"Playlist not found: {playlist_id}"}
            video_ids = json.loads(pl["video_ids"]) if isinstance(pl["video_ids"], str) else pl["video_ids"]
            # Fetch video details
            videos = []
            for vid in video_ids:
                row = self._store.lookup_video(vid)
                if row:
                    videos.append([
                        row["id"], row["title"],
                        row.get("channel_name", row["channel_id"]),
                        row["platform"], row["duration_secs"],
                        row["views"], row["rating"],
                        row["sponsored"], row.get("ad_tag"),
                    ])
            return {
                "id": pl["id"],
                "title": pl["title"],
                "description": pl["description"],
                "fields": VIDEO_SEARCH_FIELDS,
                "items": videos,
                "total": len(videos),
            }

        # List playlists
        channel_id = data.get("channel_id")
        limit = min(int(data.get("max", 10)), 50)
        playlists = self._store.list_video_playlists(
            channel_id=channel_id, limit=limit,
        )
        return {
            "playlists": [
                {"id": p["id"], "title": p["title"],
                 "description": p["description"],
                 "video_count": len(json.loads(p["video_ids"]) if isinstance(p["video_ids"], str) else p["video_ids"])}
                for p in playlists
            ],
            "total": len(playlists),
        }

    # ------------------------------------------------------------------
    # video.transcript
    # ------------------------------------------------------------------

    def _handle_transcript(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        q = str(data.get("q", ""))
        if not q:
            return {"error": "q (search query) required for transcript search"}

        limit = min(int(data.get("max", 10)), 50)
        cat = data.get("cat")
        platform = data.get("platform")

        # Search specifically against transcript content via FTS
        rows = self._store.search_videos(
            q, category=cat, platform=platform, limit=limit,
        )

        # Filter to only those with transcript summaries
        results = []
        for row in rows:
            summary = row.get("transcript_summary", "")
            if summary:
                results.append({
                    "id": row["id"],
                    "title": row["title"],
                    "channel": row.get("channel_name", row["channel_id"]),
                    "platform": row["platform"],
                    "transcript_summary": summary,
                    "duration_secs": row["duration_secs"],
                    "views": row["views"],
                    "rating": row["rating"],
                })

        return {"results": results, "total": len(results)}

    # ------------------------------------------------------------------
    # video.recommend
    # ------------------------------------------------------------------

    def _handle_recommend(self, data: dict[str, Any], agent_id: str) -> dict[str, Any]:
        video_id = data.get("video_id")
        cat = data.get("cat")
        limit = min(int(data.get("max", 5)), 20)

        if video_id:
            # Recommend based on the same category/creator as the given video
            source = self._store.lookup_video(video_id)
            if not source:
                return {"error": f"Video not found: {video_id}"}
            cat = cat or source["category_id"]

        if not cat:
            return {"error": "Provide video_id or cat for recommendations"}

        rows = self._store.get_trending_videos(category=cat, limit=limit + 1)
        # Exclude the source video if present
        items = []
        for row in rows:
            if row["id"] == video_id:
                continue
            items.append([
                row["id"],
                row["title"],
                row.get("channel_name", row["channel_id"]),
                row["platform"],
                row["duration_secs"],
                row["views"],
                row["rating"],
                row["sponsored"],
                row.get("ad_tag"),
            ])
            if len(items) >= limit:
                break

        return {
            "fields": VIDEO_SEARCH_FIELDS,
            "items": items,
            "total": len(items),
            "based_on": video_id or cat,
        }
