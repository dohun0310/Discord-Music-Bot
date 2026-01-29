"""
봇 설정 모듈

환경 변수 및 각종 설정값을 관리합니다.
"""

import os
from typing import Optional

# 봇 설정
BOT_TOKEN: Optional[str] = os.getenv("BOT_TOKEN")

# 타임아웃 설정 (초 단위)
IDLE_TIMEOUT = 60  # 음성 채널에 혼자 남았을 때 대기 시간
QUEUE_TIMEOUT = 300  # 대기열이 비었을 때 대기 시간

# 대기열 설정
MAX_QUEUE_DISPLAY = 10  # 대기열 표시 최대 개수
LAZY_LOAD_THRESHOLD = 3  # 플레이리스트 자동 로딩 임계값
PLAYLIST_BATCH_SIZE = 10  # 플레이리스트 배치 로딩 크기

# yt-dlp 옵션
YTDL_OPTIONS = {
    "format": "bestaudio/best",  # 최고 음질 오디오 선택
    "outtmpl": "downloads/%(extractor)s-%(id)s-%(title)s.%(ext)s",  # 다운로드 경로 템플릿
    "restrictfilenames": True,  # 파일명에서 특수문자 제거
    "nocheckcertificate": True,  # SSL 인증서 검사 비활성화
    "ignoreerrors": True,  # 오류 발생 시 무시하고 계속 진행
    "logtostderr": False,  # stderr로 로그 출력 비활성화
    "quiet": True,  # 조용한 모드
    "no_warnings": True,  # 경고 메시지 비활성화
    "default_search": "auto",  # 자동 검색 모드
    "source_address": "0.0.0.0",  # 소스 주소 바인딩
    "extractor_args": {
        "youtube": {
            "player_client": ["android_vr"]  # YouTube 클라이언트 설정
        }
    }
}

# FFmpeg 옵션
FFMPEG_OPTIONS = {
    "before_options": "-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",  # 재연결 설정
    "options": "-vn -bufsize 64k"  # 비디오 스트림 제거, 버퍼 크기 설정
}
