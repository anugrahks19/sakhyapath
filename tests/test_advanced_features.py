"""End-to-end boundaries for signed receipts, regions, outages, and trust."""
from __future__ import annotations

import copy
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from pypdf import PdfReader
from io import BytesIO

from app.config import Settings
from app.main import create_app
from app.services.proof import SearchProof
from app.services.regional import MetadataEvent, RegionalLedger, create_regional_app
import app.services.regional as regional_module
from app.services.shadow import shadow_policies
from app.storage.database import Database


KEY = "regional-test-key-123456"


def auth(client, key):
    response = client.post("/api/v1/auth/login", json={"operator_key": key})
    response.raise_for_status()
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def camera(camera_id, department):
    return {"camera_id": camera_id, "display_name": camera_id,
            "department": department, "latitude": 23.0, "longitude": 72.5,
            "source_mode": "owned_replay", "hls_url": "http://127.0.0.1/owned.m3u8"}


def test_signed_search_proof_survives_restart_and_rejects_tampering(tmp_path: Path):
    settings = Settings(tmp_path / "main.sqlite", "operator-test-key-12345")
    app = create_app(settings)
    with TestClient(app) as client:
        headers = auth(client, settings.operator_key)
        client.post("/api/v1/cameras/import", headers=headers, json=[camera("a", "Traffic")]).raise_for_status()
        pursuit = client.post("/api/v1/pursuits", headers=headers, json={"plate": "GJ01AB1234"}).json()
        unconfigured = client.post("/api/v1/federation/search", headers=headers,
                                   json={"plate": "GJ01AB1234"}).json()
        assert unconfigured["regions_queried"] == 0 and not unconfigured["complete"]
        proof = client.post(f"/api/v1/pursuits/{pursuit['id']}/proofs", headers=headers)
        proof.raise_for_status()
        receipt = proof.json()
        proof_id = receipt["payload"]["receipt_id"]
        assert SearchProof.verify(receipt)
        assert receipt["payload"]["matching_records"] == []
        assert "unsampled video" in receipt["payload"]["scope_warning"]
        assert "owned.m3u8" not in json.dumps(receipt)
        pdf = client.get(f"/api/v1/proofs/{proof_id}.pdf").content
        assert SearchProof.verify_pdf(pdf, receipt)
        pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
        assert "eligible_cameras" in pdf_text and "coverage_windows" in pdf_text
        assert "source_pts" in pdf_text and "unsampled video" in pdf_text
        altered = copy.deepcopy(receipt)
        altered["payload"]["query"]["target_plate"] = "GJ02AB1234"
        assert not SearchProof.verify(altered)
        assert not SearchProof.verify_pdf(pdf + b"tampered", receipt)
        assert client.get(f"/api/v1/proofs/{proof_id}/verify").json()["signature_valid"]
    restarted = create_app(settings)
    with TestClient(restarted) as client:
        auth(client, settings.operator_key)
        again = client.get(f"/api/v1/proofs/{proof_id}.json").json()
        assert again == receipt
        assert SearchProof.verify(again)


class LocalRegionTransport(httpx.AsyncBaseTransport):
    def __init__(self, agents):
        self.agents = agents

    async def handle_async_request(self, request):
        agent = self.agents[request.url.host]
        with TestClient(agent) as client:
            response = client.request(request.method, request.url.path,
                                      headers=dict(request.headers), content=request.content)
        return httpx.Response(response.status_code, content=response.content,
                              headers=dict(response.headers), request=request)


