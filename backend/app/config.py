from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    operator_key: str
    sentinel_base_url: str | None = None
    sentinel_authorization: str | None = None
    cookie_secure: bool = False
    idle_capture_seconds: float = 5.0
    evidence_dir: Path | None = None
    models_dir: Path | None = None
    analytics_max_cameras: int = 4
    department_keys: dict[str, str] | None = None
    proof_key_path: Path | None = None
    regions: list[dict] | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        key = os.getenv("SAKHYAPATH_OPERATOR_KEY", "")
        if len(key) < 16:
            raise RuntimeError("Set SAKHYAPATH_OPERATOR_KEY to at least 16 characters")
        default_db = Path(__file__).resolve().parents[1] / "data" / "sakhyapath.sqlite3"
        database_path = Path(os.getenv("SAKHYAPATH_DB", str(default_db)))
        return cls(
            database_path=database_path,
            operator_key=key,
            sentinel_base_url=os.getenv("SAKHYAPATH_SENTINEL_BASE_URL") or None,
            sentinel_authorization=os.getenv("SAKHYAPATH_SENTINEL_AUTHORIZATION") or None,
            cookie_secure=os.getenv("SAKHYAPATH_COOKIE_SECURE") == "1",
            evidence_dir=Path(os.getenv("SAKHYAPATH_EVIDENCE_DIR") or database_path.parent / "evidence"),
            models_dir=Path(os.getenv("SAKHYAPATH_MODELS_DIR") or database_path.parent / "models"),
            analytics_max_cameras=max(1, int(os.getenv("SAKHYAPATH_ANALYTICS_MAX_CAMERAS", "4"))),
            department_keys=json.loads(os.getenv("SAKHYAPATH_DEPARTMENT_KEYS", "{}")),
            proof_key_path=Path(os.getenv("SAKHYAPATH_PROOF_KEY_PATH") or database_path.parent / "proof_signing_ed25519.pem"),
            regions=json.loads(os.getenv("SAKHYAPATH_REGIONS", "[]")),
        )
