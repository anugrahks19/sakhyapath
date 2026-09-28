"""Standalone regional process: uvicorn app.regional_main:app --host 127.0.0.1 --port 8101."""
from __future__ import annotations

import os
from pathlib import Path

from app.services.regional import create_regional_app


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Set {name} for the regional agent")
    return value


app = create_regional_app(
    db_path=Path(required("SAKHYAPATH_REGION_DB")),
    region_id=required("SAKHYAPATH_REGION_ID"),
    departments={part.strip() for part in required("SAKHYAPATH_REGION_DEPARTMENTS").split(",") if part.strip()},
    token=required("SAKHYAPATH_REGION_TOKEN"),
    central_url=os.getenv("SAKHYAPATH_CENTRAL_URL") or None,
    central_token=os.getenv("SAKHYAPATH_CENTRAL_TOKEN") or None,
)
