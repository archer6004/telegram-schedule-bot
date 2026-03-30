import json
from datetime import datetime, timedelta
from typing import Optional
import pytz
from utils import generate_oauth_state

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
        state=generate_oauth_state(telegram_id),  # 랜덤 토큰 (telegram_id 노출 방지)
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

        # 이메일 가져와서 저장 + 팀 캘린더 자동 공유
        try:
            from db.connection import db_conn
            cal_svc = build("calendar", "v3", credentials=creds)
            cal_list = cal_svc.calendarList().list().execute()
            primary = next((c for c in cal_list.get("items", []) if c.get("primary")), None)
            email = primary.get("id", "") if primary else ""
            if email:
                with db_conn() as conn:
                    conn.execute(
                        "UPDATE users SET google_email=? WHERE telegram_id=?",
                        (email, telegram_id)
                    )
                # 팀 캘린더가 있으면 자동 공유
                share_team_calendar(email)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("이메일 저장/캘린더 공유 실패: %s", e)

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

def delete_event_by_id(telegram_id: int, event_id: str) -> None:
    """Google Calendar 이벤트 ID로 직접 삭제 (위저드에서 사용)."""
    service = _service(telegram_id)
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    db.log_action(telegram_id, "DELETE_EVENT_BY_ID", event_id)


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

def find_free_slots(
    telegram_id: int,
    date_from: str,
    date_to: str,
    duration_hours: float = 1.0,
) -> dict[str, list[str]]:
    """date_from ~ date_to 범위의 날짜별 빈 시간대 반환 (09:00–19:00 기준)."""
    from datetime import date as date_cls
    duration = timedelta(hours=duration_hours)
    result = {}

    start = date_cls.fromisoformat(date_from)
    end   = date_cls.fromisoformat(date_to)
    delta = (end - start).days + 1

    for i in range(delta):
        day = (start + timedelta(days=i)).isoformat()
        t_min = f"{day}T09:00:00+09:00"
        t_max = f"{day}T19:00:00+09:00"

        events = list_events(telegram_id, t_min, t_max)
        busy = []
        for e in events:
            # 종일 이벤트(all-day)는 프레임 이벤트로 간주 → 빈 시간 계산에서 제외
            if "dateTime" not in e.get("start", {}):
                continue
            s  = e["start"].get("dateTime")
            en = e["end"].get("dateTime")
            if s and en:
                busy.append((
                    datetime.fromisoformat(s).astimezone(tz),
                    datetime.fromisoformat(en).astimezone(tz),
                ))
        busy.sort()

        slots = []
        cursor    = datetime.fromisoformat(t_min).astimezone(tz)
        end_of_day = datetime.fromisoformat(t_max).astimezone(tz)

        for b_start, b_end in busy:
            if cursor + duration <= b_start:
                slots.append(f"{cursor.strftime('%H:%M')} – {b_start.strftime('%H:%M')}")
            cursor = max(cursor, b_end)

        if cursor + duration <= end_of_day:
            slots.append(f"{cursor.strftime('%H:%M')} – {end_of_day.strftime('%H:%M')}")

        if slots:
            result[day] = slots

    return result


# ── 공용 캘린더 ──────────────────────────────────────────

def create_shared_calendar(admin_uid: int) -> str:
    """관리자 계정으로 '팀 공용 일정' 캘린더를 생성하고 calendar ID를 반환."""
    import logging
    log = logging.getLogger(__name__)
    svc = _service(admin_uid)
    cal = svc.calendars().insert(body={
        "summary":  "팀 공용 일정",
        "description": "봇이 관리하는 팀 공용 캘린더",
        "timeZone": TIMEZONE,
    }).execute()
    calendar_id = cal["id"]
    db.set_setting("shared_calendar_id", calendar_id)
    # 캘린더 생성자(owner) uid 저장 → 이후 ACL 공유에 사용
    db.set_setting("shared_calendar_owner_uid", str(admin_uid))
    # 기존 연동 사용자에게 즉시 공유
    users = db.get_all_connected_users()
    for u in users:
        email = u.get("google_email")
        if email:
            try:
                svc.acl().insert(
                    calendarId=calendar_id,
                    body={"role": "writer", "scope": {"type": "user", "value": email}},
                ).execute()
                log.info("팀 캘린더 공유 완료: %s", email)
            except Exception as e:
                log.warning("팀 캘린더 공유 실패 %s: %s", email, e)
    return calendar_id


def share_team_calendar(email: str) -> bool:
    """
    팀 공용 캘린더를 특정 이메일에 공유합니다.
    캘린더 owner의 credentials를 사용합니다.
    """
    import logging
    log = logging.getLogger(__name__)
    calendar_id = db.get_setting("shared_calendar_id")
    owner_uid_str = db.get_setting("shared_calendar_owner_uid")
    if not calendar_id or not owner_uid_str or not email:
        return False
    try:
        owner_uid = int(owner_uid_str)
        svc = _service(owner_uid)
        svc.acl().insert(
            calendarId=calendar_id,
            body={"role": "writer", "scope": {"type": "user", "value": email}},
        ).execute()
        log.info("팀 캘린더 공유 완료: %s", email)
        return True
    except Exception as e:
        log.warning("팀 캘린더 공유 실패 %s: %s", email, e)
        return False


def write_to_shared_calendar(
    admin_uid: int,
    title: str, start: str, end: str,
    description: str = "",
) -> Optional[str]:
    """공용 캘린더에 일정 기록. 캘린더 미설정 시 None 반환."""
    calendar_id = db.get_setting("shared_calendar_id")
    if not calendar_id:
        return None
    svc = _service(admin_uid)
    body = {
        "summary":  title,
        "description": description,
        "start": {"dateTime": _ensure_tz(start), "timeZone": TIMEZONE},
        "end":   {"dateTime": _ensure_tz(end),   "timeZone": TIMEZONE},
    }
    event = svc.events().insert(calendarId=calendar_id, body=body).execute()
    return event.get("id")


def _ensure_tz(dt_str: str) -> str:
    """ISO8601 문자열에 타임존이 없으면 KST(+09:00)를 붙입니다."""
    if "+" not in dt_str and "Z" not in dt_str:
        return dt_str + "+09:00"
    return dt_str


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
