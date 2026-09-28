from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEDIAMTX = Path(os.getenv("MEDIAMTX_BIN", str(PROJECT_ROOT / "backend/data/tools/mediamtx/mediamtx.exe")))
CHOCOLATEY_FFMPEG = Path("C:/ProgramData/chocolatey/lib/ffmpeg/tools/ffmpeg/bin/ffmpeg.exe")
FFMPEG = str(CHOCOLATEY_FFMPEG) if CHOCOLATEY_FFMPEG.exists() else shutil.which("ffmpeg")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_port(port: int, timeout: float = 5.0) -> None:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("Local MediaMTX did not listen")


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@pytest.mark.skipif(not MEDIAMTX.exists() or FFMPEG is None,
                    reason="Local MediaMTX and FFmpeg required for owned RTSP test")
@pytest.mark.parametrize("codec,reconnect", [("libx264", True), ("libx265", False)])
def test_owned_rtsp_tcp_preview_and_reconnect(tmp_path: Path, codec: str, reconnect: bool):
    port = free_port()
    config = tmp_path / "mediamtx.yml"
    config.write_text(
        f"rtsp: true\nrtspAddress: 127.0.0.1:{port}\n"
        "rtmp: false\nhls: false\nwebrtc: false\nsrt: false\nmoq: false\n"
        "paths:\n  owned:\n    source: publisher\n", encoding="utf-8"
    )
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    relay_log = (tmp_path / "relay.log").open("wb")
    publisher_log = (tmp_path / "publisher.log").open("wb")
    relay = subprocess.Popen([str(MEDIAMTX), str(config)], cwd=tmp_path,
                             stdout=relay_log, stderr=subprocess.STDOUT,
                             creationflags=flags)
    publisher = None
    try:
        wait_port(port)
        url = f"rtsp://127.0.0.1:{port}/owned"
        command = [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-re",
            "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10",
            "-c:v", codec, "-preset", "ultrafast", "-tune", "zerolatency", "-g", "10",
            "-pix_fmt", "yuv420p", "-f", "rtsp", "-rtsp_transport", "tcp", url,
        ]
        publisher = subprocess.Popen(command, stdout=publisher_log,
                                     stderr=subprocess.STDOUT, creationflags=flags)
        settings = Settings(tmp_path / "grid.sqlite", "test-operator-key-123", idle_capture_seconds=0.5)
        with TestClient(create_app(settings)) as client:
            token = client.post("/api/v1/auth/login", json={"operator_key": "test-operator-key-123"}).json()["csrf_token"]
            client.post("/api/v1/cameras/import", headers={"X-CSRF-Token": token}, json=[{
                "camera_id": "owned-rtsp", "display_name": "Owned RTSP fixture",
                "latitude": 23, "longitude": 72, "source_mode": "owned_live", "rtsp_url": url,
            }]).raise_for_status()
            until = time.monotonic() + 10
            response = None
            while time.monotonic() < until:
                response = client.get("/api/v1/cameras/owned-rtsp/snapshot.jpg")
                if response.status_code == 200:
                    break
                time.sleep(0.2)
            assert response is not None and response.status_code == 200, (
                f"publisher={publisher.poll()} relay={relay.poll()} "
                f"health={client.get('/api/v1/cameras/owned-rtsp/health').json()} "
                f"publisher_log={(tmp_path / 'publisher.log').read_text(errors='replace')} "
                f"relay_log={(tmp_path / 'relay.log').read_text(errors='replace')}"
            )
            assert response.content.startswith(b"\xff\xd8")
            assert response.headers["x-source-pts"] != ""
            assert client.get("/api/v1/cameras/owned-rtsp/health").json()["last_frame_utc"]
            # A second consumer shares the same server-side capture worker.
            first = client.app.state.captures.acquire("owned-rtsp")
            second = client.app.state.captures.acquire("owned-rtsp")
            assert first is second
            assert client.app.state.captures.state("owned-rtsp")["connected_clients"] == 2
            until = time.monotonic() + 3
            while time.monotonic() < until:
                trust = client.get("/api/v1/cameras/owned-rtsp/trust").json()
                if trust["pts_interval_stats"] is not None:
                    break
                time.sleep(.1)
            assert trust["media_timing_ready"] and trust["pts_interval_stats"]["samples"] > 0
            assert trust["cross_camera_travel_time"] == "blocked_approximate_only"
            client.app.state.captures.release(first)
            client.app.state.captures.release(second)
            if reconnect:
                keeper = client.app.state.captures.acquire("owned-rtsp")
                original_generation = client.get("/api/v1/cameras/owned-rtsp/health").json()["stream_generation"]
                try:
                    stop_process(publisher)
                    publisher = None
                    until = time.monotonic() + 12
                    while time.monotonic() < until:
                        state = client.get("/api/v1/cameras/owned-rtsp/health").json()
                        if state["health_status"] in {"offline", "degraded"}:
                            break
                        time.sleep(0.2)
                    assert state["health_status"] in {"offline", "degraded"}, state
                    publisher = subprocess.Popen(command, stdout=publisher_log,
                                                 stderr=subprocess.STDOUT, creationflags=flags)
                    until = time.monotonic() + 15
                    while time.monotonic() < until:
                        state = client.get("/api/v1/cameras/owned-rtsp/health").json()
                        if state["health_status"] == "online" and state["stream_generation"] > original_generation:
                            break
                        time.sleep(0.2)
                    assert state["health_status"] == "online" and state["stream_generation"] > original_generation, state
                finally:
                    client.app.state.captures.release(keeper)
                until = time.monotonic() + 3
                while time.monotonic() < until:
                    if client.app.state.captures.state("owned-rtsp")["connected_clients"] == 0 and not client.app.state.captures.state("owned-rtsp")["capture_running"]:
                        break
                    time.sleep(0.1)
                assert client.app.state.captures.state("owned-rtsp")["connected_clients"] == 0
    finally:
        stop_process(publisher)
        stop_process(relay)
        publisher_log.close()
        relay_log.close()
