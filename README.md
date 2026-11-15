# 디스코드 뮤직 봇 프로젝트

이 저장소는 디스코드 서버에서 음악을 재생해주는 파이썬 봇 예시 프로젝트입니다. 주요 기능과 사용 방법을 아래에 정리했습니다.

---

## 프로젝트 개요

- 진입점: `python -m app` (하위 호환용 `main.py` shim 포함)
- 패키지: `app/`
  - `domain/` — Track 값 객체, TrackQueue, 반복/다음곡·실패 판정 정책 (순수 로직)
  - `services/` — yt-dlp 리졸버(만료 URL 재해석 포함), ffmpeg 소스 팩토리 (Protocol 기반)
  - `player/` — GuildPlayer(재생 오케스트레이션), PlaybackTimer, PlaylistAutoLoader,
    ChannelNotifier, PlayerRegistry(음성 이벤트 라우팅)
  - `ui/` — EmbedFactory, 색상/이모지 테마, 포맷 헬퍼
  - `cogs/` — 슬래시 명령 (재생/대기열/설정, 같은 음성 채널 사용자만 제어 가능)
  - `bot.py` — 의존성 조립(합성 루트), `config.py` — 환경 변수 기반 설정

## 테스트

```bash
pip install -r requirements-dev.txt
pytest
```

---

## 주요 기능

1. **음악 재생**:  
   - 유저가 명령어를 입력하면, YouTube에서 음원 정보를 가져와 재생합니다.  
   - 재생 중인 음악이 끝나면, 자동으로 다음 대기열의 음악을 재생합니다.

2. **재생 대기열 (Queue)**:  
   - 여러 곡을 순서대로 재생할 수 있도록 대기열을 관리합니다.  
   - `GuildPlayer` 클래스에서 대기열 로직과 재생 순서를 제어합니다.

3. **명령어**:  
   - `/재생 [제목 또는 URL]` : YouTube 검색어나 URL로 노래 또는 플레이리스트 재생  
   - `/스킵` : 현재 곡을 건너뛰고 다음 곡 재생  
   - `/정지` : 재생을 중지하고 대기열을 비운 뒤 음성 채널에서 퇴장  
   - `/일시정지` : 재생 일시정지  
   - `/재개` : 일시정지한 곡 다시 재생  
   - `/현재곡` : 현재 곡 정보와 진행 상황 확인  
   - `/대기열` : 대기열 목록 확인  
   - `/삭제 [순번]` : 대기열에서 지정한 순번의 곡 제거  
   - `/비우기` : 대기열 비우기  
   - `/셔플` : 대기열 섞기  
   - `/볼륨 [0-200]` : 볼륨 조절  
   - `/반복` : 반복 모드 변경 (꺼짐 → 전체 반복 → 한 곡 반복)
   - `/현재곡`, `/대기열`을 제외한 명령어는 봇과 같은 음성 채널에 있는 사용자만 사용할 수 있습니다.

---

## 설치 방법

1. **Python 버전**: Python 3.10 이상 (Docker 이미지는 `python:3.14-slim` 사용)  
2. **FFmpeg 설치**: 음원을 재생하려면 `ffmpeg`가 `PATH`에 있어야 합니다. (Docker 이미지에는 포함되어 있습니다.)
3. **의존성 설치**:  
   ```bash
   pip install -r requirements.txt
   ```  
4. **환경 변수 설정**:  
   - `BOT_TOKEN` (필수): 디스코드 봇 토큰 (예: `export BOT_TOKEN='디스코드봇토큰'`)
   - `LOG_LEVEL` (선택): 로그 수준, 기본값 `INFO`
   - 환경 변수는 `app/config.py`에서 읽습니다.

5. **봇 실행**:  
   ```bash
   python -m app
   ```
   - `BOT_TOKEN`이 없거나 로그인에 실패하면 종료 코드 1로 종료합니다.

---

## Docker 사용

`main` 브랜치에서 빌드한 이미지를 Docker Hub의 `dohun0310/discord-music-bot`에 발행합니다.
```bash
docker pull dohun0310/discord-music-bot
docker run -d --restart unless-stopped -e BOT_TOKEN='디스코드봇토큰' dohun0310/discord-music-bot
```

---

## CI/CD (Jenkins)

- `Jenkinsfile`을 사용하여 Docker 이미지를 여러 플랫폼에 자동 빌드할 수 있습니다.  
- 빌드 완료 시 Telegram 등으로 알림을 보낼 수 있으며, 빌드 테스트가 통과되지 않으면 자동으로 실패 처리가 됩니다.

---

## 문의 / 기여

- 문제나 버그가 발생하면 이슈(Issue)를 등록해주세요.  
- 기여를 원하시면 포크(Fork) 후 Pull Request를 보내주세요.