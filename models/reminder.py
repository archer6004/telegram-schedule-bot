"""
리마인더 / 감사 로그 도메인 모델
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Reminder:
    telegram_id:    int
    event_id:       str
    event_title:    str
    event_datetime: str
    remind_at:      str
    id:             Optional[int] = None
    sent:           int           = 0
    created_at:     Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "Reminder":
        fields = cls.__dataclass_fields__
        return cls(**{k: row.get(k) for k in fields})


@dataclass
class AuditLog:
    telegram_id: int
    action:      str
    detail:      str           = ""
    id:          Optional[int] = None
    created_at:  Optional[str] = None
