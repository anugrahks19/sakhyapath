from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from typing import Callable

import av
import cv2
import numpy as np

# A shared one-core demo VM must not spawn OpenCV's machine-sized worker pool
# for each preview resize/encode; model inference has its own capacity budget.
cv2.setNumThreads(1)

from app.storage.database import Database


@dataclass(frozen=True)
class FramePacket:
    camera_id: str
    bgr: np.ndarray
    source_pts: float | None
    pts_timebase: str | None
    stream_generation: int
    source_mode: str
    received_utc: str  # Operational diagnostic only; not media/event time.
    sequence: int = 0  # Monotonic decoded-frame count within this capture worker.
    received_monotonic: float | None = None  # Local queue-age diagnostic only.


class CaptureWorker:
    def __init__(self, camera_id: str, db: Database, idle_seconds: float,
                 on_exit: Callable[[str, "CaptureWorker"], None]):
        self.camera_id = camera_id
        self.db = db
        self.idle_seconds = idle_seconds
        self.on_exit = on_exit
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"capture-{camera_id}", daemon=True)
        self.viewers = 0
        self.analysis_viewers = 0
        self.latest: FramePacket | None = None
        self.latest_at_monotonic: float | None = None
        self.last_error: str | None = None
        self.active_transport: str | None = None
        self.decoded_connected = False
        self.frame_sequence = 0
        self.pts_interval_stats: dict | None = None
        self.pts_discontinuities = 0
        camera = db.camera(camera_id)
        self.generation = camera["stream_generation"] if camera else 0
        self._last_active = time.monotonic()

    def start(self) -> None:
        self.thread.start()

    def acquire(self, preview: bool = False) -> None:
        with self.condition:
            self.viewers += 1
            if not preview:
                self.analysis_viewers += 1
            self._last_active = time.monotonic()

    def release(self, preview: bool = False) -> None:
        with self.condition:
            self.viewers = max(0, self.viewers - 1)
            if not preview:
                self.analysis_viewers = max(0, self.analysis_viewers - 1)
            self._last_active = time.monotonic()
            self.condition.notify_all()

    def wait_frame(self, after: FramePacket | None, timeout: float = 2.0,
                   require_fresh: bool = False) -> FramePacket | None:
        def ready() -> bool:
            if self.stop_event.is_set():
                return True
            if self.latest is after:
                return False
            return not require_fresh or (
                self.latest_at_monotonic is not None
                and time.monotonic() - self.latest_at_monotonic <= 3.0
            )
        with self.condition:
            self.condition.wait_for(ready, timeout=timeout)
            return self.latest if not self.stop_event.is_set() and ready() and self.latest is not after else None

    def should_idle(self) -> bool:
        with self.condition:
            return self.viewers == 0 and time.monotonic() - self._last_active >= self.idle_seconds

    def stop(self) -> None:
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()

    def _run(self) -> None:
        delay = 2.0
        try:
            while not self.stop_event.is_set() and not self.should_idle():
                camera = self.db.camera(self.camera_id)
                if not camera or not camera["catalogue_present"]:
                    break
                urls = self.db.source_urls(self.camera_id)
                attempts = [(kind, urls[kind]) for kind in ("rtsp", "hls") if kind in urls]
                if not attempts:
                    break
                decoded = False
                for kind, url in attempts:
                    if self.stop_event.is_set() or self.should_idle():
                        break
                    try:
                        self.active_transport = kind
                        self.decoded_connected = False
                        options = {"rtsp_transport": "tcp"} if kind == "rtsp" else {}
                        with av.open(url, options=options, timeout=(5.0, 5.0)) as container:
                            self.generation += 1
                            decoded = self._decode(container, camera["source_mode"]) > 0
                        if not decoded:
                            self.last_error = "NoDecodedFrame"
                            self.db.record_capture_error(self.camera_id, self.last_error)
                            self.db.update_health(self.camera_id, "degraded", self.last_error)
                            continue
                        self.last_error = None
                        if self.stop_event.is_set() or self.should_idle():
                            break
                    except Exception as error:
                        # FFmpeg errors may contain credentials or the source URL.
                        self.last_error = type(error).__name__
                        self.decoded_connected = False
                        self.db.record_capture_error(self.camera_id, self.last_error)
                        self.db.update_health(self.camera_id, "degraded", self.last_error)
                        continue
                    if decoded:
                        break
                if self.stop_event.is_set() or self.should_idle():
                    break
                self.db.update_health(self.camera_id, "offline", self.last_error or "End of stream")
                self.decoded_connected = False
                self.stop_event.wait(delay)
                delay = min(30.0, delay * 2)
                if decoded:
                    delay = 2.0
        finally:
            self.active_transport = None
            self.decoded_connected = False
            camera = self.db.camera(self.camera_id)
            if camera and camera["catalogue_present"] and camera["health_status"] not in {
                "offline", "degraded"
            }:
                self.db.update_health(self.camera_id, "idle", "Capture closed")
            self.on_exit(self.camera_id, self)

    def _decode(self, container: av.container.InputContainer, source_mode: str) -> int:
        last_pts: float | None = None
        recent_deltas: deque[float] = deque(maxlen=30)
        last_thumb: np.ndarray | None = None
        last_db_write = 0.0
        decoded_frames = 0
        last_published = 0.0
        started = time.monotonic()
        for packet in container.demux(video=0):
            if self.stop_event.is_set() or self.should_idle():
                return decoded_frames
            try:
                frames = packet.decode()
            except av.error.InvalidDataError:
                # Joining before an IDR can yield corrupt reference packets.
                # Allow a bounded decoder warm-up; a persistently bad feed fails.
                if decoded_frames == 0 and time.monotonic() - started <= 3.0:
                    continue
                raise
            for frame in frames:
                if self.stop_event.is_set() or self.should_idle():
                    return decoded_frames
                decoded_frames += 1
                timebase: Fraction | None = frame.time_base
                pts = float(frame.pts * timebase) if frame.pts is not None and timebase is not None else None
                if pts is not None and last_pts is not None:
                    delta = pts - last_pts
                    if delta < 0 or delta > 10.0:
                        self.generation += 1
                        self.pts_discontinuities += 1
                        recent_deltas.clear()
                    elif delta > 0:
                        recent_deltas.append(delta)
                last_pts = pts
                now = time.monotonic()
                with self.condition:
                    analysis_requested = self.analysis_viewers > 0
                # Preview polls at 2 fps. Decode and measure every source frame,
                # but avoid converting unused frames into BGR on small demo hosts.
                if not analysis_requested and now - last_published < 0.4:
                    time.sleep(0.001)
                    continue
                bgr = frame.to_ndarray(format="bgr24")
                thumb = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (32, 18))
                if last_thumb is not None:
                    difference = float(np.mean(cv2.absdiff(thumb, last_thumb)))
                    if difference > 110.0:
                        self.generation += 1
                        recent_deltas.clear()
                last_thumb = thumb
                fps = (len(recent_deltas) / sum(recent_deltas)) if recent_deltas else None
                frame_packet = FramePacket(
                    camera_id=self.camera_id,
                    bgr=bgr,
                    source_pts=pts,
                    pts_timebase=str(timebase) if timebase is not None else None,
                    stream_generation=self.generation,
                    source_mode=source_mode,
                    received_utc=datetime.now(timezone.utc).isoformat(),
                    sequence=self.frame_sequence + 1,
                    received_monotonic=time.monotonic(),
                )
                self.frame_sequence += 1
                last_published = now
                if now - last_db_write >= 1.0:
                    self.db.update_health(self.camera_id, "online", "Decoded frame", pts,
                                          frame_packet.pts_timebase, fps, self.generation)
                    if recent_deltas:
                        ordered = sorted(recent_deltas)
                        self.pts_interval_stats = {
                            "samples": len(ordered), "median_ms": round(ordered[len(ordered)//2] * 1000, 2),
                            "p95_ms": round(ordered[min(len(ordered)-1, int(len(ordered)*.95))] * 1000, 2),
                            "max_ms": round(ordered[-1] * 1000, 2),
                        }
                    last_db_write = now
                with self.condition:
                    self.latest = frame_packet
                    self.latest_at_monotonic = time.monotonic()
                    self.decoded_connected = True
                    self.last_error = None
                    self.condition.notify_all()
                # Yield the GIL between source frames so the API can serve
                # case writes and health checks on a one-core demo host.
                time.sleep(0.001)
        return decoded_frames


class CaptureManager:
    def __init__(self, db: Database, idle_seconds: float = 5.0):
        self.db = db
        self.idle_seconds = idle_seconds
        self.lock = threading.Lock()
        self.workers: dict[str, CaptureWorker] = {}
        self.watchdog_stop = threading.Event()
        self.watchdog = threading.Thread(target=self._watchdog, name="capture-watchdog", daemon=True)
        self.watchdog.start()

    def acquire(self, camera_id: str, preview: bool = False) -> CaptureWorker:
        camera = self.db.camera(camera_id)
        if not camera or not camera["catalogue_present"]:
            raise KeyError(camera_id)
        if not self.db.source_urls(camera_id):
            raise ValueError("Camera has no capture URL")
        with self.lock:
            worker = self.workers.get(camera_id)
            if not worker or not worker.thread.is_alive():
                worker = CaptureWorker(camera_id, self.db, self.idle_seconds, self._on_exit)
                self.workers[camera_id] = worker
                worker.acquire(preview=preview)
                worker.start()
            else:
                worker.acquire(preview=preview)
        return worker

    def release(self, worker: CaptureWorker, preview: bool = False) -> None:
        worker.release(preview=preview)

    def stop(self, camera_id: str) -> None:
        with self.lock:
            worker = self.workers.get(camera_id)
        if worker:
            worker.stop()
            worker.thread.join(timeout=7.0)

    def shutdown(self) -> None:
        self.watchdog_stop.set()
        self.watchdog.join(timeout=2.0)
        with self.lock:
            workers = list(self.workers.values())
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.thread.join(timeout=7.0)

    def _watchdog(self) -> None:
        while not self.watchdog_stop.wait(0.5):
            with self.lock:
                workers = list(self.workers.values())
            for worker in workers:
                with worker.condition:
                    last = worker.latest_at_monotonic
                    viewers = worker.viewers
                if not viewers or last is None:
                    continue
                age = time.monotonic() - last
                if age > 6.0:
                    worker.decoded_connected = False
                    self.db.update_health(worker.camera_id, "offline", "No decoded frame for over 6 seconds")
                elif age > 3.0:
                    worker.decoded_connected = False
                    self.db.update_health(worker.camera_id, "degraded", "No decoded frame for over 3 seconds")

    def state(self, camera_id: str) -> dict:
        with self.lock:
            worker = self.workers.get(camera_id)
        if not worker:
            return {"connected_clients": 0, "active_transport": None, "capture_running": False,
                    "pts_interval_stats": None, "pts_discontinuities": 0}
        return {
            "connected_clients": worker.viewers,
            "active_transport": worker.active_transport,
            "capture_running": worker.thread.is_alive(),
            "decoded_connected": worker.decoded_connected,
            "last_error": worker.last_error,
            "pts_interval_stats": worker.pts_interval_stats,
            "pts_discontinuities": worker.pts_discontinuities,
        }

    def counts(self) -> dict[str, int]:
        with self.lock:
            workers = list(self.workers.values())
        return {
            "connected": sum(1 for worker in workers if worker.thread.is_alive()
                             and worker.decoded_connected),
            "viewed": sum(1 for worker in workers if worker.viewers > 0),
            "concurrently_analyzed": 0,  # Filled by the analytics coordinator in the API layer.
        }

    def _on_exit(self, camera_id: str, worker: CaptureWorker) -> None:
        with self.lock:
            if self.workers.get(camera_id) is worker:
                self.workers.pop(camera_id, None)
