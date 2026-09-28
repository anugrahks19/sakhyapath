"""Module 3's deterministic owned three-camera history and access gates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.config import Settings
from app.main import create_app


BASE = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)
PLATE = "GJ01AB1234"


def fixture_jpeg(text: str) -> bytes:
    frame = np.full((100, 370, 3), 245, dtype=np.uint8)
    cv2.putText(frame, text, (12, 65), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (20, 20, 20), 2, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    return encoded.tobytes()


def login(client: TestClient, key: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"operator_key": key})
    response.raise_for_status()
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_custom_database_uses_matching_private_storage(monkeypatch, tmp_path: Path):
    database_path = tmp_path / "custom.sqlite3"
    monkeypatch.setenv("SAKHYAPATH_OPERATOR_KEY", "test-operator-key-12345")
    monkeypatch.setenv("SAKHYAPATH_DB", str(database_path))
    monkeypatch.delenv("SAKHYAPATH_EVIDENCE_DIR", raising=False)
    monkeypatch.delenv("SAKHYAPATH_MODELS_DIR", raising=False)
    settings = Settings.from_environment()
    assert settings.database_path == database_path
    assert settings.evidence_dir == tmp_path / "evidence"
    assert settings.models_dir == tmp_path / "models"


def add_read(app, camera_id: str, *, plate: str = PLATE,
             generation: int = 1, pts: float = 0,
             when: datetime = BASE, confirmed: bool = True) -> dict:
    return app.state.intelligence.record_read(
        camera_id=camera_id, source_mode="owned_replay", source_pts=pts,
        pts_timebase="1/90000", stream_generation=generation,
        received_utc=when.isoformat(), raw_text=plate,
        detector_score=.97, ocr_score=.94, bbox=(0, 0, 370, 100),
        crop_jpeg=fixture_jpeg(plate), model_version="annotated-owned-fixture-v1",
        confirmed=confirmed,
    )


def test_three_camera_journey_report_reviews_integrity_and_department_scope(tmp_path: Path):
    settings = Settings(tmp_path / "grid.sqlite", "operator-test-key-12345",
                        evidence_dir=tmp_path / "evidence",
                        department_keys={"Traffic A": "traffic-a-test-key-12345",
                                         "Traffic B": "traffic-b-test-key-12345"})
    app = create_app(settings)
    with TestClient(app) as client:
        operator = login(client, settings.operator_key)
        cameras = [
            ("north", "Traffic A", 23.02, 72.57),
            ("middle", "Traffic A", 23.07, 72.62),
            ("south", "Traffic A", 23.12, 72.67),
            ("far", "Traffic A", 28.61, 77.20),
            ("private-b", "Traffic B", 22.30, 73.20),
        ]
        client.post("/api/v1/cameras/import", headers=operator, json=[{
            "camera_id": camera_id, "display_name": camera_id.title(),
            "department": department, "latitude": lat, "longitude": lon,
            "source_mode": "owned_replay", "hls_url": "http://127.0.0.1/fixture.m3u8",
        } for camera_id, department, lat, lon in cameras]).raise_for_status()
        for camera_id, offset in (("north", 0), ("middle", 5), ("south", 10)):
            read = add_read(app, camera_id, pts=30,
                            when=BASE + timedelta(minutes=offset))
            mapping = client.post(f"/api/v1/cameras/{camera_id}/time-mappings",
                                  headers=operator, json={
                                      "stream_generation": 1, "pts_anchor": 30,
                                      "utc_anchor": (BASE + timedelta(minutes=offset)).isoformat(),
                                      "uncertainty_ms": 100, "basis": "owned_recording_clock_attested",
                                      "evidence_note": "Controlled recording start clock in owned fixture",
                                  })
            mapping.raise_for_status()
            assert read["source_pts"] == 30
        private = add_read(app, "private-b", when=BASE + timedelta(minutes=3))
        search = client.post("/api/v1/pursuits", headers=operator,
                             json={"plate": "gj-01 ab 1234"})
        search.raise_for_status()
        pursuit_id = search.json()["id"]
        initial = client.get(f"/api/v1/pursuits/{pursuit_id}/journey").json()
        assert initial["counts"]["observations"] == 4  # Operator can see both departments.
        assert [item["camera_id"] for item in initial["observations"] if
                item["department"] == "Traffic A"] == ["north", "middle", "south"]
        assert all(item["evidence_status"] == "verified" for item in initial["records"])

        # A broad attested clock error must not falsely label a close pair impossible.
        for camera_id, minute in (("north", 0), ("middle", 1)):
            client.post(f"/api/v1/cameras/{camera_id}/time-mappings", headers=operator, json={
                "stream_generation": 1, "pts_anchor": 30,
                "utc_anchor": (BASE + timedelta(minutes=minute)).isoformat(),
                "uncertainty_ms": 60000, "basis": "owned_recording_clock_attested",
                "evidence_note": "Controlled wide uncertainty fixture for conservative speed check",
            }).raise_for_status()
        wide_clock = client.get(f"/api/v1/pursuits/{pursuit_id}/journey").json()
        first_link = next(link for link in wide_clock["links"] if
                          link["from_camera_id"] == "north" and link["to_camera_id"] == "middle")
        assert first_link["status"] == "possible_inferred"
        assert first_link["duration_uncertainty_seconds"] == 120
        for camera_id, minute in (("north", 0), ("middle", 5)):
            client.post(f"/api/v1/cameras/{camera_id}/time-mappings", headers=operator, json={
                "stream_generation": 1, "pts_anchor": 30,
                "utc_anchor": (BASE + timedelta(minutes=minute)).isoformat(),
                "uncertainty_ms": 100, "basis": "owned_recording_clock_attested",
                "evidence_note": "Controlled recording start clock in owned fixture",
            }).raise_for_status()

        reviewer = login(client, "traffic-a-test-key-12345")
        assert client.get("/api/v1/cameras").json() and all(
            item["department"] == "Traffic A" for item in client.get("/api/v1/cameras").json()
        )
        assert client.get(private["evidence_url"]).status_code == 404
        assert client.get(f"/api/v1/pursuits/{pursuit_id}/report").status_code == 404
        assert client.post("/api/v1/cameras/import", headers=reviewer, json=[]).status_code == 403
        own = client.post("/api/v1/pursuits", headers=reviewer,
                          json={"plate": PLATE})
        own.raise_for_status()
        own_id = own.json()["id"]
        journey = client.get(f"/api/v1/pursuits/{own_id}/journey").json()
        assert journey["counts"] == {"records": 3, "observations": 3,
                                     "candidates": 0, "rejected": 0}
        assert [item["camera_id"] for item in journey["observations"]] == [
            "north", "middle", "south",
        ]
        assert all(item["timestamp_provenance"] == "owned_recording_clock_attested"
                   and item["event_utc_if_verified"] for item in journey["records"])
        assert all(link["status"] == "possible_inferred" for link in journey["links"])
        filtered = client.get("/api/v1/sightings", params={
            "plate": PLATE, "camera_id": "middle", "review_status": "confirmed",
            "from_utc": (BASE + timedelta(minutes=4)).isoformat(),
            "to_utc": (BASE + timedelta(minutes=6)).isoformat(),
        })
        assert filtered.status_code == 200
        assert [item["camera_id"] for item in filtered.json()] == ["middle"]
        assert client.get("/api/v1/sightings", params={
            "from_utc": "2026-09-28T06:00:00"
        }).status_code == 422
        report = client.get(f"/api/v1/pursuits/{own_id}/report")
        assert report.status_code == 200 and report.content.startswith(b"%PDF")
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report.content)).pages)
        for camera_id in ("north", "middle", "south"):
            assert camera_id in text
        assert PLATE in text and "Dashed inference only" in text
        assert "private-b" not in text

        # A wrong read is reviewable, then excluded without destroying its crop.
        candidate = add_read(app, "middle", generation=2, pts=3,
                             when=BASE + timedelta(minutes=7), confirmed=False)
        assert client.get(f"/api/v1/pursuits/{own_id}/journey").json()["counts"]["candidates"] == 1
        client.post(f"/api/v1/sightings/{candidate['id']}/review", headers=reviewer,
                    json={"decision": "rejected", "note": "Annotated false positive"}).raise_for_status()
        after_reject = client.get(f"/api/v1/pursuits/{own_id}/journey").json()
        assert after_reject["counts"]["rejected"] == 1
        assert after_reject["counts"]["observations"] == 3
        assert client.get(candidate["evidence_url"]).content.startswith(b"\xff\xd8")
        assert app.state.intelligence.sighting(candidate["id"])["review_status"] == "candidate"
        rejected_record = next(item for item in after_reject["records"] if item["id"] == candidate["id"])
        assert rejected_record["event_utc_if_verified"] is None
        assert rejected_record["display_time_is_approximate"]
        assert "Cross-camera clock alignment unverified" in " ".join(after_reject["gaps"])

        # Corrected OCR enters the target query, but never fabricates an alert.
        corrected = add_read(app, "south", plate="GJO1AB1234", generation=2, pts=4,
                             when=BASE + timedelta(minutes=12), confirmed=False)
        client.post(f"/api/v1/sightings/{corrected['id']}/review", headers=reviewer,
                    json={"decision": "confirmed", "corrected_plate": PLATE,
                          "note": "Manually matched annotated registration"}).raise_for_status()
        after_correct = client.get(f"/api/v1/pursuits/{own_id}/journey").json()
        assert after_correct["counts"]["observations"] == 4
        assert any(item["id"] == corrected["id"] and item["effective_plate"] == PLATE
                   and item["plate_normalized"] == "GJO1AB1234"
                   for item in after_correct["records"])
        assert client.get("/api/v1/alerts").json() == []
        assert len(client.get(f"/api/v1/sightings/{corrected['id']}/review-history").json()) == 1

        # An attested 500+ km jump in one minute is flagged, not drawn as a road.
        far = add_read(app, "far", pts=60, when=BASE + timedelta(minutes=11))
        operator = login(client, settings.operator_key)
        client.post("/api/v1/cameras/far/time-mappings", headers=operator, json={
            "stream_generation": 1, "pts_anchor": 60,
            "utc_anchor": (BASE + timedelta(minutes=11)).isoformat(),
            "uncertainty_ms": 100, "basis": "owned_recording_clock_attested",
            "evidence_note": "Controlled recording start clock in owned fixture",
        }).raise_for_status()
        reviewer = login(client, "traffic-a-test-key-12345")
        with_jump = client.get(f"/api/v1/pursuits/{own_id}/journey").json()
        assert any(link["status"] == "implausible" for link in with_jump["links"])
        assert all(link["line_style"] == "dashed" for link in with_jump["links"])

        # Tampered evidence is visible in the audit record but loses map support.
        with app.state.database.connection() as connection:
            path = Path(connection.execute(
                "SELECT evidence_path FROM sightings WHERE id=?", (far["id"],)
            ).fetchone()[0])
        path.write_bytes(b"tampered")
        assert client.get(far["evidence_url"]).status_code == 409
        after_tamper = client.get(f"/api/v1/pursuits/{own_id}/journey").json()
        assert any(item["id"] == far["id"] and item["evidence_status"] == "hash_mismatch"
                   for item in after_tamper["records"])
        assert all(item["id"] != far["id"] for item in after_tamper["observations"])
        tampered_report = client.get(f"/api/v1/pursuits/{own_id}/report")
        assert b"%PDF" == tampered_report.content[:4]
        tampered_text = "\n".join(page.extract_text() or "" for page in
                                  PdfReader(BytesIO(tampered_report.content)).pages)
        assert "hash_mismatch" in tampered_text
        assert "excluded from supported map observations" in tampered_text
        path.unlink()
        missing = client.get(f"/api/v1/pursuits/{own_id}/journey").json()
        assert any(item["id"] == far["id"] and item["evidence_status"] == "missing"
                   for item in missing["records"])
    with TestClient(create_app(settings)) as restarted:
        login(restarted, "traffic-a-test-key-12345")
        restored = restarted.get(f"/api/v1/pursuits/{own_id}/journey")
        assert restored.status_code == 200
        assert any(item["id"] == corrected["id"] for item in restored.json()["records"])
        assert restarted.get(f"/api/v1/pursuits/{own_id}/report").status_code == 200
