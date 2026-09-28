from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass


@dataclass
class Session:
    expires_at: float
    csrf: str
    department: str | None = None
    role: str = "operator"


class SessionManager:
    def __init__(self, operator_key: str, department_keys: dict[str, str] | None = None):
        self.operator_key = operator_key
        self.department_keys = department_keys or {}
        if any(len(key) < 16 or key == operator_key for key in self.department_keys.values()):
            raise ValueError("Department keys must be unique from the operator key and at least 16 characters")
        if len(set(self.department_keys.values())) != len(self.department_keys):
            raise ValueError("Department keys must be unique")
        self.sessions: dict[str, Session] = {}

    def login(self, supplied_key: str) -> tuple[str, Session] | None:
        department = None
        if not hmac.compare_digest(self.operator_key, supplied_key):
            department = next((name for name, key in self.department_keys.items()
                               if hmac.compare_digest(key, supplied_key)), None)
            if department is None:
                return None
        token = secrets.token_urlsafe(32)
        session = Session(expires_at=time.time() + 8 * 3600, csrf=secrets.token_urlsafe(24),
                          department=department,
                          role="department_reviewer" if department else "operator")
        self.sessions[token] = session
        return token, session

    def get(self, token: str | None) -> Session | None:
        session = self.sessions.get(token or "")
        if not session:
            return None
        if session.expires_at < time.time():
            self.sessions.pop(token or "", None)
            return None
        return session

    def logout(self, token: str | None) -> None:
        if token:
            self.sessions.pop(token, None)
