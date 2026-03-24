# 📅 Telegram 스케줄 챗봇

Google Calendar + Claude AI 기반 Telegram 일정 관리 봇

---

## 빠른 시작

### 1. 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. 환경 변수 설정
```bash
cp .env.example .env
# .env 파일을 열어 각 값을 채워주세요
```

| 변수 | 설명 |
|------|------|
| `TELEGRAM_BOT_TOKEN` | @BotFather 에서 발급 |
| `ADMIN_TELEGRAM_IDS` | 관리자 Telegram ID (콤마 구분) |
| `ANTHROPIC_API_KEY` | Anthropic Console에서 발급 |
| `GOOGLE_CREDENTIALS_PATH` | Google OAuth2 credentials.json 경로 |

### 3. Google Calendar API 설정
1. [Google Cloud Console](https://console.cloud.google.com) → 새 프로젝트 생성
2. **APIs & Services → Enable APIs** → Google Calendar API 활성화
3. **OAuth 2.0 Client ID** 생성 (유형: Desktop app)
4. `credentials.json` 다운로드 → 프로젝트 루트에 배치

### 4. 봇 실행
```bash
python main.py
```

---

## 파일 구조

```
telegram_schedule_bot/
├── main.py                      # 봇 진입점
├── config.py                    # 환경 변수 로드
├── database.py                  # SQLite CRUD
├── requirements.txt
├── .env.example
├── handlers/
│   ├── auth_handler.py          # /start, /register, /connect
│   ├── admin_handler.py         # /admin, 승인/거부 버튼
│   └── calendar_handler.py      # /today, /week, /free, 자연어 처리
└── services/
    ├── claude_service.py        # Claude API + Tool Use
    ├── calendar_service.py      # Google Calendar API
    └── scheduler_service.py     # APScheduler (리마인더, 브리핑)
```

---

## 지원 기능

### 사용자
| 명령어 | 기능 |
|--------|------|
| `/start` | 시작 / 상태 확인 |
| `/register` | 이용 신청 |
| `/connect` | Google Calendar 연동 |
| `/today` | 오늘 일정 |
| `/week` | 이번 주 일정 |
| `/free` | 오늘 빈 시간대 |
| `/status` | 내 권한 상태 |
| 자연어 | 일정 생성/조회/삭제/리마인더 |

### 관리자
| 명령어 | 기능 |
|--------|------|
| `/admin` | 대시보드 (대기/활성/오늘 요청 수) |
| 승인 버튼 | 신청 승인 → 사용자에게 알림 |
| 거부 버튼 | 신청 거부 → 사용자에게 알림 |

### 자동 알림
- **아침 브리핑**: 매일 오전 8시 오늘 일정 발송
- **리마인더**: 일정 1시간 전, 10분 전 자동 알림
- **일정 충돌 감지**: 동 시간대 일정 생성 시 경고

---

## 자연어 예시

```
내일 오후 3시에 팀 미팅 잡아줘
이번 주 일정 보여줘
금요일 회의 취소해줘
다음 주 화요일 2시간 비는 시간 찾아줘
팀 미팅 1시간 전이랑 10분 전에 알려줘
매주 월요일 9시 스탠드업 등록해줘
```
