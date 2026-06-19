"""표시용 포맷 헬퍼 (순수 함수)."""

from __future__ import annotations

from typing import Optional


def format_time(seconds: Optional[float]) -> str:
    """초를 'H:MM:SS' 또는 'MM:SS'로 변환. None이면 '--:--'."""
    if seconds is None:
        return "--:--"
    total_seconds = int(seconds)
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def create_progress_bar(current: float, total: float, length: int = 12) -> str:
    """진행률 바 문자열을 만든다."""
    if total <= 0:
        return "▬" * length
    progress = min(current / total, 1.0)
    filled = int(progress * length)
    return "▬" * filled + "🔘" + "▬" * (length - filled - 1)


def truncate_string(text: str, max_length: int = 50, suffix: str = "...") -> str:
    """최대 길이를 넘으면 접미사를 붙여 자른다."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix
