"""Decision-only equal-budget comparison. Never opens a second capture."""
from __future__ import annotations

import json

from app.storage.database import Database, utc_now


def shadow_policies(ranks: list[dict], adaptive: dict[str, float], budget: float,
                    revision: int, slots: int) -> dict:
    eligible = [row["camera_id"] for row in ranks]
    count = min(slots, len(eligible), len(adaptive))
    if count == 0:
        return {"uniform": {}, "adaptive": adaptive, "exploration_camera_id": None}
    # Rotate the baseline across the permitted grid, at the same camera-slot and fps budget.
    start = (revision - 1) % len(eligible)
    uniform_ids = [eligible[(start + i) % len(eligible)] for i in range(count)]
    usable = min(budget, sum(adaptive.values()))
    rate = int(usable / count * 1000) / 1000
    outside = [camera_id for camera_id in eligible if camera_id not in adaptive]
    return {"uniform": {camera_id: rate for camera_id in uniform_ids},
            "adaptive": adaptive, "exploration_camera_id": outside[(revision - 1) % len(outside)] if outside else None}


class ShadowLedger:
    def __init__(self, db: Database):
        self.db = db

    def migrate(self) -> None:
        with self.db.connection() as connection:
            connection.executescript("""CREATE TABLE IF NOT EXISTS shadow_decisions (
                schedule_id TEXT PRIMARY KEY REFERENCES pursuit_schedules(id),
                pursuit_id TEXT NOT NULL, created_utc TEXT NOT NULL,
                decisions_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pursuit_exploration (
                pursuit_id TEXT PRIMARY KEY REFERENCES pursuits(id), enabled INTEGER NOT NULL DEFAULT 0);""")

    def enabled(self, pursuit_id: str) -> bool:
        with self.db.connection() as connection:
            row = connection.execute("SELECT enabled FROM pursuit_exploration WHERE pursuit_id=?", (pursuit_id,)).fetchone()
        return bool(row and row["enabled"])

    def set_enabled(self, pursuit_id: str, enabled: bool) -> dict:
        with self.db.connection() as connection:
            connection.execute("INSERT INTO pursuit_exploration VALUES(?,?) ON CONFLICT(pursuit_id) DO UPDATE SET enabled=excluded.enabled", (pursuit_id, int(enabled)))
        return {"pursuit_id": pursuit_id, "exploration_enabled": enabled}

    def record(self, schedule_id: str, pursuit_id: str, revision: int,
               ranks: list[dict], adaptive: dict[str, float], budget: float, slots: int) -> None:
        policies = shadow_policies(ranks, adaptive, budget, revision, slots)
        policies.update({"revision": revision, "budget_fps": budget,
                         "source": "one capture path; uniform policy is counterfactual only",
                         "outcome_warning": "Counterfactual hits and detection gains require recorded replay; decisions alone prove no accuracy benefit."})
        with self.db.connection() as connection:
            connection.execute("INSERT INTO shadow_decisions VALUES(?,?,?,?)",
                               (schedule_id, pursuit_id, utc_now(), json.dumps(policies, sort_keys=True)))

    def history(self, pursuit_id: str) -> dict:
        with self.db.connection() as connection:
            rows = connection.execute("SELECT schedule_id,created_utc,decisions_json FROM shadow_decisions WHERE pursuit_id=? ORDER BY created_utc DESC LIMIT 100", (pursuit_id,)).fetchall()
        return {"pursuit_id": pursuit_id, "exploration_enabled": self.enabled(pursuit_id),
                "decisions": [{"schedule_id": row["schedule_id"], "created_utc": row["created_utc"], **json.loads(row["decisions_json"])} for row in rows],
                "meaning": "Uniform is a shadow decision on the same captured feeds. Only adaptive is applied; no duplicate capture or counterfactual detection is claimed."}
