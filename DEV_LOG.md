# 팀 스케줄 챗봇 개발 로그 & 아이디어

> 위치: `telegram_schedule_bot/DEV_LOG.md`
> 최종 업데이트: 2026-03-27

---

## 📦 프로젝트 개요

**Telegram 기반 팀 일정 관리 봇**
- Python Telegram Bot 21.6 + Claude AI (claude-3-5-sonnet)
- Google Calendar API (개인 + 팀 공용 캘린더)
- SQLite3 (WAL 모드) 로컬 DB
- Open-Meteo API 날씨 서비스 (무료, 키 불필요)

---

## ✅ 완료된 개발 항목

### Phase 1 — 기초 구조
- [x] Telegram Bot ConversationHandler 기반 아키텍처
- [x] Claude API 자연어 처리 (claude_service.py)
- [x] Google Calendar 연동 (OAuth2, 개인 캘린더 CRUD)
- [x] 사용자 등록/승인/거부/정지 플로우 (auth_handler.py)
- [x] SQLite 기반 사용자·일정·로그 DB (db/ 패키지)
- [x] 리마인더 시스템 (scheduler_service.py, N분 전 알림)

### Phase 2 — 팀 기능
- [x] 팀 이벤트 위저드 (team_wizard_handler)
  - 중요도 선택: 🔴 필수 / 🟡 조율가능 / 🟢 자유
  - 구글 캘린더 동기화
- [x] 팀 일정 충돌 감지
  - DB 기반: `get_overlapping_team_events()`
  - Google Calendar 기반: 개인 일정과의 시간 겹침 확인
  - Privacy fix: 충돌 알림에 다른 사용자 일정 내용 비공개 (이름만 공개)
- [x] 팀 공용 캘린더 생성 (`/setup_team`)
  - calendar_service.create_shared_calendar()
  - Google Calendar Group Calendar 생성
- [x] 팀 공용 캘린더 자동 공유
  - 사용자 Google 연동 시 → share_team_calendar(email)
  - shared_calendar_owner_uid 세팅으로 owner 자격증명 사용

### Phase 3 — UX 개선
- [x] 일정 등록 위저드 (wizard_handler.py)
  - 자연어 파싱 → 확인 → 등록 3단계 플로우
- [x] 일정 취소 위저드 (cancel_wizard_start)
  - 향후 14일 이벤트 목록 버튼으로 표시
  - 이름 기억 못해도 선택 가능
- [x] 하단 고정 메뉴 버튼 (ReplyKeyboardMarkup)
- [x] 날씨 서비스 (weather_service.py)
  - Open-Meteo API (무료)
  - 오늘 날씨 / 주간 예보 / 이벤트 당일 날씨
  - 1시간 캐시

### Phase 4 — 권한 체계
- [x] OWNER > ADMIN > MEMBER 3단계 역할 체계
  - DB `role` 컬럼 + migration 자동 적용
  - config.py: OWNER_TELEGRAM_IDS (기본값 = ADMIN_TELEGRAM_IDS)
- [x] OWNER 전용 기능
  - 👑 역할 관리: 사용자 역할 변경 (OWNER ↔ ADMIN ↔ MEMBER)
  - ⚙️ 시스템 설정: 공용 캘린더 ID, Owner UID 확인
- [x] ADMIN 기능
  - 사용자 승인/거부/정지/삭제
  - 사용 통계 조회
- [x] 사용자 삭제 cascade: team_event_conflicts → team_events → audit_log → users 원자적 삭제

### Phase 5 — 신규 사용자 경험 개선 (2026-03-27)
- [x] 신규 사용자 웰컴 메시지 (/start)
  - 봇 소개 + 기능 목록 표시
  - "이용 신청하기" 인라인 버튼 제공
- [x] 등록 플로우 NAME 단계 추가
  - 기존: DEPT → PURPOSE
  - 변경: NAME → DEPT → PURPOSE
  - 실명을 DB full_name에 저장
- [x] 도움말 버튼 정리
  - 제거: 오늘 일정, 이번 주 일정, 일정 등록, 일정 취소, 빈 시간 찾기, Google 연동
    (모두 하단 메뉴 버튼 또는 자연어로 처리 가능)
  - 유지: 시작 가이드, 개인 일정 설명, 팀 일정 설명, 리마인더 설정, 내 상태 확인

### 버그 수정 이력
- [x] `db.connection.get_conn()` AttributeError → `from db.connection import db_conn`로 수정
- [x] google_email 저장 실패 (위 버그로 인한 silent failure)
- [x] Google userinfo API 401 → calendarList() primary ID로 이메일 추출 변경
- [x] `shared_calendar_owner_uid` 누락 → 수동 세팅 + 코드에 저장 로직 추가
- [x] 충돌 감지 누락: `exclude_uid` 제거 → 본인 팀이벤트도 충돌 체크 대상 포함
- [x] 고아 팀이벤트(삭제된 사용자) → cascade delete + 수동 클린업

---

## 🔒 PROTECTED 모듈

아래 파일은 **의존성이 많아 수정 시 반드시 사용자에게 설명 후 승인** 받을 것:

| 파일 | 역할 | 주요 의존처 |
|------|------|------------|
| `constants.py` | 전역 상수 (세션 키, 버튼 텍스트 등) | 모든 handler, service |
| `utils.py` | OAuth state 생성, Markdown escape | calendar_service, 모든 handler |
| `db/connection.py` | SQLite 연결, init_db, migration | 모든 db repo |

