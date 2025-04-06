import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN 환경변수가 설정되어 있지 않습니다.")

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "outtmpl": "downloads/%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0"
}

FFMPEG_OPTIONS = {
    "before_options": "-protocol_whitelist file,crypto,https,http,tcp,tls -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn"
}