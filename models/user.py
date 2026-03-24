"""
사용자 도메인 모델
"""
from dataclasses import dataclass
from typing import Optional


class UserStatus:
    PENDING   = "PENDING"
    APPROVED  = "APPROVED"
    REJECTED  = "REJECTED"
    EXPIRED   = "EXPIRED"
    SUSPENDED = "SUSPENDED"


@dataclass
class User:
    telegram_id:     int
    username:        str           = ""
    full_name:       str           = ""
    department:      str           = ""
    purpose:         str           = ""
    status:          str           = UserStatus.PENDING
    google_token:    Optional[str] = None
    created_at:      Optional[str] = None
    approved_at:     Optional[str] = None
    expires_at:      Optional[str] = None
    rejected_reason: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "User":
        """sqlite3.Row dict를 User 인스턴스로 변환"""
        fields = cls.__dataclass_fields__
        return cls(**{k: row.get(k) for k in fields})