def test_two_isolated_regions_scope_search_and_durable_outage_replay(tmp_path: Path):
    regions = [
        {"id": "north", "url": "http://north.test", "token": KEY, "departments": ["Traffic A"]},
        {"id": "south", "url": "http://south.test", "token": KEY, "departments": ["Traffic B"]},
    ]
    agents = {
        "north.test": create_regional_app(tmp_path / "north.sqlite", "north", {"Traffic A"}, KEY),
        "south.test": create_regional_app(tmp_path / "south.sqlite", "south", {"Traffic B"}, KEY),
    }
    for name, department in (("north", "Traffic A"), ("south", "Traffic B")):
        db = Database(tmp_path / f"{name}.sqlite")
        db.import_owned(camera(name, department))
        with db.connection() as connection:
            connection.execute("""INSERT INTO sightings(id,camera_id,source_mode,stream_generation,received_utc,
                raw_text,plate_normalized,detector_score,ocr_score,review_status,model_version,
                evidence_path,evidence_sha256,bbox_json,first_seen_utc,last_seen_utc,raw_reads_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name + "-hit", name, "owned_replay", 1, datetime.now(timezone.utc).isoformat(),
                 "GJ01AB1234", "GJ01AB1234", .9, .9, "confirmed", "test",
                 "regional-only.jpg", "a" * 64, "[]", datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat(), "[]"))
    settings = Settings(tmp_path / "central.sqlite", "operator-test-key-12345",
                        department_keys={"Traffic A": "traffic-a-test-key-12345"}, regions=regions)
    central = create_app(settings, regional_transport=LocalRegionTransport(agents))
    with TestClient(central) as client:
        operator = auth(client, settings.operator_key)
        both = client.post("/api/v1/federation/search", headers=operator,
                           json={"plate": "GJ01AB1234"}).json()
        assert {hit["region_id"] for hit in both["hits"]} == {"north", "south"}
        assert "regional-only.jpg" not in json.dumps(both)
        scoped = auth(client, "traffic-a-test-key-12345")
        one = client.post("/api/v1/federation/search", headers=scoped,
                          json={"plate": "GJ01AB1234"}).json()
        assert {hit["region_id"] for hit in one["hits"]} == {"north"}
        operator = auth(client, settings.operator_key)
        south_agent = agents.pop("south.test")
        incomplete = client.post("/api/v1/federation/search", headers=operator,
                                 json={"plate": "GJ01AB1234"}).json()
        assert not incomplete["complete"] and incomplete["errors"][0]["region_id"] == "south"
        agents["south.test"] = south_agent
        with TestClient(agents["north.test"]) as agent_client:
            denied = agent_client.post("/v1/search", headers={"X-Region-Token": KEY},
                                       json={"plate": "GJ01AB1234", "department": "Traffic B"})
            assert denied.status_code == 403
            bad_payload = agent_client.post("/v1/local-events", headers={"X-Region-Token": KEY},
                json={"event_id": "event-12345", "department": "Traffic A", "kind": "feed_gap",
                      "camera_id": "north", "occurred_utc": datetime.now(timezone.utc).isoformat(),
                      "video_url": "rtsp://secret"})
            assert bad_payload.status_code == 422
        ledger = agents["north.test"].state.ledger
        north_db = Database(tmp_path / "north.sqlite")
        north_db.update_health("north", "online", pts=1, timebase="1/90000", generation=1)
        north_db.update_health("north", "degraded", detail="owned test disconnect")
        north_db.update_health("north", "online", pts=2, timebase="1/90000", generation=2)
        ledger.capture_local_changes({"Traffic A"})
        assert ledger.status()["pending_metadata"] >= 1
        with north_db.connection() as connection:
            kinds = {json.loads(row["payload_json"])["kind"] for row in connection.execute("SELECT payload_json FROM regional_outbox")}
        assert {"sighting", "feed_gap", "feed_restored"} <= kinds
        failed = ledger.flush(lambda _: False)
        assert failed["delivered_now"] == 0 and failed["pending_metadata"] >= 1
        def deliver(payload):
            response = client.post("/api/v1/regions/north/events",
                                   headers={"X-Region-Token": KEY}, json=payload)
            response.raise_for_status()
            return response.json()["accepted"]
        recovered = ledger.flush(deliver)
        assert recovered["pending_metadata"] == 0
        assert recovered["delivered_now"] >= 1
        delivered_kinds = {event["kind"] for event in client.get("/api/v1/regions/events").json()["events"]}
        assert {"sighting", "feed_gap", "feed_restored"} <= delivered_kinds
        repeat = client.post("/api/v1/regions/north/events", headers={"X-Region-Token": KEY},
                             json={"event_id": "sighting:north-hit", "department": "Traffic A",
                                   "kind": "sighting", "camera_id": "north",
                                   "occurred_utc": datetime.now(timezone.utc).isoformat(),
                                   "plate": "GJ01AB1234"})
        assert repeat.json()["duplicate"]


def test_shadow_equal_budget_and_clock_block(tmp_path: Path):
    ranks = [{"camera_id": str(i)} for i in range(5)]
    first = shadow_policies(ranks, {"0": 1.0, "1": 1.0}, 2.0, 1, 2)
    second = shadow_policies(ranks, {"0": 1.0, "1": 1.0}, 2.0, 2, 2)
    assert sum(first["uniform"].values()) <= sum(first["adaptive"].values())
    assert first["uniform"] != second["uniform"]
    assert first["exploration_camera_id"] in {"2", "3", "4"}
    settings = Settings(tmp_path / "trust.sqlite", "operator-test-key-12345")
    app = create_app(settings)
    with TestClient(app) as client:
        headers = auth(client, settings.operator_key)
        client.post("/api/v1/cameras/import", headers=headers, json=[camera("clock", "Traffic")]).raise_for_status()
        trust = client.get("/api/v1/cameras/clock/trust").json()
        assert trust["cross_camera_travel_time"] == "blocked_approximate_only"
        assert not trust["shared_utc_verified"]
        app.state.database.update_health("clock", "online", pts=42, timebase="1/90000", fps=12, generation=1)
        mapped = client.post("/api/v1/cameras/clock/time-mappings", headers=headers, json={
            "stream_generation": 1, "pts_anchor": 42,
            "utc_anchor": datetime.now(timezone.utc).isoformat(), "uncertainty_ms": 100,
            "basis": "owned_recording_clock_attested", "evidence_note": "Owned fixture clock anchor",
        })
        mapped.raise_for_status()
        assert client.get("/api/v1/cameras/clock/trust").json()["shared_utc_verified"]
        app.state.database.update_health("clock", "online", pts=1, timebase="1/90000", fps=12, generation=2)
        assert client.get("/api/v1/cameras/clock/trust").json()["cross_camera_travel_time"] == "blocked_approximate_only"


def test_exploration_changes_one_worker_within_measured_budget(tmp_path: Path):
    settings = Settings(tmp_path / "schedule.sqlite", "operator-test-key-12345")
    app = create_app(settings)
    class Worker:
        max_cameras = 4
        def __init__(self, store): self.store, self.active = store, {}
        def start(self, camera_id, rate): self.active[camera_id] = rate
        def stop(self, camera_id): self.active.pop(camera_id, None)
        def status(self, camera_id):
            return {**self.store.analysis_status(camera_id), "running": camera_id in self.active,
                    "applied_fps": self.active.get(camera_id, 0),
                    "acknowledged_utc": datetime.now(timezone.utc).isoformat() if camera_id in self.active else None}
    with TestClient(app) as client:
        app.state.active_pursuit.analytics = Worker(app.state.intelligence)
        headers = auth(client, settings.operator_key)
        client.post("/api/v1/cameras/import", headers=headers,
                    json=[camera(f"c{i}", "Traffic") for i in range(5)]).raise_for_status()
        pursuit = client.post("/api/v1/pursuits", headers=headers,
                              json={"plate": "GJ01AB1234"}).json()
        identifier = pursuit["id"]
        client.post("/api/v1/capacity/measurements", headers=headers, json={
            "duration_seconds": 10, "feed_count": 1, "decoded_frames": 120,
            "analyzed_frames": 100, "codec": "h264", "resolution": "1280x720",
            "model_provider": "owned-test", "source_mode": "owned_replay",
            "method": "Owned deterministic fixture", "evidence_note": "Test capacity fixture",
        }).raise_for_status()
        client.put(f"/api/v1/pursuits/{identifier}/exploration?enabled=true", headers=headers).raise_for_status()
        ranked = client.get(f"/api/v1/pursuits/{identifier}/rankings").json()["rankings"]
        scheduled = client.post(f"/api/v1/pursuits/{identifier}/schedule", headers=headers)
        scheduled.raise_for_status()
        applied = {row["camera_id"] for row in scheduled.json()["allocations"] if row["requested_fps"] > 0}
        assert len(applied) == 4
        assert len(applied - {row["camera_id"] for row in ranked[:4]}) == 1
        assert scheduled.json()["requested_total_fps"] <= 7
        shadow = client.get(f"/api/v1/pursuits/{identifier}/shadow").json()
        assert len(shadow["decisions"]) == 1
        assert sum(shadow["decisions"][0]["uniform"].values()) <= 7


def test_regional_background_pump_retries_and_survives_restart(tmp_path: Path, monkeypatch):
    region = {"id": "north", "url": "http://127.0.0.1:8101", "token": KEY,
              "departments": ["Traffic A"]}
    central = create_app(Settings(tmp_path / "central.sqlite", "operator-test-key-12345",
                                  regions=[region]))
    regional_path = tmp_path / "north.sqlite"
    agent = create_regional_app(regional_path, "north", {"Traffic A"}, KEY,
                                central_url="http://127.0.0.1:8000", central_token=KEY)
    regional_db = Database(regional_path)
    regional_db.import_owned(camera("north-camera", "Traffic A"))
    regional_db.update_health("north-camera", "degraded", detail="test WAN outage")
    offline = {"value": True}
    with TestClient(central) as central_client:
        def post_to_central(url, **kwargs):
            if offline["value"]:
                raise httpx.ConnectError("simulated WAN outage")
            return central_client.post(url.removeprefix("http://127.0.0.1:8000"),
                                       json=kwargs["json"], headers=kwargs["headers"])
        monkeypatch.setattr(regional_module.httpx, "post", post_to_central)
        with TestClient(agent):
            until = time.monotonic() + 3
            while time.monotonic() < until and not agent.state.ledger.status()["pending_metadata"]:
                time.sleep(.05)
            assert agent.state.ledger.status()["pending_metadata"] == 1
            assert central_client.get("/api/v1/regions/events").status_code == 401
            auth(central_client, "operator-test-key-12345")
            assert central_client.get("/api/v1/regions/events").json()["events"] == []
            offline["value"] = False
            until = time.monotonic() + 8
            while time.monotonic() < until and agent.state.ledger.status()["pending_metadata"]:
                time.sleep(.1)
            assert agent.state.ledger.status()["pending_metadata"] == 0
            events = central_client.get("/api/v1/regions/events").json()
            assert len(events["events"]) == 1
            assert events["open_delivered_gaps"][0]["camera_id"] == "north-camera"
    restarted = create_regional_app(regional_path, "north", {"Traffic A"}, KEY)
    assert restarted.state.ledger.status()["delivered_metadata"] == 1
