"""Observable feed/clock readiness; grades are rules, not probabilities."""
from __future__ import annotations

from datetime import datetime, timezone

from app.storage.database import Database


class CameraTrust:
    def __init__(self, db: Database):
        self.db = db

    def scorecard(self, camera: dict, analysis: dict, capture: dict | None = None) -> dict:
        camera_id = camera["camera_id"]
        with self.db.connection() as connection:
            errors = connection.execute("SELECT count,last_kind FROM camera_capture_errors WHERE camera_id=?", (camera_id,)).fetchone()
            mappings = [dict(row) for row in connection.execute(
                "SELECT stream_generation,uncertainty_ms,basis,created_utc FROM time_mappings WHERE camera_id=? ORDER BY stream_generation DESC LIMIT 3", (camera_id,))]
            events = [dict(row) for row in connection.execute(
                "SELECT at_utc,status,detail FROM camera_health_events WHERE camera_id=? ORDER BY id DESC LIMIT 20", (camera_id,))]
        last_frame = camera["last_frame_utc"]
        age = None
        if last_frame:
            age = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(last_frame)).total_seconds())
        recent_mapping = next((row for row in mappings if row["stream_generation"] == camera["stream_generation"]), None)
        fresh = age is not None and age <= 30
        decoded = camera["health_status"] == "online" and fresh
        pts = camera["source_pts"] is not None and bool(camera["pts_timebase"])
        clock_verified = bool(recent_mapping and recent_mapping["basis"] == "owned_recording_clock_attested")
        clock_precise_enough = bool(clock_verified and recent_mapping["uncertainty_ms"] <= 1000)
        queue_age = analysis.get("last_queue_age_ms")
        reasons = []
        if not camera["catalogue_present"]:
            reasons.append("Camera absent from latest catalogue")
        if not decoded:
            reasons.append("No fresh decoded frame")
        if not pts:
            reasons.append("Source PTS/timebase unavailable")
        if not clock_verified:
            reasons.append("No attested UTC mapping for current stream generation")
        elif not clock_precise_enough:
            reasons.append("Clock mapping uncertainty exceeds one second review threshold")
        if queue_age is not None and queue_age > 2000:
            reasons.append("Analytics queue older than 2 seconds")
        if not analysis.get("running"):
            reasons.append("Analytics not running")
        return {
            "camera_id": camera_id, "source_mode": camera["source_mode"],
            "codec": camera["codec"], "resolution": [camera["width"], camera["height"]],
            "measured_fps": camera["measured_fps"], "frame_age_seconds": round(age, 2) if age is not None else None,
            "pts_interval_stats": (capture or {}).get("pts_interval_stats"),
            "pts_discontinuities_this_capture": (capture or {}).get("pts_discontinuities", 0),
            "source_pts": camera["source_pts"], "pts_timebase": camera["pts_timebase"],
            "stream_generation": camera["stream_generation"],
            "capture_errors": errors["count"] if errors else 0,
            "last_capture_error": errors["last_kind"] if errors else None,
            "recent_reconnect_or_health_events": events,
            "analysis_queue_age_ms": queue_age,
            "decoded_frame_ready": decoded,
            "media_timing_ready": pts,
            "shared_utc_verified": clock_verified,
            "mapping": recent_mapping,
            "cross_camera_travel_time": "eligible_for_review" if decoded and pts and clock_precise_enough else "blocked_approximate_only",
            "readiness": "ready" if decoded and pts and analysis.get("running") and (queue_age is None or queue_age <= 2000) else "limited",
            "reasons": reasons,
            "meaning": "Rules on observed telemetry, not a calibrated reliability probability or plate accuracy estimate.",
        }
