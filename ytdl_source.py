"""
YouTube-DL 소스 모듈

yt-dlp를 사용하여 YouTube에서 오디오 정보를 추출합니다.
플레이리스트 배치 로딩을 지원합니다.
"""

import asyncio
import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional, Union

import yt_dlp

from config import YTDL_OPTIONS, PLAYLIST_BATCH_SIZE

# yt-dlp 버그 리포트 메시지 비활성화
yt_dlp.utils.bug_reports_message = lambda *args, **kwargs: ""

logger = logging.getLogger('discord.bot.ytdl')

# YTDL 작업용 스레드 풀 (최대 2개 동시 작업)
_ytdl_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ytdl")

# 프로그램 종료 시 스레드 풀 정리
atexit.register(_ytdl_executor.shutdown, wait=False)


class YTDLSource:
    """
    YouTube-DL 래퍼 클래스

    YouTube에서 오디오 정보를 추출하고 처리합니다.
    플레이리스트의 경우 배치 단위로 lazy loading을 지원합니다.
    """

    @staticmethod
    def _process_entry(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        YTDL 항목에서 필요한 필드만 추출합니다.

        Args:
            entry: yt-dlp에서 반환된 원본 항목 딕셔너리

        Returns:
            필요한 필드만 포함된 딕셔너리, 실패 시 None
        """
        if not entry:
            logger.debug("항목 처리 실패: entry가 None 또는 빈 값입니다")
            return None

        # 필수 키 존재 여부 확인
        required_keys = ("url", "title", "webpage_url")
        if not all(key in entry for key in required_keys):
            missing_keys = [k for k in required_keys if k not in entry]
            logger.warning(
                f"항목 처리 실패 - 필수 키 누락: {missing_keys}, "
                f"제목: '{entry.get('title', '알 수 없음')}'"
            )
            return None

        result = {
            "webpage_url": entry["webpage_url"],
            "title": entry["title"],
            "url": entry["url"],
            "duration": entry.get("duration")
        }

        logger.debug(
            f"항목 처리 완료 - 제목: '{result['title']}', "
            f"길이: {result['duration']}초"
        )
        return result

    @classmethod
    async def create_source(
        cls,
        query: str,
        *,
        loop: asyncio.AbstractEventLoop,
        get_next_batch: bool = False,
        playlist_start_index: int = 1
    ) -> Optional[Union[dict[str, Any], list[dict[str, Any]]]]:
        """
        YouTube에서 오디오 정보를 추출합니다.

        Args:
            query: YouTube URL 또는 검색어
            loop: 비동기 실행을 위한 이벤트 루프
            get_next_batch: 플레이리스트의 다음 배치를 가져올지 여부
            playlist_start_index: 플레이리스트 시작 인덱스

        Returns:
            - 단일 곡: {"type": "track", ...} 딕셔너리
            - 플레이리스트 첫 배치: {"type": "playlist", "entries": [...], ...} 딕셔너리
            - 플레이리스트 다음 배치: 항목 리스트
            - 실패 시: None
        """
        # 쿼리가 너무 길면 로그에서 잘라서 표시
        display_query = query[:80] + "..." if len(query) > 80 else query
        logger.info(
            f"YouTube 정보 추출 시작 - 쿼리: '{display_query}', "
            f"배치 로딩: {get_next_batch}, 시작 인덱스: {playlist_start_index}"
        )

        # 옵션 복사 및 설정
        opts = YTDL_OPTIONS.copy()
        is_search = not query.startswith(("http://", "https://"))

        if is_search:
            logger.debug(f"검색 모드로 처리 - 검색어: '{query}'")
        else:
            logger.debug(f"URL 모드로 처리 - URL: '{display_query}'")

        # 플레이리스트 범위 설정
        if get_next_batch:
            end_index = playlist_start_index + PLAYLIST_BATCH_SIZE - 1
            opts['playlist_items'] = f"{playlist_start_index}-{end_index}"
            logger.debug(
                f"플레이리스트 다음 배치 로딩 설정 - "
                f"범위: {playlist_start_index}~{end_index}"
            )
        else:
            opts['playlist_items'] = f"1-{PLAYLIST_BATCH_SIZE}"
            logger.debug(f"플레이리스트 초기 배치 설정 - 범위: 1~{PLAYLIST_BATCH_SIZE}")

        # yt-dlp로 정보 추출
        try:
            logger.debug("yt-dlp 인스턴스 생성 중...")
            ytdl = yt_dlp.YoutubeDL(opts)

            logger.debug(f"extract_info 호출 시작 - 쿼리: '{display_query}'")
            data = await loop.run_in_executor(
                _ytdl_executor,
                lambda: ytdl.extract_info(query, download=False)
            )
            logger.debug(f"extract_info 완료 - 데이터 수신: {data is not None}")

        except yt_dlp.utils.DownloadError as e:
            logger.warning(f"yt-dlp 다운로드 오류 - 쿼리: '{display_query}', 오류: {e}")
            raise
        except Exception as e:
            logger.error(
                f"yt-dlp 예기치 않은 오류 - 쿼리: '{display_query}', 오류: {e}",
                exc_info=True
            )
            raise

        if data is None:
            logger.warning(f"yt-dlp에서 데이터를 받지 못함 - 쿼리: '{display_query}'")
            return None

        # 결과 타입 로깅
        has_entries = "entries" in data
        has_url = "url" in data
        data_type = data.get('_type', 'unknown')
        logger.debug(
            f"yt-dlp 결과 분석 - entries 존재: {has_entries}, "
            f"url 존재: {has_url}, 타입: {data_type}"
        )

        # 검색 결과 처리 (첫 번째 결과만 반환)
        if not get_next_batch and is_search and "entries" in data:
            entries = data["entries"]
            logger.debug(f"검색 결과 처리 - 총 {len(entries) if entries else 0}개 항목")

            processed = [cls._process_entry(e) for e in entries if e]
            valid_entries = [e for e in processed if e]
            logger.debug(f"검색 결과 중 유효한 항목: {len(valid_entries)}개")

            if valid_entries:
                result = valid_entries[0]
                result["type"] = "track"
                logger.info(f"검색 결과 반환 - 제목: '{result['title']}'")
                return result

            logger.warning(f"검색 결과에서 유효한 항목을 찾지 못함 - 검색어: '{query}'")
            return None

        # 플레이리스트 처리
        if "entries" in data:
            playlist_title = data.get('title', '알 수 없는 플레이리스트')
            original_url = data.get('webpage_url') or data.get('original_url') or query
            entries = data["entries"]

            logger.info(
                f"플레이리스트 처리 시작 - 제목: '{playlist_title}', "
                f"항목 수: {len(entries) if entries else 0}개"
            )

            # 각 항목 처리
            processed = [cls._process_entry(e) for e in entries if e]
            valid_entries = [e for e in processed if e]

            logger.debug(
                f"플레이리스트 항목 처리 완료 - "
                f"전체: {len(entries) if entries else 0}개, "
                f"유효: {len(valid_entries)}개"
            )

            if not valid_entries:
                logger.warning(
                    f"플레이리스트에서 유효한 항목을 찾지 못함 - "
                    f"제목: '{playlist_title}', 범위: {opts.get('playlist_items')}"
                )
                return [] if get_next_batch else None

            # 배치 로딩인 경우 리스트만 반환
            if get_next_batch:
                logger.info(
                    f"플레이리스트 배치 로딩 완료 - 제목: '{playlist_title}', "
                    f"로드된 항목: {len(valid_entries)}개"
                )
                return valid_entries

            # 첫 번째 배치인 경우 메타데이터와 함께 반환
            next_start = playlist_start_index + len(valid_entries)
            logger.info(
                f"플레이리스트 초기 로딩 완료 - 제목: '{playlist_title}', "
                f"로드된 항목: {len(valid_entries)}개, 다음 시작 인덱스: {next_start}"
            )
            return {
                "type": "playlist",
                "original_url": original_url,
                "title": playlist_title,
                "entries": valid_entries,
                "next_start_index": next_start
            }

        # 단일 곡 처리
        if "url" in data:
            result = cls._process_entry(data)
            if result:
                result["type"] = "track"
                logger.info(f"단일 곡 정보 추출 완료 - 제목: '{result['title']}'")
                return result

            logger.warning(f"단일 곡 정보 처리 실패 - 쿼리: '{display_query}'")
            return None

        logger.warning(
            f"예상치 못한 yt-dlp 결과 형식 - 쿼리: '{display_query}', "
            f"키 목록: {list(data.keys())}"
        )
        return None
