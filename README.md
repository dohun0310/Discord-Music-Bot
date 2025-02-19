# 디스코드 뮤직 봇 프로젝트

이 저장소는 디스코드 서버에서 음악을 재생해주는 파이썬 봇 예시 프로젝트입니다. 주요 기능과 사용 방법을 아래에 정리했습니다.

---

## 프로젝트 개요

- 디스코드 봇의 실행 파일: `main.py`  
- 음악 관련 로직 파일: `music_player.py`  
- YouTube 음원 정보를 추출하는 파일: `ytdl_source.py`  
- 봇 설정 정보: `config.py`  
- 헬퍼 함수(메시지 전송 등)를 포함한 파일: `utils.py`

---

## 주요 기능

1. **음악 재생**:  
   - 유저가 명령어를 입력하면, YouTube에서 음원 정보를 가져와 재생합니다.  
   - 재생 중인 음악이 끝나면, 자동으로 다음 대기열의 음악을 재생합니다.

2. **재생 대기열 (Queue)**:  
   - 여러 곡을 순서대로 재생할 수 있도록 대기열을 관리합니다.  
   - `MusicPlayer` 클래스에서 대기열 로직과 재생 순서를 제어합니다.

3. **명령어 예시**:  
   - `/재생 [URL or 검색어]` : 유튜브 URL 혹은 검색어로 음악 재생  
   - `/대기열` : 현재 대기열 목록 확인  
   - `/스킵` : 현재 재생 중인 음악을 스킵하고 다음 음악으로 넘어감  
   - `/정지` : 음악 정지 및 대기열 초기화

---

## 설치 방법

1. **Python 버전**: Python 3.10 이상 사용 권장  
2. **의존성 설치**:  
   ```bash
   pip install -r requirements.txt
   ```  
3. **환경 변수 설정**:  
   - `config.py`에서 사용하는 `BOT_TOKEN` 을 환경 변수로 설정해야 합니다.  
   - (예: `export BOT_TOKEN='디스코드봇토큰'`)

4. **봇 실행**:  
   ```bash
   python main.py
   ```

---

## Docker 사용

이 저장소에 있는 파일을 `Docker Hub`에 빌드해 두었습니다.
```bash
docker push dohun0310/discord-music-bot
docker run -e BOT_TOKEN='디스코드봇토큰' discord-music-bot
```

---

## CI/CD (Jenkins)

- `Jenkinsfile`을 사용하여 Docker 이미지를 여러 플랫폼에 자동 빌드할 수 있습니다.  
- 빌드 완료 시 Telegram 등으로 알림을 보낼 수 있으며, 빌드 테스트가 통과되지 않으면 자동으로 실패 처리가 됩니다.

---

## 문의 / 기여

- 문제나 버그가 발생하면 이슈(Issue)를 등록해주세요.  
- 기여를 원하시면 포크(Fork) 후 Pull Request를 보내주세요.