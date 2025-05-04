import asyncio
import yt_dlp
import logging
from typing import Optional, Union, List
from config import YTDL_OPTIONS

yt_dlp.utils.bug_reports_message = lambda: ""
ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
logger = logging.getLogger(__name__)

class YTDLSource:
    @classmethod
    async def create_source(cls, query: str, *, loop: asyncio.AbstractEventLoop, get_next_batch=False, playlist_start_index=1):
        custom_ytdl_opts = YTDL_OPTIONS.copy()
        if not get_next_batch:
            custom_ytdl_opts['extract_flat'] = True

        local_ytdl = yt_dlp.YoutubeDL(custom_ytdl_opts)
        data = await loop.run_in_executor(None, lambda: local_ytdl.extract_info(query, download=False))

        if data is None:
            return None

        if "entries" in data:
            if not get_next_batch:
                return {
                    "type": "playlist",
                    "original_url": data.get('webpage_url') or query,
                    "title": data.get('title', 'Unknown Playlist'),
                    "entries": cls._process_playlist(data["entries"]),
                    "next_start_index": playlist_start_index + len(data["entries"])
                }
            else:
                return cls._process_playlist(data["entries"])
        else:
            return cls._process_single(data)

    @staticmethod
    def _process_playlist(entries: List[dict]) -> List[dict]:
        valid_entries = [entry for entry in entries if entry and all(k in entry for k in ("url", "title", "webpage_url"))]
        return [
            {
                "webpage_url": entry["webpage_url"],
                "title": entry["title"],
                "url": entry["url"],
                "duration": entry.get("duration")
            } for entry in valid_entries
        ] if valid_entries else []

    @staticmethod
    def _process_single(data: dict) -> dict:
        return {
            "webpage_url": data["webpage_url"],
            "title": data["title"],
            "url": data["url"],
            "duration": data.get("duration")
        }