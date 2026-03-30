"""
날씨 서비스 — Open-Meteo API (완전 무료, API 키 불필요)
https://open-meteo.com/

캐시: 1시간 TTL (불필요한 API 호출 최소화)
위치: config.py 의 USER_LATITUDE / USER_LONGITUDE (기본: 서울)
"""
import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from config import TIMEZONE, USER_LATITUDE, USER_LONGITUDE

log = logging.getLogger(__name__)

BASE_URL    = "https://api.open-meteo.com/v1/forecast"
_CACHE_TTL  = 3600  # 1시간

# WMO 날씨 코드 → (이모지, 한국어 설명)
WMO_CODES: dict[int, tuple[str, str]] = {
    0:  ("☀️",  "맑음"),
    1:  ("🌤️", "대체로 맑음"),
    2:  ("⛅",  "부분적으로 흐림"),
    3:  ("☁️",  "흐림"),
    45: ("🌫️", "안개"),
    48: ("🌫️", "짙은 안개"),
    51: ("🌦️", "약한 이슬비"),
    53: ("🌦️", "이슬비"),
    55: ("🌧️", "강한 이슬비"),
    61: ("🌧️", "약한 비"),
    63: ("🌧️", "비"),
    65: ("🌧️", "강한 비"),
    71: ("🌨️", "약한 눈"),
    73: ("🌨️", "눈"),
    75: ("❄️",  "강한 눈"),
    77: ("🌨️", "싸락눈"),
    80: ("🌦️", "소나기"),
    81: ("🌧️", "강한 소나기"),
    82: ("⛈️",  "폭우"),
    85: ("🌨️", "눈 소나기"),
    86: ("❄️",  "강한 눈 소나기"),
    95: ("⛈️",  "뇌우"),
    96: ("⛈️",  "우박 동반 뇌우"),
    99: ("⛈️",  "강한 우박 동반 뇌우"),
}

_cache: dict = {}


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _cache_get(key: str) -> Optional[dict]:
    entry = _cache.get(key)
    if entry and time.monotonic() - entry["ts"] < _CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data: dict) -> None:
    _cache[key] = {"data": data, "ts": time.monotonic()}


def _wmo(code) -> tuple[str, str]:
    try:
        return WMO_CODES.get(int(code), ("🌡️", f"코드 {code}"))
    except (TypeError, ValueError):
        return ("🌡️", "알 수 없음")


