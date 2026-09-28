from __future__ import annotations

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.ingest.catalogue import SentinelCatalogue, parse_catalogue
from app.main import create_app


def _login(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"operator_key": "test-operator-key-123"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _settings(path: Path) -> Settings:
    return Settings(database_path=path, operator_key="test-operator-key-123", idle_capture_seconds=0.3)


class ChangingCatalogue:
    def __init__(self):
        self.records = []

    def fetch(self):
        return self.records


def test_catalogue_is_read_only_and_uses_returned_urls():
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        return httpx.Response(200, json={"cameras": [{
            "id": "A-42", "name": "Junction A", "department": "Test",
            "location": {"lat": 23.0, "lng": 72.0}, "live": True,
            "codec": "H.265", "width": 1280, "height": 720, "bitrate": 1200000,
            "urls": {
                "rtsp": "rtsp://example.invalid:8554/custom-path/a",
                "hls": "https://example.invalid/custom-hls/list.m3u8",
                "whep": "https://example.invalid/custom-preview/whep",
            },
        }]})

    catalogue = SentinelCatalogue("https://example.invalid", transport=httpx.MockTransport(respond))
    cameras = catalogue.fetch()
    assert requests == [("GET", "https://example.invalid/api/ingest")]
    assert cameras[0]["camera_id"] == "A-42"
    assert cameras[0]["rtsp_url"].endswith("/custom-path/a")
    assert cameras[0]["codec"] == "H.265"


def test_catalogue_rejects_missing_coordinates_and_inference_url():
    base = {"id": "x", "urls": {"rtsp": "rtsp://example.invalid/a"}}
    try:
        parse_catalogue({"cameras": [base]})
    except ValueError as error:
        assert "coordinates" in str(error)
    else:
        raise AssertionError("Expected catalogue validation failure")


def test_registry_survives_restart_and_catalogue_removal(tmp_path: Path):
    source = ChangingCatalogue()
    source.records = [{
        "camera_id": "gov-1", "display_name": "Government camera 1", "department": "Dept A",
        "latitude": 23.0, "longitude": 72.0, "source_type": "rtsp",
        "source_mode": "government_live", "codec": "H.264", "width": 640,
        "height": 360, "bitrate": 700000, "catalogue_live": True,
        "rtsp_url": "rtsp://example.invalid:8554/some-actual-url", "hls_url": None,
    }]
    settings = _settings(tmp_path / "grid.sqlite")
    with TestClient(create_app(settings, source)) as client:
        assert client.get("/api/v1/cameras").status_code == 401
        csrf = _login(client)
        assert client.post("/api/v1/cameras/sync-sentinel").status_code == 403
        result = client.post("/api/v1/cameras/sync-sentinel", headers=csrf)
        assert result.json() == {"discovered": 1, "added": 1, "restored": 0, "removed": 0,
                                 "changed": 0, "restart_ids": []}
        listed = client.get("/api/v1/cameras").json()
        assert listed[0]["health_status"] == "unknown"  # Catalogue live is not decoded live.
        assert listed[0]["catalogue_live"] is True
        assert "rtsp_url" not in listed[0]
        assert "some-actual-url" not in str(listed)

    with TestClient(create_app(settings, source)) as client:
        csrf = _login(client)
        assert client.get("/api/v1/cameras/gov-1").json()["latitude"] == 23.0
        source.records = [{
            **source.records[0], "camera_id": "gov-2", "codec": "H.265",
            "width": 1920, "catalogue_live": False,
        }]
        result = client.post("/api/v1/cameras/sync-sentinel", headers=csrf).json()
        assert result == {"discovered": 1, "added": 1, "restored": 0, "removed": 1,
                          "changed": 0, "restart_ids": ["gov-1"]}
        assert client.get("/api/v1/cameras/gov-1").json()["health_status"] == "offline"
        assert client.get("/api/v1/cameras/gov-1").json()["catalogue_present"] is False
        assert client.get("/api/v1/cameras/gov-2").json()["codec"] == "H.265"
        assert client.get("/api/v1/cameras/gov-2/health").json()["history"] == []
        source.records = [{**source.records[0], "rtsp_url": "rtsp://example.invalid/new-url"}]
        changed = client.post("/api/v1/cameras/sync-sentinel", headers=csrf).json()
        assert changed["changed"] == 1
        assert changed["restart_ids"] == ["gov-2"]
        assert client.app.state.database.source_urls("gov-2")["rtsp"].endswith("/new-url")
        assert client.get("/api/v1/cameras/gov-2").json()["health_status"] == "unknown"
        source.records.append({**source.records[0], "camera_id": "gov-1"})
        returned = client.post("/api/v1/cameras/sync-sentinel", headers=csrf).json()
        assert returned["restored"] == 1
        assert client.get("/api/v1/cameras/gov-1").json()["health_status"] == "unknown"


def test_owned_import_auth_and_no_url_leak(tmp_path: Path):
    settings = _settings(tmp_path / "grid.sqlite")
    camera = {
        "camera_id": "owned-1", "display_name": "Owned demo feed", "department": "Team",
        "latitude": 22.3, "longitude": 73.2, "source_mode": "owned_replay",
        "hls_url": "http://example.invalid/private/stream.m3u8",
    }
    with TestClient(create_app(settings)) as client:
        csrf = _login(client)
        assert client.post("/api/v1/cameras/import", json=[camera]).status_code == 403
        response = client.post("/api/v1/cameras/import", json=[camera], headers=csrf)
        assert response.status_code == 201
        public = client.get("/api/v1/cameras/owned-1").json()
        assert public["source_mode"] == "owned_replay"
        assert public["health_status"] == "unknown"
        assert "private/stream" not in str(public)
        assert client.get("/api/v1/cameras/owned-1/health").json()["capture"]["connected_clients"] == 0
        invalid_batch = [
            {**camera, "camera_id": "would-have-been-added"},
            {**camera, "camera_id": "invalid-no-source", "hls_url": None},
        ]
        rejected = client.post("/api/v1/cameras/import", json=invalid_batch, headers=csrf)
        assert rejected.status_code == 400
        assert client.get("/api/v1/cameras/would-have-been-added").status_code == 404
        updated = client.post("/api/v1/cameras/import", headers=csrf, json=[
            {**camera, "hls_url": "http://example.invalid/new-source.m3u8"},
        ]).json()
        assert updated["restarted"] == ["owned-1"]
        assert client.app.state.database.source_urls("owned-1")["hls"].endswith("/new-source.m3u8")
    with TestClient(create_app(settings)) as client:
        _login(client)
        assert client.get("/api/v1/cameras/owned-1").json()["longitude"] == 73.2
