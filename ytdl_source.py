import asyncio
import atexit
import yt_dlp
import logging
from typing import Optional, Union, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
from config import YTDL_OPTIONS

yt_dlp.utils.bug_reports_message = lambda *args, **kwargs: ""
logger = logging.getLogger('discord.bot.ytdl')
PLAYLIST_BATCH_SIZE = 10

_ytdl_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ytdl")

# 프로그램 종료 시 executor 정리
atexit.register(_ytdl_executor.shutdown, wait=False)

class YTDLSource:
    @staticmethod
    def _process_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not entry:
            return None

        if not all(key in entry for key in ("url", "title", "webpage_url")):
            logger.warning(f"항목 처리 중 필수 키 누락: title='{entry.get('title', 'N/A')}', id='{entry.get('id', 'N/A')}'")
            return None

        return {
            "webpage_url": entry["webpage_url"],
            "title": entry["title"],
            "url": entry["url"],
            "duration": entry.get("duration")
        }

    @classmethod
    async def create_source(
        cls,
        query: str,
        *,
        loop: asyncio.AbstractEventLoop,
        get_next_batch: bool = False,
        playlist_start_index: int = 1
    ) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
        current_opts = YTDL_OPTIONS.copy()
        is_search = not (query.startswith("http://") or query.startswith("https://"))

        if get_next_batch:
            playlist_end_index = playlist_start_index + PLAYLIST_BATCH_SIZE - 1
            current_opts['playlist_items'] = f"{playlist_start_index}-{playlist_end_index}"
            logger.debug(f"Lazy loading next batch: items {playlist_start_index}-{playlist_end_index}")
        else:
            current_opts['playlist_items'] = f"1-{PLAYLIST_BATCH_SIZE}"
            logger.debug(f"Initial fetch: items 1-{PLAYLIST_BATCH_SIZE} (if playlist)")

        try:
            local_ytdl = yt_dlp.YoutubeDL(current_opts)

            data = await loop.run_in_executor(
                _ytdl_executor,
                lambda: local_ytdl.extract_info(query, download=False)
            )
        except yt_dlp.utils.DownloadError as e:
            logger.warning(f"YTDL DownloadError for query '{query}': {e}")
            raise  # main.py에서 적절히 처리하도록 다시 던짐
        except Exception as e:
            logger.error(f"Unexpected error during YTDL extraction for query '{query}': {e}", exc_info=True)
            raise

        if data is None:
            logger.warning(f"No data returned from YTDL for query '{query}'")
            return None

        if not get_next_batch and is_search and "entries" in data:
            processed = [cls._process_entry(entry) for entry in data["entries"] if entry]
            valid = [e for e in processed if e]
            if valid:
                first = valid[0]
                logger.info(f"검색어 '{query}' 결과 처리: 첫 곡 반환 '{first['title']}'")
                first["type"] = "track"
                return first
            return None

        if "entries" in data:
            playlist_title = data.get('title', '알 수 없는 플레이리스트')
            original_url = data.get('webpage_url') or data.get('original_url') or query
            entries = data["entries"]

            processed_entries = [cls._process_entry(entry) for entry in entries if entry]
            valid_entries = [entry for entry in processed_entries if entry is not None]

            if not valid_entries:
                 logger.warning(f"플레이리스트 '{playlist_title}'에서 유효한 항목을 찾지 못함 (범위: {current_opts.get('playlist_items')}).")
                 return [] if get_next_batch else None

            if get_next_batch:
                logger.info(f"플레이리스트 '{playlist_title}' 다음 배치 로드 완료 ({len(valid_entries)}개 항목).")
                return valid_entries
            else:
                next_start = playlist_start_index + len(valid_entries)
                logger.info(f"플레이리스트 '{playlist_title}' 첫 배치 로드 완료 ({len(valid_entries)}개 항목), 다음 시작: {next_start}")
                return {
                    "type": "playlist",
                    "original_url": original_url,
                    "title": playlist_title,
                    "entries": valid_entries,
                    "next_start_index": next_start
                }
        elif "url" in data:
            processed_entry = cls._process_entry(data)
            if processed_entry:
                logger.info(f"단일 곡 정보 처리 완료: '{processed_entry['title']}'")
                processed_entry["type"] = "track"
                return processed_entry
            else:
                logger.warning(f"단일 곡 정보 처리 실패: query='{query}'")
                return None
        else:
            logger.warning(f"YTDL 결과 형식이 예상과 다름 (플레이리스트나 단일 곡 아님): query='{query}'")
            return None