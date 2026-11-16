import discord
import pytest

import app.__main__ as entry
from app.config import Settings


class _Bot:
    def __init__(self, error=None):
        self.error = error

    def run(self, token, log_handler=None):
        if self.error:
            raise self.error


def _patch(monkeypatch, *, token, bot):
    monkeypatch.setattr(
        entry.Settings, "from_env",
        classmethod(lambda cls: Settings(bot_token=token, log_level="INFO")),
    )
    monkeypatch.setattr(entry, "configure_logging", lambda level: None)
    monkeypatch.setattr(entry, "build_bot", lambda settings: bot)


def test_missing_token_exits_with_error(monkeypatch):
    _patch(monkeypatch, token=None, bot=_Bot())
    with pytest.raises(SystemExit) as exc:
        entry.main()
    assert exc.value.code == 1


@pytest.mark.parametrize("error", [discord.LoginFailure("bad"), RuntimeError("boom")])
def test_run_failure_exits_with_error(monkeypatch, error):
    _patch(monkeypatch, token="토큰", bot=_Bot(error))
    with pytest.raises(SystemExit) as exc:
        entry.main()
    assert exc.value.code == 1


def test_normal_shutdown_returns(monkeypatch):
    _patch(monkeypatch, token="토큰", bot=_Bot())
    entry.main()  # 정상 종료는 예외 없이 반환
