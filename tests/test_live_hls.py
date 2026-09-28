from __future__ import annotations

import functools
import http.server
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import av
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not available")
@pytest.mark.parametrize("rtsp_mode", ["absent", "refused", "empty_decode"])
def test_real_hls_frame_reaches_authenticated_snapshot_with_pts(tmp_path: Path,
                                                                rtsp_mode: str,
                                                                monkeypatch):
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc=size=640x360:rate=10",
        "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-f", "hls", "-hls_time", "1", "-hls_playlist_type", "vod",
        str(tmp_path / "index.m3u8"),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(tmp_path))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            unavailable_port = probe.getsockname()[1]
        if rtsp_mode == "empty_decode":
            original_open = av.open

            class EmptyRtsp:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def demux(self, **_kwargs):
                    return iter(())

            def open_with_empty_rtsp(url, *args, **kwargs):
                if url.startswith("rtsp://"):
                    return EmptyRtsp()
                return original_open(url, *args, **kwargs)

            monkeypatch.setattr(av, "open", open_with_empty_rtsp)
        settings = Settings(tmp_path / "grid.sqlite", "test-operator-key-123", idle_capture_seconds=0.3)
        with TestClient(create_app(settings)) as client:
            login = client.post("/api/v1/auth/login", json={"operator_key": "test-operator-key-123"})
            csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
            client.post("/api/v1/cameras/import", headers=csrf, json=[{
                "camera_id": "hls-1", "display_name": "Owned HLS fixture", "department": "Test",
                "latitude": 23, "longitude": 72, "source_mode": "owned_replay",
                "rtsp_url": f"rtsp://127.0.0.1:{unavailable_port}/missing"
                if rtsp_mode != "absent" else None,
                "hls_url": f"http://127.0.0.1:{server.server_port}/index.m3u8",
            }]).raise_for_status()
            response = client.get("/api/v1/cameras/hls-1/snapshot.jpg")
            assert response.status_code == 200, response.text
            assert response.content.startswith(b"\xff\xd8")
            assert response.headers["x-camera-id"] == "hls-1"
            assert response.headers["x-source-pts"] != ""
            assert response.headers["x-pts-timebase"] != "unavailable"
            health = client.get("/api/v1/cameras/hls-1/health").json()
            assert health["last_frame_utc"] is not None
            assert any(event["status"] == "online" for event in health["history"])
            if rtsp_mode != "absent":
                assert health["capture"]["active_transport"] == "hls"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
