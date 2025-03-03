import asyncio
import yt_dlp
from config import YTDL_OPTIONS

yt_dlp.utils.bug_reports_message = lambda: ""

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class YTDLSource:
    @classmethod
    async def create_source(cls, query: str, *, loop: asyncio.AbstractEventLoop):
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        if "entries" in data:
            data = data["entries"][0]
        return {
            "webpage_url": data["webpage_url"],
            "title": data["title"],
            "url": data["url"]
        }