from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.storage.database import Database
from app.storage.intelligence import IntelligenceStore, needs_manual_review, normalize_plate
from app.vision.recognizer import PlateRead
from test_live_rtsp import FFMPEG, MEDIAMTX, free_port, stop_process, wait_port


class FixtureRecognizer:
    provider = "fixture-cpu"
    model_version = "fixture-annotated-plate-v1"

    def predict(self, frame_bgr: np.ndarray) -> list[PlateRead]:
        height, width = frame_bgr.shape[:2]
        return [PlateRead("GJ01AB1234", .96, .93, (width // 3, height // 3,
                                                    width * 2 // 3, height * 2 // 3))]


def test_persisted_sighting_evidence_watchlist_and_ambiguity(tmp_path: Path):
    db = Database(tmp_path / "grid.sqlite")
    db.migrate()
    db.import_owned({
        "camera_id": "cam1", "display_name": "Fixture", "department": "Test",
        "latitude": 23, "longitude": 72, "source_mode": "owned_replay",
        "hls_url": "http://127.0.0.1/example.m3u8",
    })
    store = IntelligenceStore(db, tmp_path / "evidence")
    store.migrate()
    assert normalize_plate("gj-01 ab 1234") == "GJ01AB1234"
    assert needs_manual_review("GJO1AB1234")
    assert not needs_manual_review("GJ01AB1234")
    entry = store.create_watchlist("GJ 01 AB 1234", "representative", "Fixture",
                                   None, "test-operator")
    image = np.full((80, 220, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    common = dict(
        camera_id="cam1", source_mode="owned_replay", pts_timebase="1/90000",
        stream_generation=1, received_utc="2026-09-28T00:00:00+00:00",
        detector_score=.96, ocr_score=.93, bbox=(0, 0, 220, 80),
        crop_jpeg=encoded.tobytes(), model_version="fixture-v1",
    )
    candidate = store.record_read(**common, source_pts=1.0, raw_text="GJ01AB1234", confirmed=False)
    assert candidate["review_status"] == "candidate"
    assert store.alerts() == []
    confirmed = store.record_read(**common, source_pts=1.5, raw_text="GJ01AB1234", confirmed=True)
    assert confirmed["id"] == candidate["id"]
    assert confirmed["read_count"] == 2
    assert confirmed["review_status"] == "confirmed"
    assert confirmed["event_utc_if_verified"] is None
    assert confirmed["timestamp_provenance"] == "source_pts_per_stream"
    assert confirmed["raw_reads"][0]["text"] == "GJ01AB1234"
    assert store.evidence(confirmed["id"]) == encoded.tobytes()
    assert len(store.alerts()) == 1
    untimed = store.record_read(**{**common, "detector_score": .99},
                                source_pts=None, raw_text="GJ01AB1234", confirmed=True)
    assert untimed["source_pts"] is not None
    assert untimed["raw_reads"][-1]["source_pts"] is None
    store.record_read(**common, source_pts=2.0, raw_text="GJ01AB1234", confirmed=True)
    assert len(store.alerts()) == 1
    ambiguous = store.record_read(**common, source_pts=3.0, raw_text="GJO1AB1234", confirmed=True)
    assert ambiguous["review_status"] == "candidate"
    assert len(store.alerts()) == 1
    store.record_read(**{**common, "stream_generation": 2}, source_pts=1.0,
                      raw_text="GJ01AB1234", confirmed=True)
    assert len(store.alerts()) == 1  # A reconnect inside the encounter is not an alert flood.
    assert store.disable_watchlist(entry["id"])
    store.record_read(**{**common, "stream_generation": 3}, source_pts=1.0,
                      raw_text="GJ01AB1234", confirmed=True)
    assert len(store.alerts()) == 1
    expiring = store.create_watchlist(
        "GJ01AB1234", "representative", "Expiring test entry",
        (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), "test-operator",
    )
    with db.connection() as connection:
        connection.execute("UPDATE watchlist SET expires_utc=? WHERE id=?", (
            (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), expiring["id"],
        ))
    store.record_read(**{**common, "stream_generation": 4}, source_pts=1.0,
                      raw_text="GJ01AB1234", confirmed=True)
    assert len(store.alerts()) == 1
    alert = store.alerts()[0]
    assert store.acknowledge_alert(alert["id"], "test-operator")
    assert [item["action"] for item in store.alert_history(alert["id"])] == [
        "created", "acknowledged",
    ]
    assert [event["kind"] for event in store.events_after(0)] == [
        "SightingCreated", "AlertCreated", "SightingCreated",
        "SightingCreated", "SightingCreated", "SightingCreated",
        "AlertAcknowledged",
    ]
    assert store.latest_event_id() == store.events_after(0)[-1]["id"]
    with Database(tmp_path / "grid.sqlite").connection() as connection:
        path = Path(connection.execute(
            "SELECT evidence_path FROM sightings WHERE id=?", (confirmed["id"],)
        ).fetchone()[0])
    path.write_bytes(b"tampered")
    assert store.evidence(confirmed["id"]) is None
    restarted = IntelligenceStore(Database(tmp_path / "grid.sqlite"), tmp_path / "evidence")
    assert restarted.sightings("GJ01AB1234")[0]["id"] == confirmed["id"] or any(
        item["id"] == confirmed["id"] for item in restarted.sightings("GJ01AB1234")
    )


@pytest.mark.skipif(not MEDIAMTX.exists() or FFMPEG is None,
                    reason="Owned RTSP fixture requires MediaMTX and FFmpeg")
def test_real_decoded_feed_reaches_bounded_analyzer_and_alert(tmp_path: Path):
    port = free_port()
    config = tmp_path / "mediamtx.yml"
    config.write_text(
        f"rtsp: true\nrtspAddress: 127.0.0.1:{port}\n"
        "rtmp: false\nhls: false\nwebrtc: false\nsrt: false\nmoq: false\n"
        "paths:\n  owned:\n    source: publisher\n", encoding="utf-8",
    )
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    relay_log = (tmp_path / "relay.log").open("wb")
    publisher_log = (tmp_path / "publisher.log").open("wb")
    relay = subprocess.Popen([str(MEDIAMTX), str(config)], cwd=tmp_path,
                             stdout=relay_log, stderr=subprocess.STDOUT, creationflags=flags)
    publisher = None
    try:
        wait_port(port)
        url = f"rtsp://127.0.0.1:{port}/owned"
        publisher = subprocess.Popen([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-re", "-f", "lavfi",
            "-i", "testsrc=size=640x360:rate=12", "-c:v", "libx264",
            "-preset", "ultrafast", "-tune", "zerolatency", "-g", "12",
            "-pix_fmt", "yuv420p", "-f", "rtsp", "-rtsp_transport", "tcp", url,
        ], stdout=publisher_log, stderr=subprocess.STDOUT, creationflags=flags)
        settings = Settings(tmp_path / "grid.sqlite", "test-operator-key-123",
                            idle_capture_seconds=.3, evidence_dir=tmp_path / "evidence",
                            models_dir=tmp_path / "models")
        app = create_app(settings)
        app.state.analytics.factory = FixtureRecognizer
        with TestClient(app) as client:
            token = client.post("/api/v1/auth/login", json={
                "operator_key": "test-operator-key-123",
            }).json()["csrf_token"]
            csrf = {"X-CSRF-Token": token}
            client.post("/api/v1/cameras/import", headers=csrf, json=[{
                "camera_id": "owned", "display_name": "Owned annotated stream",
                "latitude": 23, "longitude": 72, "source_mode": "owned_live",
                "rtsp_url": url,
            }]).raise_for_status()
            client.post("/api/v1/watchlist", headers=csrf, json={
                "plate": "GJ01AB1234", "source_label": "Test fixture",
            }).raise_for_status()
            assert client.get("/api/v1/sightings").status_code == 200
            assert client.post("/api/v1/cameras/owned/analysis",
                               json={"sample_fps": 4}).status_code == 403
            client.post("/api/v1/cameras/owned/analysis", headers=csrf,
                        json={"sample_fps": 4}).raise_for_status()
            until = time.monotonic() + 12
            while time.monotonic() < until and not client.get("/api/v1/alerts").json():
                time.sleep(.2)
            alerts = client.get("/api/v1/alerts").json()
            assert len(alerts) == 1, client.get("/api/v1/cameras/owned/analysis").json()
            found = client.get("/api/v1/sightings?plate=GJ01AB1234").json()
            assert found[0]["camera_id"] == "owned"
            assert found[0]["source_pts"] is not None
            assert found[0]["review_status"] == "confirmed"
            assert client.get(found[0]["evidence_url"]).content.startswith(b"\xff\xd8")
            status = client.get("/api/v1/cameras/owned/analysis").json()
            assert status["analyzed"] >= 2
            assert status["execution_provider"] == "fixture-cpu"
            assert client.get("/api/v1/metrics").json()["concurrently_analyzed"] == 1
            client.delete("/api/v1/cameras/owned/analysis", headers=csrf).raise_for_status()
            assert client.get("/api/v1/metrics").json()["concurrently_analyzed"] == 0
        with TestClient(create_app(settings)) as client:
            client.post("/api/v1/auth/login", json={"operator_key": "test-operator-key-123"})
            assert len(client.get("/api/v1/alerts").json()) == 1
            assert client.get("/api/v1/sightings?plate=GJ01AB1234").json()
    finally:
        stop_process(publisher)
        stop_process(relay)
        publisher_log.close()
        relay_log.close()
