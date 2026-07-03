from app.bot import build_bot
from app.config import Settings


async def test_build_bot_assembles_cogs_via_setup_hook():
    bot = build_bot(Settings(bot_token="토큰", log_level="INFO"))
    try:
        await bot.setup_hook()  # cog 등록 + sync 시도(로그인 전이라 실패해도 예외 없음)
        names = {type(c).__name__ for c in bot.cogs.values()}
        assert names == {"PlaybackCog", "QueueCog", "SettingsCog"}
    finally:
        await bot.close()
