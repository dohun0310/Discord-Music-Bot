import asyncio
import yt_dlp
from typing import Optional, Union, List
from config import YTDL_OPTIONS

yt_dlp.utils.bug_reports_message = lambda: ""

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class YTDLSource:
    @classmethod
    async def create_source(cls, query: str, *, loop: asyncio.AbstractEventLoop) -> Optional[Union[dict, List[dict]]]:
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        except yt_dlp.utils.DownloadError as e:
            print(f"Error extracting info for query '{query}': {e}")
            if "Private video" in str(e):
                return None
            raise

        if "entries" in data:
            entries = [entry for entry in data["entries"] if entry and all(key in entry for key in ("url", "title", "webpage_url"))]
            if entries:
                return [
                    {
                        "webpage_url": entry["webpage_url"],
                        "title": entry["title"],
                        "url": entry["url"]
                    } for entry in entries
                ]
        elif all(key in data for key in ("url", "title", "webpage_url")):
            return {
                "webpage_url": data["webpage_url"],
                "title": data["title"],
                "url": data["url"]
            }
        return None