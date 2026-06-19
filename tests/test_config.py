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


def test_from_env_overrides_log_level(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "abc")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert Settings.from_env().log_level == "DEBUG"