---

## 🗺️ 현재 DB 상태 (2026-03-27)

| 항목 | 내용 |
|------|------|
| 활성 사용자 | 2명 (OWNER 1, MEMBER 1) |
| 팀 공용 캘린더 | 생성됨 (`shared_calendar_id` in settings) |
| Google 연동 계정 | seotepn@gmail.com (OWNER) |
| 팀 이벤트 | 테스트 이벤트 정리 완료 |

---

## 💡 향후 개발 아이디어

### 🌟 우선순위 높음

#### 1. 날씨 + 일정 연동 AI 브리핑
- 매일 아침 자동 브리핑 메시지
  - 오늘 날씨 요약 + 당일 일정 목록
  - "오후에 비 예보 → 외부 미팅 시 우산 챙기세요"
- 구현 위치: `services/briefing_service.py` + 스케줄러 연동
- `JobQueue`로 매일 08:00 KST 발송

#### 2. 팀 일정 조율 UI 개선
- 충돌 발생 시 대안 시간대 자동 추천
  - "3명 모두 가능한 시간: 화 14:00, 수 10:00"
- `find_free_slots()`를 다중 사용자에 대해 교집합 계산

#### 3. 반복 일정 지원
- "매주 월요일 10시 팀 스탠드업" 자연어 파싱
- Google Calendar recurrence 규칙 생성 (RRULE)
- DB에 recurrence_rule 컬럼 추가

### 🔧 중간 우선순위

#### 4. 일정 수정 위저드
- "금요일 미팅 시간 3시로 바꿔줘" 처리
- 현재는 삭제 후 재등록해야 함
- `update_event()` API 추가 필요

#### 5. 팀원 초대 시스템
- OWNER/ADMIN이 초대 링크 생성
- 링크 클릭 → 자동 등록 (승인 필요 없음 옵션)
- `settings` 테이블에 `invite_token` 저장

#### 6. 일정 검색
- "지난주 미팅 기록 찾아줘"
- Google Calendar search API 활용
- 날짜 범위 + 키워드 조합 쿼리

#### 7. 통계/리포트
- 주간/월간 일정 요약 리포트
- "이번 달 팀 미팅 몇 번 했어?"
- audit_log 기반 활동 분석

### 🎯 낮은 우선순위 / 아이디어

#### 8. 외부 캘린더 연동
- Notion Calendar, Apple Calendar sync
- `.ics` 파일 import/export

#### 9. 일정 공유 링크
- "이 미팅 링크 공유해줘" → 구글 캘린더 이벤트 링크 전송
- 참석자 추가 (attendees API)

#### 10. 다국어 지원
- 현재: 한국어 고정
- 사용자별 언어 설정 (settings 테이블)
- 영어 UI 지원

#### 11. Slack/Teams 연동
- 팀 일정 변경 시 Slack 채널 알림
- Webhook 기반 단방향 연동

#### 12. 음성 메모 → 일정
- 텔레그램 음성 메시지 → Whisper API → 텍스트 → 일정 등록
- `telegram.Voice` 핸들러 추가

---

## 🛠️ 기술 부채 & 리팩토링 필요 항목

- [ ] `handlers/calendar_handler.py`가 너무 큼 → 분리 고려
- [ ] `services/team_service.py` 충돌 감지 로직 테스트 코드 부재
- [ ] Google API 호출 실패 시 재시도 로직 없음 (exponential backoff)
- [ ] 환경별 설정 분리 (dev/prod .env)
- [ ] 단위 테스트 전무 → pytest 기반 테스트 추가

---

## 📁 주요 파일 구조

```
telegram_schedule_bot/
├── bot.py                    # 진입점, 핸들러 등록
├── config.py                 # 환경변수 로드 (PROTECTED)
├── constants.py              # 전역 상수 (PROTECTED)
├── utils.py                  # 유틸리티 (PROTECTED)
├── db/
│   ├── connection.py         # DB 연결 + init_db (PROTECTED)
│   ├── user_repo.py          # 사용자 CRUD
│   ├── team_repo.py          # 팀 이벤트 CRUD
│   ├── reminder_repo.py      # 리마인더 + 로그
│   └── settings_repo.py      # 설정 key-value
├── handlers/
│   ├── auth_handler.py       # 등록/승인/연동 플로우
│   ├── admin_handler.py      # 관리자 대시보드 (OWNER/ADMIN)
│   ├── calendar_handler.py   # 메인 메뉴 + 자연어 라우팅
│   ├── wizard_handler.py     # 일정 등록/취소 위저드
│   └── team_handler.py       # 팀 일정 충돌 조율
├── services/
│   ├── calendar_service.py   # Google Calendar API
│   ├── claude_service.py     # Claude AI API
│   ├── team_service.py       # 팀 충돌 감지 로직
│   ├── weather_service.py    # Open-Meteo 날씨
│   ├── scheduler_service.py  # 리마인더 스케줄러
│   ├── rate_limiter.py       # API 레이트 리미팅
│   └── oauth_server.py       # Mac 로컬 OAuth 캡처
├── models/
│   └── user.py               # UserStatus enum
└── DEV_LOG.md                # ← 이 파일
```
