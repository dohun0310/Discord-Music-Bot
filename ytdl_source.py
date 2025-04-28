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
    async def create_source(cls, query: str, *, loop: asyncio.AbstractEventLoop) -> Optional[Union[dict, List[dict]]]:
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        except yt_dlp.utils.DownloadError as e:
            logger.warning(f"YTDL download error for '{query}': {e}")
            if "Private video" in str(e):
                return None
            raise

        if "entries" in data:
            return cls._process_playlist(data["entries"])
        elif all(key in data for key in ("url", "title", "webpage_url")):
            return cls._process_single(data)
        logger.warning(f"No valid data returned for query '{query}': {data}")
        return None

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