"""Module 4 integration: measured scheduling, worker ack, ledger, and PDF."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.config import Settings
from app.main import create_app
from app.storage.database import utc_now


class AcknowledgingFixtureWorker:
    """A worker double that acknowledges applied rates and uses persisted counters."""
    max_cameras = 4

    def __init__(self, store):
        self.store = store
        self.active = {}

    def start(self, camera_id, sample_fps):
        self.active[camera_id] = sample_fps
        self.store.set_analysis(camera_id, True, sample_fps)

    def stop(self, camera_id):
        self.active.pop(camera_id, None)
        self.store.set_analysis(camera_id, False, self.store.analysis_status(camera_id)["sample_fps"])

    def status(self, camera_id):
        status = self.store.analysis_status(camera_id)
        status.update(running=camera_id in self.active,
                      applied_fps=self.active.get(camera_id, 0),
                      acknowledged_utc=utc_now() if camera_id in self.active else None)
        return status


def _read(app, camera_id, *, confirmed=True):
    image = np.full((70, 220, 3), 235, np.uint8)
    cv2.putText(image, "GJ01AB1234", (5, 43), cv2.FONT_HERSHEY_SIMPLEX,
                .57, (22, 37, 52), 2)
    okay, encoded = cv2.imencode(".jpg", image)
    assert okay
    return app.state.intelligence.record_read(
        camera_id=camera_id, source_mode="owned_replay", source_pts=time.monotonic(),
        pts_timebase="1/90000", stream_generation=1, received_utc=utc_now(),
        raw_text="GJ01AB1234", detector_score=.96, ocr_score=.92,
        bbox=(0, 0, 220, 70), crop_jpeg=encoded.tobytes(),
        model_version="owned-annotated-test", confirmed=confirmed,
    )


def test_schedule_reacts_to_confirmed_evidence_and_ledger_has_four_states(tmp_path: Path):
    settings = Settings(tmp_path / "grid.sqlite", "operator-test-key-12345",
                        evidence_dir=tmp_path / "evidence")
    app = create_app(settings)
    with TestClient(app) as client:
        fake = AcknowledgingFixtureWorker(app.state.intelligence)
        app.state.active_pursuit.analytics = fake
        auth = client.post("/api/v1/auth/login", json={"operator_key": settings.operator_key}).json()
        headers = {"X-CSRF-Token": auth["csrf_token"]}
        cameras = [("origin", 23.00, 72.50), ("next", 23.02, 72.52),
                   ("negative", 23.03, 72.53), ("offline", 23.04, 72.54),
                   ("far", 23.50, 73.00)]
        response = client.post("/api/v1/cameras/import", headers=headers, json=[{
            "camera_id": camera_id, "display_name": camera_id.title(),
            "department": "Owned test", "latitude": lat, "longitude": lon,
            "source_mode": "owned_replay", "hls_url": "http://127.0.0.1/owned.m3u8",
            "width": 1280, "height": 720, "codec": "h264",
        } for camera_id, lat, lon in cameras])
        response.raise_for_status()
        for camera_id, _, _ in cameras:
            app.state.database.update_health(camera_id, "online")
        origin = _read(app, "origin")
        pursuit = client.post("/api/v1/pursuits", headers=headers,
                              json={"plate": "GJ01AB1234"}).json()
        identifier = pursuit["id"]
        before = client.get(f"/api/v1/pursuits/{identifier}/rankings").json()
        assert before == client.get(f"/api/v1/pursuits/{identifier}/rankings").json()
        assert before["latest_confirmed_sighting_id"] == origin["id"]
        assert before["score_meaning"].endswith("not a route probability")
        assert client.post(f"/api/v1/pursuits/{identifier}/schedule", headers=headers).status_code == 409
        measurement = client.post("/api/v1/capacity/measurements", headers=headers, json={
            "duration_seconds": 10, "feed_count": 1,
            "decoded_frames": 120, "analyzed_frames": 100,
            "codec": "h264", "resolution": "1280x720",
            "model_provider": "fixture-cpu", "source_mode": "owned_replay",
            "method": "Ten second measured owned replay fixture",
            "evidence_note": "Synthetic counters for deterministic schedule integration only",
        })
        measurement.raise_for_status()
        assert measurement.json()["budget_fps"] == 7
        schedule = client.post(f"/api/v1/pursuits/{identifier}/schedule", headers=headers)
        schedule.raise_for_status()
        first = schedule.json()
        assert first["active"] and first["schedule"]["revision"] == 1
        assert first["requested_total_fps"] <= 7
        assert all(row["applied_fps"] == row["requested_fps"]
                   for row in first["allocations"])
        assert client.post("/api/v1/cameras/next/analysis", headers=headers,
                           json={"sample_fps": 9}).status_code == 409
        assert client.post("/api/v1/cameras/far/analysis", headers=headers,
                           json={"sample_fps": 10}).status_code == 409
        # These are actual counter deltas in the fixture worker, not UI labels.
        time.sleep(2.1)
        for camera_id in ("origin", "next", "negative"):
            app.state.intelligence.update_counters(camera_id, received=12, analyzed=10)
        app.state.database.update_health("offline", "offline", "Owned replay interruption")
        _read(app, "negative", confirmed=False)
        app.state.active_pursuit.tick(identifier)
        unchanged = client.get(f"/api/v1/pursuits/{identifier}/schedule").json()
        assert unchanged["schedule"]["revision"] == 1
        assert unchanged["schedule"]["latest_sighting_id"] == origin["id"]
        _read(app, "next")
        ledger = client.get(f"/api/v1/pursuits/{identifier}/coverage").json()
        by_camera = {window["camera_id"]: window for window in ledger["windows"]}
        assert by_camera["next"]["result_code"] == "observed"
        assert by_camera["negative"]["result_code"] == "not observed in sampled frames"
        assert by_camera["offline"]["result_code"] == "feed unavailable"
        assert by_camera["far"]["result_code"] == "insufficient coverage"
        assert by_camera["origin"]["result_code"] == "not observed in sampled frames"
        assert by_camera["negative"]["analyzed_frames"] == 10
        assert by_camera["offline"]["applied_fps"] > 0  # Ack does not equal coverage.
        app.state.active_pursuit.tick(identifier)
        changed = client.get(f"/api/v1/pursuits/{identifier}/schedule").json()
        assert changed["schedule"]["revision"] == 2  # Confirmed next sighting drove replan.
        assert changed["schedule"]["latest_sighting_id"] != origin["id"]
        current = client.get(f"/api/v1/pursuits/{identifier}/journey").json()
        assert current["coverage"]["windows"]
        report = client.get(f"/api/v1/pursuits/{identifier}/report")
        report.raise_for_status()
        text = "\n".join(page.extract_text() or "" for page in
                         PdfReader(BytesIO(report.content)).pages)
        assert "Coverage Integrity Ledger" in text
        assert "Feed unavailable" in text or "feed unavailable" in text
        # Sustained inference latency must visibly shed load, not accumulate a queue.
        stressed_camera = next(row["camera_id"] for row in changed["allocations"]
                               if row["requested_fps"] > 0)
        app.state.intelligence.update_counters(stressed_camera, latency_ms=10_000)
        app.state.active_pursuit.tick(identifier)
        app.state.active_pursuit.tick(identifier)
        shed = client.get(f"/api/v1/pursuits/{identifier}/schedule").json()
        assert shed["schedule"]["revision"] == 3
        assert "load shed" in shed["schedule"]["reason"]
        assert shed["requested_total_fps"] < changed["requested_total_fps"]
        stopped = client.delete(f"/api/v1/pursuits/{identifier}/schedule", headers=headers)
        stopped.raise_for_status()
        assert stopped.json()["active"] is False
        frozen = client.get(f"/api/v1/pursuits/{identifier}/coverage").json()
        old = next(window for window in frozen["windows"]
                   if window["revision"] == 1 and window["camera_id"] == "negative")
        app.state.intelligence.update_counters("negative", received=100, analyzed=100)
        app.state.database.update_health("negative", "offline", "Later outage")
        again = client.get(f"/api/v1/pursuits/{identifier}/coverage").json()
        after = next(window for window in again["windows"]
                     if window["revision"] == 1 and window["camera_id"] == "negative")
        assert (old["received_frames"], old["analyzed_frames"], old["health"]) == (
            after["received_frames"], after["analyzed_frames"], after["health"]
        )
        app.state.intelligence.update_counters("next", queue_age_ms=1000)
        measured_rank = client.get(f"/api/v1/pursuits/{identifier}/rankings").json()
        next_camera = next(item for item in measured_rank["rankings"]
                           if item["camera_id"] == "next")
        assert next_camera["factors"]["queue_age_ms"] == 1000
        assert next_camera["factors"]["queue_delay_proxy"] == .2


def test_capacity_measurement_rejects_unmeasured_or_inconsistent_counts(tmp_path: Path):
    app = create_app(Settings(tmp_path / "x.sqlite", "operator-test-key-12345"))
    with TestClient(app) as client:
        auth = client.post("/api/v1/auth/login", json={"operator_key": "operator-test-key-12345"}).json()
        headers = {"X-CSRF-Token": auth["csrf_token"]}
        body = {"duration_seconds": 20, "feed_count": 1,
                "decoded_frames": 2, "analyzed_frames": 5, "codec": "h264",
                "resolution": "1280x720", "model_provider": "CPUExecutionProvider",
                "source_mode": "owned_replay", "method": "Measured owned stream end to end",
                "evidence_note": "Counter pair is inconsistent and must be rejected"}
        assert client.post("/api/v1/capacity/measurements", headers=headers,
                           json=body).status_code == 400
