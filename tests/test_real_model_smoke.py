"""Optional local smoke test using FastALPR's official sample image.

The sample is intentionally kept in ignored backend/data; this test does not
measure Indian-plate accuracy and is skipped when that image is absent.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from test_live_rtsp import FFMPEG, MEDIAMTX, free_port, stop_process, wait_port

SAMPLE = Path(__file__).resolve().parents[1] / "backend/data/fastalpr_sample.png"


@pytest.mark.skipif(not SAMPLE.exists() or not MEDIAMTX.exists() or FFMPEG is None,
                    reason="Official sample, local MediaMTX, and FFmpeg required")
def test_real_fastalpr_frame_to_alert(tmp_path: Path):
    port = free_port()
    config = tmp_path / "mediamtx.yml"
    config.write_text(
        f"rtsp: true\nrtspAddress: 127.0.0.1:{port}\n"
        "rtmp: false\nhls: false\nwebrtc: false\nsrt: false\nmoq: false\n"
        "paths:\n  sample:\n    source: publisher\n", encoding="utf-8",
    )
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    relay_log = (tmp_path / "relay.log").open("wb")
    publisher_log = (tmp_path / "publisher.log").open("wb")
    relay = subprocess.Popen([str(MEDIAMTX), str(config)], cwd=tmp_path,
                             stdout=relay_log, stderr=subprocess.STDOUT, creationflags=flags)
    publisher = None
    try:
        wait_port(port)
        url = f"rtsp://127.0.0.1:{port}/sample"
        publisher = subprocess.Popen([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-re", "-loop", "1",
            "-framerate", "5", "-i", str(SAMPLE), "-vf",
            "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset",
            "ultrafast", "-tune", "zerolatency", "-g", "10", "-pix_fmt", "yuv420p",
            "-f", "rtsp", "-rtsp_transport", "tcp", url,
        ], stdout=publisher_log, stderr=subprocess.STDOUT, creationflags=flags)
        settings = Settings(
            tmp_path / "grid.sqlite", "test-operator-key-123", idle_capture_seconds=.3,
            evidence_dir=tmp_path / "evidence",
            models_dir=SAMPLE.parent / "models",
        )
        with TestClient(create_app(settings)) as client:
            csrf = {"X-CSRF-Token": client.post("/api/v1/auth/login", json={
                "operator_key": "test-operator-key-123",
            }).json()["csrf_token"]}
            client.post("/api/v1/cameras/import", headers=csrf, json=[{
                "camera_id": "sample-replay", "display_name": "FastALPR official sample",
                "latitude": 23, "longitude": 72, "source_mode": "owned_replay",
                "rtsp_url": url,
            }]).raise_for_status()
            client.post("/api/v1/watchlist", headers=csrf, json={
                "plate": "5AU5341", "category": "representative",
                "source_label": "Official model sample, not Government data",
            }).raise_for_status()
            client.post("/api/v1/cameras/sample-replay/analysis", headers=csrf,
                        json={"sample_fps": 2}).raise_for_status()
            until = time.monotonic() + 20
            while time.monotonic() < until and not client.get("/api/v1/alerts").json():
                time.sleep(.25)
            alerts = client.get("/api/v1/alerts").json()
            assert len(alerts) == 1, {
                "analysis": client.get("/api/v1/cameras/sample-replay/analysis").json(),
                "publisher_log": publisher_log.name,
            }
            found = client.get("/api/v1/sightings?plate=5AU5341").json()
            confirmed = [item for item in found if item["review_status"] == "confirmed"]
            assert len(confirmed) == 1
            assert confirmed[0]["read_count"] >= 2
            assert confirmed[0]["source_pts"] is not None
            assert len(confirmed[0]["evidence_sha256"]) == 64
            assert client.get(confirmed[0]["evidence_url"]).content.startswith(b"\xff\xd8")
            search = client.post("/api/v1/pursuits", headers=csrf,
                                 json={"plate": "5AU5341"})
            search.raise_for_status()
            journey = client.get(f"/api/v1/pursuits/{search.json()['id']}/journey").json()
            assert journey["counts"]["observations"] >= 1
            assert any(item["id"] == confirmed[0]["id"] and item["evidence_status"] == "verified"
                       for item in journey["records"])
            assert client.get(f"/api/v1/pursuits/{search.json()['id']}/report").content.startswith(b"%PDF")
            status = client.get("/api/v1/cameras/sample-replay/analysis").json()
            assert status["execution_provider"] in {
                "CUDAExecutionProvider", "CPUExecutionProvider",
            }
            # Measure the same decoded owned stream for a real Module 4 budget.
            captures = client.app.state.captures
            before_frames = captures.workers["sample-replay"].frame_sequence
            before_analyzed = status["analyzed"]
            started = time.perf_counter()
            time.sleep(10.2)
            elapsed = time.perf_counter() - started
            after = client.get("/api/v1/cameras/sample-replay/analysis").json()
            assert after["last_queue_age_ms"] is not None
            decoded = captures.workers["sample-replay"].frame_sequence - before_frames
            analyzed = after["analyzed"] - before_analyzed
            assert decoded >= analyzed > 0
            measurement = client.post("/api/v1/capacity/measurements", headers=csrf,
                                      json={"duration_seconds": elapsed,
                                            "feed_count": 1,
                                            "decoded_frames": decoded,
                                            "analyzed_frames": analyzed,
                                            "codec": "h264", "resolution": "518x331",
                                            "model_provider": after["execution_provider"],
                                            "source_mode": "owned_replay",
                                            "method": "Timed owned RTSP decode and FastALPR test interval",
                                            "evidence_note": "One official sample replay; local integration smoke only"})
            measurement.raise_for_status()
            client.delete("/api/v1/cameras/sample-replay/analysis", headers=csrf).raise_for_status()
            pursuit_id = search.json()["id"]
            schedule = client.post(f"/api/v1/pursuits/{pursuit_id}/schedule", headers=csrf)
            schedule.raise_for_status()
            assert schedule.json()["requested_total_fps"] <= measurement.json()["budget_fps"]
            until = time.monotonic() + 12
            applied = None
            while time.monotonic() < until:
                applied = client.get(f"/api/v1/pursuits/{pursuit_id}/schedule").json()
                if applied["current_applied_total_fps"] > 0:
                    break
                time.sleep(.25)
            assert applied["current_applied_total_fps"] > 0
            # The replayed image is decoded continuously, but the first few
            # scheduled samples may miss OCR. Wait for an actual supported read.
            until = time.monotonic() + 12
            observed_window = None
            while time.monotonic() < until:
                ledger = client.get(f"/api/v1/pursuits/{pursuit_id}/coverage").json()
                observed_window = next((window for window in ledger["windows"]
                                        if window["result_code"] == "observed"), None)
                if observed_window:
                    break
                time.sleep(.25)
            assert observed_window, {
                "coverage": ledger,
                "analysis": client.get("/api/v1/cameras/sample-replay/analysis").json(),
            }
            observed_id = observed_window["observed_sighting_id"]
            observed = client.get(f"/api/v1/sightings/{observed_id}").json()
            assert observed["plate_normalized"] == "5AU5341"
            assert observed["review_status"] == "confirmed"
            assert observed["camera_id"] == "sample-replay"
            client.delete(f"/api/v1/pursuits/{pursuit_id}/schedule", headers=csrf).raise_for_status()
    finally:
        stop_process(publisher)
        stop_process(relay)
        relay_log.close()
        publisher_log.close()
