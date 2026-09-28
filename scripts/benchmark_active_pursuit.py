"""Measure the actual local capture -> FastALPR worker path on owned RTSP replay.

This is a laptop/sandbox calibration, not an Indian-road accuracy or statewide
capacity claim. Requires the ignored official sample, MediaMTX and FFmpeg.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


SAMPLE = ROOT / "backend/data/fastalpr_sample.png"
RELAY = ROOT / "backend/data/tools/mediamtx/mediamtx.exe"
FFMPEG = shutil.which("ffmpeg")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_port(port: int) -> None:
    until = time.monotonic() + 8
    while time.monotonic() < until:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=.2):
                return
        except OSError:
            time.sleep(.1)
    raise RuntimeError("MediaMTX did not start")


def stop(process: subprocess.Popen | None) -> None:
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def gpu_snapshot() -> dict | None:
    if not shutil.which("nvidia-smi"):
        return None
    result = subprocess.run([
        "nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
        "--format=csv,noheader,nounits",
    ], capture_output=True, text=True, timeout=4, check=False)
    if result.returncode:
        return None
    try:
        load, memory = (int(value.strip()) for value in result.stdout.splitlines()[0].split(","))
        return {"gpu_util_percent": load, "gpu_memory_mib": memory}
    except (ValueError, IndexError):
        return None


def process_ram_mib() -> float | None:
    if sys.platform != "win32":
        return None
    class MemoryCounters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]
    memory = MemoryCounters()
    memory.cb = ctypes.sizeof(memory)
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = (
        ctypes.c_void_p, ctypes.POINTER(MemoryCounters), ctypes.c_ulong
    )
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    handle = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
        return None
    return round(memory.WorkingSetSize / 1048576, 1)


def relay_network_bytes(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2) as response:
            lines = response.read().decode("utf-8").splitlines()
    except OSError:
        return None
    counters = {"received": 0, "sent": 0}
    matched = False
    for line in lines:
        if line.startswith("#"):
            continue
        if line.startswith("paths_bytes_received") or line.startswith("paths_bytes_sent"):
            try:
                value = float(line.rsplit(" ", 1)[-1])
            except ValueError:
                continue
            if line.startswith("paths_bytes_received"):
                counters["received"] += value
            else:
                counters["sent"] += value
            matched = True
    return counters if matched else None


def measure(duration: int, width: int, height: int) -> dict:
    if not SAMPLE.exists() or not RELAY.exists() or not FFMPEG:
        raise RuntimeError("Official sample, local MediaMTX, and FFmpeg are required")
    port = free_port()
    metrics_port = free_port()
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with tempfile.TemporaryDirectory(prefix="sakhyapath_capacity_",
                                     ignore_cleanup_errors=True) as name:
        work = Path(name)
        relay_dir = work / "relay"
        relay_dir.mkdir()
        config = relay_dir / "mediamtx.yml"
        config.write_text(
            f"rtsp: true\nrtspAddress: 127.0.0.1:{port}\n"
            f"metrics: true\nmetricsAddress: 127.0.0.1:{metrics_port}\n"
            "rtmp: false\nhls: false\nwebrtc: false\nsrt: false\nmoq: false\n"
            "paths:\n  h264:\n    source: publisher\n  h265:\n    source: publisher\n",
            encoding="utf-8",
        )
        relay_log = (work / "relay.log").open("wb")
        publisher_logs = []
        publishers = []
        relay = None
        try:
            relay = subprocess.Popen([str(RELAY), str(config)], cwd=relay_dir,
                                     stdout=relay_log, stderr=subprocess.STDOUT,
                                     creationflags=flags)
            wait_port(port)
            for codec in ("h264", "h265"):
                logfile = (work / f"{codec}.log").open("wb")
                publisher_logs.append(logfile)
                codec_args = (["-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency"]
                              if codec == "h264" else
                              ["-c:v", "libx265", "-preset", "ultrafast", "-x265-params",
                               "log-level=error:keyint=24", "-tune", "zerolatency"])
                publishers.append(subprocess.Popen([
                    FFMPEG, "-hide_banner", "-loglevel", "error", "-re", "-loop", "1",
                    "-framerate", "12", "-i", str(SAMPLE), "-vf",
                    f"scale={width}:{height},pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    *codec_args, "-g", "12", "-pix_fmt", "yuv420p", "-f", "rtsp",
                    "-rtsp_transport", "tcp", f"rtsp://127.0.0.1:{port}/{codec}",
                ], stdout=logfile, stderr=subprocess.STDOUT, creationflags=flags))
            settings = Settings(work / "benchmark.sqlite3", "owned-benchmark-key-12345",
                                evidence_dir=work / "evidence",
                                models_dir=ROOT / "backend/data/models", analytics_max_cameras=2)
            with TestClient(create_app(settings)) as client:
                auth = client.post("/api/v1/auth/login", json={
                    "operator_key": settings.operator_key,
                }).json()
                headers = {"X-CSRF-Token": auth["csrf_token"]}
                cameras = [{"camera_id": codec, "display_name": f"Owned {codec} benchmark",
                            "department": "Owned capacity fixture", "latitude": 23,
                            "longitude": 72, "source_mode": "owned_replay",
                            "rtsp_url": f"rtsp://127.0.0.1:{port}/{codec}",
                            "width": width, "height": height, "codec": codec}
                           for codec in ("h264", "h265")]
                client.post("/api/v1/cameras/import", headers=headers, json=cameras).raise_for_status()
                for codec in ("h264", "h265"):
                    client.post(f"/api/v1/cameras/{codec}/analysis", headers=headers,
                                json={"sample_fps": 10}).raise_for_status()
                ready_until = time.monotonic() + 45
                while time.monotonic() < ready_until:
                    statuses = {codec: client.get(f"/api/v1/cameras/{codec}/analysis").json()
                                for codec in ("h264", "h265")}
                    if all(statuses[codec]["analyzed"] >= 2 for codec in statuses):
                        break
                    if any(process.poll() is not None for process in publishers):
                        raise RuntimeError("A benchmark publisher exited during warm-up")
                    time.sleep(.5)
                else:
                    health = {codec: client.get(f"/api/v1/cameras/{codec}/health").json()
                              for codec in ("h264", "h265")}
                    raise RuntimeError(f"Analysis did not warm up: {statuses}; health={health}")
                captures = client.app.state.captures
                start_status = statuses
                network_start = relay_network_bytes(metrics_port)
                start_sequences = {codec: captures.workers[codec].frame_sequence
                                   for codec in statuses}
                gpu_samples = []
                ram_samples = []
                latency_samples = []
                cpu_started = time.process_time()
                started = time.perf_counter()
                while time.perf_counter() - started < duration:
                    for codec in ("h264", "h265"):
                        item = client.get(f"/api/v1/cameras/{codec}/analysis").json()
                        if item["last_latency_ms"] is not None:
                            latency_samples.append(item["last_latency_ms"])
                    gpu = gpu_snapshot()
                    if gpu:
                        gpu_samples.append(gpu)
                    memory = process_ram_mib()
                    if memory is not None:
                        ram_samples.append(memory)
                    time.sleep(.7)
                elapsed = time.perf_counter() - started
                process_cpu_seconds = time.process_time() - cpu_started
                reported_elapsed = round(elapsed, 3)
                network_end = relay_network_bytes(metrics_port)
                end_status = {codec: client.get(f"/api/v1/cameras/{codec}/analysis").json()
                              for codec in ("h264", "h265")}
                decoded = sum(captures.workers[codec].frame_sequence - start_sequences[codec]
                              for codec in end_status)
                analyzed = sum(end_status[codec]["analyzed"] - start_status[codec]["analyzed"]
                               for codec in end_status)
                received = sum(end_status[codec]["received"] - start_status[codec]["received"]
                               for codec in end_status)
                dropped = sum(end_status[codec]["dropped"] - start_status[codec]["dropped"]
                              for codec in end_status)
                provider = "+".join(sorted({item["execution_provider"]
                                            for item in end_status.values()}))
                errors = sum(client.app.state.database.capture_error_count(codec)
                             for codec in end_status)
                reconnects = sum(sum(event["status"] in {"offline", "degraded"}
                                     for event in client.app.state.database.health_events(codec, 500))
                                 for codec in end_status)
                for codec in ("h264", "h265"):
                    client.delete(f"/api/v1/cameras/{codec}/analysis", headers=headers).raise_for_status()
                ordered = sorted(latency_samples)
                p95 = ordered[min(len(ordered) - 1, int(.95 * len(ordered)))] if ordered else None
                return {
                    "duration_seconds": reported_elapsed, "feed_count": 2,
                    "decoded_frames": decoded, "received_frames": received,
                    "analyzed_frames": analyzed, "dropped_frames": dropped,
                    "sustainable_fps_observed": round(analyzed / reported_elapsed, 3),
                    "scheduler_budget_fps_70_percent": round(.7 * analyzed / reported_elapsed, 3),
                    "headroom_fraction": .30, "codec": "h264+h265",
                    "resolution": f"{width}x{height}", "model_provider": provider,
                    "source_mode": "owned_replay",
                    "p95_sampled_model_latency_ms": round(p95, 2) if p95 is not None else None,
                    "gpu_max_util_percent": max((x["gpu_util_percent"] for x in gpu_samples), default=None),
                    "gpu_max_memory_mib": max((x["gpu_memory_mib"] for x in gpu_samples), default=None),
                    "process_cpu_seconds": round(process_cpu_seconds, 2),
                    "process_cpu_cores_average": round(process_cpu_seconds / elapsed, 3),
                    "process_ram_peak_mib": max(ram_samples, default=None),
                    "relay_bytes_received": (round(network_end["received"] - network_start["received"])
                                             if network_start and network_end else None),
                    "relay_bytes_sent": (round(network_end["sent"] - network_start["sent"])
                                         if network_start and network_end else None),
                    "capture_errors": errors, "health_degraded_or_offline_events": reconnects,
                    "method": "Two local MediaMTX RTSP/TCP publishers, H.264 and H.265; decode, sampling, FastALPR, SQLite; warmed before timed interval",
                    "evidence_note": "Official FastALPR sample looped as owned replay. This measures local throughput, not Indian plate accuracy or 80k-camera scale.",
                    "limitations": ["One laptop, two owned replay feeds", "Publisher encoding shares this host",
                                    "No Sentinel access", "p95 is sampled model latency, not frame-to-alert latency"],
                }
        finally:
            for process in publishers:
                stop(process)
            stop(relay)
            for logfile in publisher_logs:
                logfile.close()
            relay_log.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--record-local-db", action="store_true")
    args = parser.parse_args()
    result = measure(args.duration, args.width, args.height)
    destination = ROOT / "output/benchmarks/module4_owned_pipeline.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.record_local_db:
        local_db = ROOT / "backend/data/sakhyapath.sqlite3"
        settings = Settings(local_db, "local-benchmark-import-key-12345")
        app = create_app(settings)
        try:
            app.state.database.migrate()
            app.state.intelligence.migrate()
            app.state.journeys.migrate()
            app.state.active_pursuit.migrate()
            measurement = app.state.active_pursuit.add_measurement({
                key: result[key] for key in ("duration_seconds", "feed_count", "decoded_frames",
                                               "analyzed_frames", "codec", "resolution",
                                               "model_provider", "source_mode", "method",
                                               "evidence_note")
            })
            result["recorded_measurement_id"] = measurement["id"]
            destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
        finally:
            app.state.captures.shutdown()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
