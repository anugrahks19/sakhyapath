"""Police case workflow: review gates, scoped inbox, evidence and restart persistence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.proof import SearchProof


OPERATOR = "case-operator-test-key-123456"
WEST = "west-department-key-123456"
EAST = "east-department-key-123456"


def auth(client, key):
    response = client.post("/api/v1/auth/login", json={"operator_key": key})
    response.raise_for_status()
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def camera(camera_id, department, latitude):
    return {"camera_id": camera_id, "display_name": camera_id,
            "department": department, "latitude": latitude, "longitude": 72.57,
            "source_mode": "owned_replay", "hls_url": "http://127.0.0.1/owned.m3u8"}


def case_body(reference="CASE-001", plate="GJ01AB1234"):
    return {"reference": reference, "kind": "hit_and_run", "priority": "urgent",
            "plate_query": plate, "query_mode": "partial" if plate == "AB12" else "exact",
            "vehicle_description": "White test vehicle",
            "incident_latitude": 23.02, "incident_longitude": 72.57,
            "incident_utc": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "lead_department": "West"}


def read(app, plate, confirmed):
    return app.state.intelligence.record_read(
        camera_id="west-1", source_mode="owned_replay", source_pts=1.0,
        pts_timebase="1/90000", stream_generation=1,
        received_utc=datetime.now(timezone.utc).isoformat(), raw_text=plate,
        detector_score=.95, ocr_score=.95, bbox=(0, 0, 100, 30),
        crop_jpeg=b"owned-test-evidence", model_version="owned-test-model",
        confirmed=confirmed,
    )


def test_casebridge_end_to_end_and_restart(tmp_path):
    settings = Settings(tmp_path / "case.sqlite", OPERATOR,
                        department_keys={"West": WEST, "East": EAST},
                        evidence_dir=tmp_path / "evidence", proof_key_path=tmp_path / "proof.pem")
    app = create_app(settings)
    with TestClient(app) as client:
        operator = auth(client, OPERATOR)
        created = client.post("/api/v1/cameras/import", headers=operator,
                              json=[camera("west-1", "West", 23.02),
                                    camera("east-1", "East", 23.08)])
        created.raise_for_status()
        case_response = client.post("/api/v1/cases", headers=operator, json=case_body())
        case_response.raise_for_status()
        case_id = case_response.json()["id"]
        assert client.post("/api/v1/cases", headers=operator, json=case_body()).status_code == 409
        detail = client.get(f"/api/v1/cases/{case_id}").json()
        assert detail["camera_plan"]["unavailable_or_unverified"]
        assert detail["evidence"]["confirmed"] == []
        assert client.post("/api/v1/cases", headers=operator,
                           json={**case_body("BAD-WINDOW"), "search_until_utc": "2020-01-01T00:00:00Z"}).status_code == 422

        candidate = read(app, "GJ01AB1234", False)
        denied = client.post(f"/api/v1/cases/{case_id}/handoffs", headers=operator,
                             json={"recipient_department": "East", "sighting_id": candidate["id"],
                                   "note": "Review this case sighting"})
        assert denied.status_code == 409
        assert client.post(f"/api/v1/cases/{case_id}/pursuit?sighting_id={candidate['id']}",
                           headers=operator).status_code == 409

        confirmed = read(app, "GJ01AB1234", True)
        assert confirmed["id"] == candidate["id"]
        detail = client.get(f"/api/v1/cases/{case_id}").json()
        assert detail["evidence"]["confirmed"][0]["evidence_status"] == "verified"
        client.post("/api/v1/watchlist", headers=operator,
                    json={"plate": "GJ01AB1234", "category": "representative",
                          "source_label": "CaseBridge owned test"}).raise_for_status()
        assert client.get(f"/api/v1/cases/{case_id}").json()["representative_watchlist"]
        assert client.get("/api/v1/cases/shift-briefing").json()["open_cases"][0]["last_confirmed"]
        sent = client.post(f"/api/v1/cases/{case_id}/handoffs", headers=operator,
                           json={"recipient_department": "East", "sighting_id": confirmed["id"],
                                 "note": "Please inspect the next authorised camera"})
        sent.raise_for_status()
        handoff_id = sent.json()["id"]
        assert "owned.m3u8" not in str(sent.json())
        assert sent.json()["packet"]["suggested_cameras"][0]["camera_id"] == "east-1"
        pursuit = client.post(f"/api/v1/cases/{case_id}/pursuit?sighting_id={confirmed['id']}",
                              headers=operator)
        pursuit.raise_for_status()
        assert client.get(f"/api/v1/cases/{case_id}").json()["case"]["pursuit_id"] == pursuit.json()["id"]
        assert client.post(f"/api/v1/cases/{case_id}/notes", headers=operator,
                           json={"note": "Pass to next shift"}).status_code == 200

        # Operator cannot impersonate the recipient; other departments cannot read its inbox.
        assert client.post(f"/api/v1/cases/handoffs/{handoff_id}/acknowledge", headers=operator,
                           json={"note": "Received"}).status_code == 403
        client.post("/api/v1/auth/logout", headers=operator).raise_for_status()
        west = auth(client, WEST)
        assert client.get("/api/v1/cases/inbox").json() == []
        assert client.get(f"/api/v1/cases/{case_id}").status_code == 403
        assert client.post(f"/api/v1/cases/handoffs/{handoff_id}/acknowledge", headers=west,
                           json={"note": "Received"}).status_code == 404
        client.post("/api/v1/auth/logout", headers=west).raise_for_status()
        east = auth(client, EAST)
        assert len(client.get("/api/v1/cases/inbox").json()) == 1
        acknowledged = client.post(f"/api/v1/cases/handoffs/{handoff_id}/acknowledge",
                                   headers=east, json={"note": "District desk received and will review"})
        acknowledged.raise_for_status()
        assert acknowledged.json()["status"] == "acknowledged"
        assert client.post(f"/api/v1/cases/handoffs/{handoff_id}/acknowledge", headers=east,
                           json={"note": "Repeat"}).status_code == 409
        client.post("/api/v1/auth/logout", headers=east).raise_for_status()
        operator = auth(client, OPERATOR)
        signed = client.post(f"/api/v1/cases/{case_id}/timeline", headers=operator)
        signed.raise_for_status()
        envelope = signed.json()
        assert SearchProof.verify(envelope)
        assert any(event["kind"] == "handoff_acknowledged" for event in envelope["payload"]["events"])
        snapshot_id = envelope["payload"]["snapshot_id"]
        assert client.get(f"/api/v1/cases/{case_id}/timeline/{snapshot_id}").json() == envelope
        assert client.get(f"/api/v1/cases/{case_id}/timeline/{snapshot_id}/verify").json()["signature_valid"]
        assert client.put(f"/api/v1/cases/{case_id}/status", headers=operator,
                          json={"status": "closed", "note": "Case closed after desk review"}).status_code == 200
        assert client.post(f"/api/v1/cases/{case_id}/handoffs", headers=operator,
                           json={"recipient_department": "East", "sighting_id": confirmed["id"],
                                 "note": "Do not send closed case"}).status_code == 409
    with TestClient(create_app(settings)) as client:
        auth(client, OPERATOR)
        assert client.get(f"/api/v1/cases/{case_id}").json()["case"]["status"] == "closed"
        assert SearchProof.verify(client.get(f"/api/v1/cases/{case_id}/timeline/{snapshot_id}").json())


def test_partial_plate_is_triage_only(tmp_path):
    settings = Settings(tmp_path / "partial.sqlite", OPERATOR, evidence_dir=tmp_path / "evidence")
    app = create_app(settings)
    with TestClient(app) as client:
        operator = auth(client, OPERATOR)
        client.post("/api/v1/cameras/import", headers=operator,
                    json=[camera("west-1", "West", 23.02), camera("east-1", "East", 23.08)]).raise_for_status()
        response = client.post("/api/v1/cases", headers=operator, json=case_body("PARTIAL", "AB12"))
        response.raise_for_status()
        case_id = response.json()["id"]
        read(app, "GJ01AB1234", False)
        read(app, "GJ99ZZ9999", False)
        verified = []
        original_status = app.state.journeys._evidence_status
        def checked_status(row):
            verified.append(row["plate_normalized"])
            return original_status(row)
        app.state.journeys._evidence_status = checked_status
        detail = client.get(f"/api/v1/cases/{case_id}").json()
        assert detail["evidence"]["partial_query"]
        assert len(detail["evidence"]["candidates"]) == 1
        assert detail["evidence"]["confirmed"] == []
        assert verified == ["GJ01AB1234"]


def test_old_or_hash_mismatched_evidence_cannot_be_handed_off(tmp_path):
    settings = Settings(tmp_path / "integrity.sqlite", OPERATOR, evidence_dir=tmp_path / "evidence")
    app = create_app(settings)
    with TestClient(app) as client:
        operator = auth(client, OPERATOR)
        client.post("/api/v1/cameras/import", headers=operator,
                    json=[camera("west-1", "West", 23.02), camera("east-1", "East", 23.08)]).raise_for_status()
        sighting = read(app, "GJ01AB1234", True)
        future_case = client.post("/api/v1/cases", headers=operator,
                                  json={**case_body("FUTURE"),
                                        "incident_utc": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
        future_case.raise_for_status()
        assert client.get(f"/api/v1/cases/{future_case.json()['id']}").json()["evidence"]["confirmed"] == []
        active_case = client.post("/api/v1/cases", headers=operator, json=case_body("TAMPER"))
        active_case.raise_for_status()
        with app.state.database.connection() as connection:
            evidence_path = connection.execute("SELECT evidence_path FROM sightings WHERE id=?",
                                               (sighting["id"],)).fetchone()["evidence_path"]
        from pathlib import Path
        Path(evidence_path).write_bytes(b"tampered")
        detail = client.get(f"/api/v1/cases/{active_case.json()['id']}").json()
        assert detail["evidence"]["confirmed"] == []
        response = client.post(f"/api/v1/cases/{active_case.json()['id']}/handoffs", headers=operator,
                               json={"recipient_department": "East", "sighting_id": sighting["id"],
                                     "note": "Review this tampered sighting"})
        assert response.status_code == 409
