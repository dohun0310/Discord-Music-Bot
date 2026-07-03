from app.config import Settings


def test_from_env_reads_token_and_defaults(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "abc")
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    s = Settings.from_env()
    assert s.bot_token == "abc"
    assert s.log_level == "INFO"
    assert s.default_volume == 0.5
    assert s.max_volume == 2.0
    assert s.queue_timeout == 300
    assert s.opus_bitrate == 128
    assert s.opus_signal_type == "music"
    assert s.stream_url_ttl == 14400
    assert s.max_consecutive_failures == 5


def test_from_env_overrides_log_level(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "abc")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert Settings.from_env().log_level == "DEBUG"


def test_default_tool_options_locations():
    from app.services.audio import DEFAULT_FFMPEG_OPTIONS
    from app.services.resolver import DEFAULT_YTDL_OPTIONS

    assert DEFAULT_YTDL_OPTIONS["format"] == "bestaudio/best"
    assert "outtmpl" not in DEFAULT_YTDL_OPTIONS  # 다운로드 안 하므로 불필요
    assert "-vn" in DEFAULT_FFMPEG_OPTIONS["options"]
