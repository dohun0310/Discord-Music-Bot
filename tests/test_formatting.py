from discord_music_bot.ui.formatting import (
    create_progress_bar,
    format_time,
    truncate_string,
)


def test_format_time_none():
    assert format_time(None) == "--:--"


def test_format_time_minutes_seconds():
    assert format_time(75) == "01:15"


def test_format_time_hours():
    assert format_time(3661) == "1:01:01"


def test_progress_bar_zero_total():
    assert create_progress_bar(0, 0, 10) == "▬" * 10


def test_progress_bar_midpoint_has_head():
    bar = create_progress_bar(5, 10, 10)
    assert "🔘" in bar
    assert len(bar.replace("🔘", "X")) == 10


def test_truncate_short_unchanged():
    assert truncate_string("abc", 10) == "abc"


def test_truncate_long_adds_suffix():
    out = truncate_string("abcdefghij", 5)
    assert out.endswith("...")
    assert len(out) == 5
