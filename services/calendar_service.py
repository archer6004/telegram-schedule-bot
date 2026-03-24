import json
from datetime import datetime, timedelta
from typing import Optional
import pytz

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from config import GOOGLE_CREDENTIALS_PATH, GOOGLE_SCOPES, TIMEZONE
import db as db

tz = pytz.timezone(TIMEZONE)


def get_credentials(telegram_id: int) -> Optional[Credentials]:
    token = db.get_google_token(telegram_id)
    if not token:
        return None
    creds = Credentials.from_authorized_user_info(token, GOOGLE_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        db.save_google_token(telegram_id, json.loads(creds.to_json()))
    return creds


REDIRECT_URI = "https://archer6004.github.io/telegram-schedule-bot/oauth/"


def get_auth_url(telegram_id: int) -> str:
    flow = Flow.from_client_secrets_file(
        GOOGLE_CREDENTIALS_PATH,
        scopes=GOOGLE_SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=str(telegram_id),
        prompt="consent",
    )
    return url


def exchange_code(telegram_id: int, code: str) -> bool:
    try:
        flow = Flow.from_client_secrets_file(
            GOOGLE_CREDENTIALS_PATH,
            scopes=GOOGLE_SCOPES,
            redirect_uri=REDIRECT_URI,
        )
        flow.fetch_token(code=code)
        creds = flow.credentials
        db.save_google_token(telegram_id, json.loads(creds.to_json()))
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("exchange_code 실패: %s", e)
        return False


def _service(telegram_id: int):
    creds = get_credentials(telegram_id)
    if not creds:
        raise PermissionError("Google 계정이 연동되지 않았습니다. /connect 명령어로 연결하세요.")
    return build("calendar", "v3", credentials=creds)


# ── 일정 생성 ─────────────────────────────────────────────

def create_event(telegram_id: int, title: str, start: str, end: str,
                 location: str = "", description: str = "", attendees: list = None) -> dict:
    service = _service(telegram_id)
    body = {
        "summary": title,
        "start": {"dateTime": start, "timeZone": TIMEZONE},
        "end":   {"dateTime": end,   "timeZone": TIMEZONE},
    }
    if location:    body["location"] = location
    if description: body["description"] = description
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]

    event = service.events().insert(calendarId="primary", body=body).execute()
    db.log_action(telegram_id, "CREATE_EVENT", f"{title} | {start}")
    return event


# ── 일정 목록 조회 ────────────────────────────────────────

def list_events(telegram_id: int, time_min: str, time_max: str) -> list[dict]:
    service = _service(telegram_id)
    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
        maxResults=20,
    ).execute()
    return result.get("items", [])


# ── 일정 삭제 ─────────────────────────────────────────────

def delete_event(telegram_id: int, query: str, date_hint: str = None) -> bool:
    service = _service(telegram_id)
    now = datetime.now(tz)

    # 검색 범위: date_hint가 있으면 그 날, 없으면 오늘부터 2주
    if date_hint:
        t_min = f"{date_hint}T00:00:00+09:00"
        t_max = f"{date_hint}T23:59:59+09:00"
    else:
        t_min = now.isoformat()
        t_max = (now + timedelta(weeks=2)).isoformat()

    items = list_events(telegram_id, t_min, t_max)
    matched = [e for e in items if query.lower() in e.get("summary", "").lower()]

    if not matched:
        return False

    event = matched[0]
    service.events().delete(calendarId="primary", eventId=event["id"]).execute()
    db.log_action(telegram_id, "DELETE_EVENT", event.get("summary", ""))
    return True


# ── 빈 시간 찾기 ─────────────────────────────────────────

def find_free_slots(telegram_id: int, date: str, duration_hours: float = 1.0) -> list[str]:
    t_min = f"{date}T09:00:00+09:00"
    t_max = f"{date}T19:00:00+09:00"
    events = list_events(telegram_id, t_min, t_max)

    busy = []
    for e in events:
        s = e["start"].get("dateTime", e["start"].get("date"))
        en = e["end"].get("dateTime", e["end"].get("date"))
        if s and en:
            busy.append((
                datetime.fromisoformat(s).astimezone(tz),
                datetime.fromisoformat(en).astimezone(tz),
            ))
    busy.sort()

    slots = []
    cursor = datetime.fromisoformat(t_min).astimezone(tz)
    end_of_day = datetime.fromisoformat(t_max).astimezone(tz)
    duration = timedelta(hours=duration_hours)

    for b_start, b_end in busy:
        if cursor + duration <= b_start:
            slots.append(f"{cursor.strftime('%H:%M')} – {b_start.strftime('%H:%M')}")
        cursor = max(cursor, b_end)

    if cursor + duration <= end_of_day:
        slots.append(f"{cursor.strftime('%H:%M')} – {end_of_day.strftime('%H:%M')}")

    return slots


# ── 포맷 헬퍼 ────────────────────────────────────────────

def format_event(event: dict) -> str:
    title = event.get("summary", "(제목 없음)")
    start = event["start"].get("dateTime", event["start"].get("date", ""))
    end   = event["end"].get("dateTime",   event["end"].get("date", ""))
    loc   = event.get("location", "")
    link  = event.get("htmlLink", "")

    try:
        s = datetime.fromisoformat(start).astimezone(tz)
        e = datetime.fromisoformat(end).astimezone(tz)
        time_str = f"{s.strftime('%Y년 %m월 %d일 (%a) %H:%M')} – {e.strftime('%H:%M')}"
    except Exception:
        time_str = start

    lines = [f"✅ *{title}*", f"🗓 {time_str}"]
    if loc: lines.append(f"📍 {loc}")
    if link: lines.append(f"🔗 [캘린더에서 보기]({link})")
    return "\n".join(lines)


def format_event_list(events: list[dict]) -> str:
    if not events:
        return "일정이 없습니다."
    lines = []
    for e in events:
        title = e.get("summary", "(제목 없음)")
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        try:
            s = datetime.fromisoformat(start).astimezone(tz)
            time_str = s.strftime("%m/%d(%a) %H:%M")
        except Exception:
            time_str = start
        lines.append(f"• {time_str}  {title}")
    return "\n".join(lines)