def _fetch(lat: float, lon: float) -> Optional[dict]:
    """Open-Meteo 일별+시간별 예보 가져오기. 1시간 캐시 적용."""
    key = f"{lat:.4f}:{lon:.4f}"
    cached = _cache_get(key)
    if cached:
        return cached
    try:
        resp = httpx.get(
            BASE_URL,
            params={
                "latitude":      lat,
                "longitude":     lon,
                "daily":         (
                    "weathercode,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,precipitation_sum"
                ),
                "hourly":        (
                    "temperature_2m,apparent_temperature,"
                    "precipitation_probability,weathercode"
                ),
                "timezone":      TIMEZONE,
                "forecast_days": 7,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _cache_set(key, data)
        log.debug("Open-Meteo 날씨 데이터 수신 완료 lat=%s lon=%s", lat, lon)
        return data
    except Exception as e:
        log.warning("Open-Meteo API 호출 실패: %s", e)
        return None


# ── 공개 API ──────────────────────────────────────────────

def get_today_summary(
    lat: float = USER_LATITUDE,
    lon: float = USER_LONGITUDE,
) -> str:
    """오늘 날씨 한 줄 요약 텍스트."""
    data = _fetch(lat, lon)
    if not data:
        return "🌡️ 날씨 정보 없음"

    daily = data.get("daily", {})
    code  = daily.get("weathercode", [0])[0]
    t_max = daily.get("temperature_2m_max", [None])[0]
    t_min = daily.get("temperature_2m_min", [None])[0]
    rain  = daily.get("precipitation_probability_max", [0])[0] or 0

    icon, desc = _wmo(code)
    parts = [f"{icon} {desc}"]
    if t_max is not None and t_min is not None:
        parts.append(f"🌡️ {t_min:.0f}°C ~ {t_max:.0f}°C")
    if int(rain) >= 20:
        parts.append(f"☂️ {int(rain)}%")
    return "  ".join(parts)


def get_week_forecast(
    lat: float = USER_LATITUDE,
    lon: float = USER_LONGITUDE,
) -> str:
    """5일 날씨 예보 Markdown 텍스트."""
    data = _fetch(lat, lon)
    if not data:
        return "🌡️ 날씨 정보를 가져올 수 없습니다."

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    codes = daily.get("weathercode", [])
    t_max = daily.get("temperature_2m_max", [])
    t_min = daily.get("temperature_2m_min", [])
    rain  = daily.get("precipitation_probability_max", [])

    lines = ["🌤 *5일 날씨 예보*\n"]
    for i, date in enumerate(dates[:5]):
        if i >= len(codes):
            break
        icon, desc = _wmo(codes[i])
        hi   = t_max[i] if i < len(t_max) else None
        lo   = t_min[i] if i < len(t_min) else None
        r    = int(rain[i]) if i < len(rain) and rain[i] else 0

        try:
            dt        = datetime.strptime(date, "%Y-%m-%d")
            day_label = dt.strftime("%m/%d (%a)")
        except Exception:
            day_label = date

        temp_str = f" {lo:.0f}°~{hi:.0f}°C" if hi is not None and lo is not None else ""
        rain_str = f" ☂️{r}%" if r >= 20 else ""
        lines.append(f"• *{day_label}* {icon} {desc}{temp_str}{rain_str}")

    return "\n".join(lines)


def get_event_weather(
    event_datetime: str,
    lat: float = USER_LATITUDE,
    lon: float = USER_LONGITUDE,
) -> Optional[dict]:
    """
    특정 일정 시간대의 시간별 날씨 반환.
    event_datetime: 'YYYY-MM-DDTHH:MM' 또는 'YYYY-MM-DD HH:MM'
    """
    data = _fetch(lat, lon)
    if not data:
        return None

    hourly = data.get("hourly", {})
    times  = hourly.get("time", [])
    target = event_datetime.replace(" ", "T")[:16]

    # 가장 가까운 시간 인덱스 탐색 (±2시간 이내)
    best_idx, best_diff = None, float("inf")
    for i, t in enumerate(times):
        try:
            diff = abs(
                (datetime.fromisoformat(t) - datetime.fromisoformat(target)).total_seconds()
            )
            if diff < best_diff:
                best_diff, best_idx = diff, i
        except Exception:
            continue

    if best_idx is None or best_diff > 7200:
        return None

    codes = hourly.get("weathercode", [])
    temps = hourly.get("temperature_2m", [])
    feels = hourly.get("apparent_temperature", [])
    rain  = hourly.get("precipitation_probability", [])

    code       = codes[best_idx] if best_idx < len(codes) else 0
    icon, desc = _wmo(code)

    return {
        "icon":              icon,
        "desc":              desc,
        "temp":              temps[best_idx] if best_idx < len(temps) else None,
        "feels_like":        feels[best_idx] if best_idx < len(feels) else None,
        "precipitation_prob": int(rain[best_idx]) if best_idx < len(rain) else 0,
        "datetime":          times[best_idx],
    }


def format_event_weather_hint(event_datetime: str) -> str:
    """
    일정에 날씨 힌트 한 줄 반환.
    주의 필요 날씨(비/눈/뇌우)만 반환하고, 맑음·구름은 빈 문자열 반환.
    """
    w = get_event_weather(event_datetime)
    if not w:
        return ""
    rain = w.get("precipitation_prob", 0)
    temp = w.get("temp")
    temp_str = f" {temp:.0f}°C" if temp is not None else ""

    # 비/눈/뇌우 → 우산 경고
    if rain >= 40:
        return f"{w['icon']} {w['desc']}{temp_str} ☂️ 우산 챙기세요"
    # 이슬비 이상
    if rain >= 20:
        return f"{w['icon']} {w['desc']}{temp_str}"
    return ""
