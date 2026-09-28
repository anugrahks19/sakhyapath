from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

import cv2

from app.ingest.capture import CaptureManager, FramePacket
from app.storage.database import Database
from app.storage.intelligence import IntelligenceStore, normalize_plate
from app.vision.recognizer import FastAlprRecognizer, Recognizer


class AnalyticsCoordinator:
    """One latest-frame subscriber per active camera; inference never queues old frames."""

    def __init__(self, database: Database, store: IntelligenceStore,
                 captures: CaptureManager, models_dir: Path, max_cameras: int = 4,
                 recognizer_factory: Callable[[], Recognizer] | None = None):
        self.db = database
        self.store = store
        self.captures = captures
        self.models_dir = models_dir
        self.max_cameras = max_cameras
        self.factory = recognizer_factory or (lambda: FastAlprRecognizer(models_dir))
        self.lock = threading.Lock()
        self.model_lock = threading.Lock()
        self.recognizer: Recognizer | None = None
        self.workers: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self.rates: dict[str, float] = {}
        self.acknowledgements: dict[str, dict] = {}

    def start(self, camera_id: str, sample_fps: float = 2.0) -> None:
        if not 0.2 <= sample_fps <= 10:
            raise ValueError("Sampling rate must be between 0.2 and 10 fps")
        camera = self.db.camera(camera_id)
        if not camera or not camera["catalogue_present"]:
            raise KeyError(camera_id)
        if not self.db.source_urls(camera_id):
            raise ValueError("Camera has no supported RTSP/HLS URL")
        with self.lock:
            current = self.workers.get(camera_id)
            if current and current[0].is_alive():
                self.rates[camera_id] = sample_fps
                self.store.set_analysis(camera_id, True, sample_fps)
                return
            running = sum(1 for thread, _ in self.workers.values() if thread.is_alive())
            if running >= self.max_cameras:
                raise ValueError(f"Analysis capacity is limited to {self.max_cameras} cameras")
            stopped = threading.Event()
            thread = threading.Thread(
                target=self._run, args=(camera_id, sample_fps, stopped),
                daemon=True, name=f"analysis-{camera_id}",
            )
            self.workers[camera_id] = (thread, stopped)
            self.rates[camera_id] = sample_fps
            self.acknowledgements.pop(camera_id, None)
            self.store.set_analysis(camera_id, True, sample_fps)
            thread.start()

    def stop(self, camera_id: str) -> None:
        with self.lock:
            current = self.workers.get(camera_id)
        if current:
            current[1].set()
            current[0].join(timeout=8.0)
            if current[0].is_alive():
                raise ValueError("Analysis worker did not stop within timeout")
        with self.lock:
            self.acknowledgements.pop(camera_id, None)
        self.store.set_analysis(camera_id, False, self.store.analysis_status(camera_id)["sample_fps"])

    def restore(self) -> None:
        for item in self.store.enabled_analyses():
            try:
                self.start(item["camera_id"], item["sample_fps"])
            except (KeyError, ValueError):
                self.store.update_counters(item["camera_id"], error="Cannot resume analysis")

    def shutdown(self) -> None:
        with self.lock:
            current = list(self.workers.values())
        for _, event in current:
            event.set()
        for thread, _ in current:
            thread.join(timeout=8.0)

    def status(self, camera_id: str) -> dict:
        result = self.store.analysis_status(camera_id)
        with self.lock:
            current = self.workers.get(camera_id)
            ack = self.acknowledgements.get(camera_id)
        result["running"] = bool(current and current[0].is_alive())
        result["max_concurrent_cameras"] = self.max_cameras
        fresh = bool(ack and time.monotonic() - ack["at_monotonic"] <= 5)
        result["applied_fps"] = ack["rate"] if result["running"] and fresh else 0.0
        result["acknowledged_utc"] = ack["at_utc"] if fresh else None
        return result

    def running_count(self) -> int:
        with self.lock:
            return sum(1 for thread, _ in self.workers.values() if thread.is_alive())

    def _get_model(self) -> Recognizer:
        if self.recognizer is None:
            self.recognizer = self.factory()
        return self.recognizer

    def _run(self, camera_id: str, sample_fps: float, stopped: threading.Event) -> None:
        try:
            worker = self.captures.acquire(camera_id)
        except (KeyError, ValueError):
            self.store.update_counters(camera_id, error="Capture unavailable")
            return
        previous: FramePacket | None = None
        last_sample_pts: float | None = None
        last_sample_generation: int | None = None
        last_sample_monotonic = 0.0
        streaks: dict[str, tuple[int, int, float | None, int]] = {}
        try:
            while not stopped.is_set():
                packet = worker.wait_frame(previous, timeout=1.0)
                if packet is None:
                    if worker.stop_event.is_set() or not worker.thread.is_alive():
                        break
                    continue
                gap = packet.sequence - previous.sequence if previous else 1
                if gap <= 0:
                    gap = 1
                self.store.update_counters(
                    camera_id, received=gap, dropped=max(0, gap - 1)
                )
                previous = packet
                if packet.stream_generation != last_sample_generation:
                    last_sample_generation = packet.stream_generation
                    last_sample_pts = None
                    streaks.clear()
                with self.lock:
                    active_fps = self.rates.get(camera_id, sample_fps)
                if packet.source_pts is not None:
                    if last_sample_pts is not None and (
                        packet.source_pts - last_sample_pts < 1 / active_fps
                    ):
                        continue
                    last_sample_pts = packet.source_pts
                else:
                    now_mono = time.monotonic()
                    if now_mono - last_sample_monotonic < 1 / active_fps:
                        continue
                    last_sample_monotonic = now_mono
                queue_age_ms = (max(0.0, (time.monotonic() - packet.received_monotonic) * 1000)
                                if packet.received_monotonic is not None else None)
                self.store.update_counters(camera_id, selected=1, queue_age_ms=queue_age_ms)
                start = time.perf_counter()
                try:
                    with self.model_lock:
                        model = self._get_model()
                        reads = model.predict(packet.bgr)
                    latency_ms = (time.perf_counter() - start) * 1000
                    self.store.update_counters(
                        camera_id, analyzed=1, detections=len(reads),
                        latency_ms=latency_ms, provider=model.provider,
                        model_version=model.model_version,
                    )
                    with self.lock:
                        self.acknowledgements[camera_id] = {
                            "rate": active_fps, "at_monotonic": time.monotonic(),
                            "at_utc": packet.received_utc,
                        }
                    for read in reads:
                        plate = normalize_plate(read.raw_text)
                        if not 4 <= len(plate) <= 16:
                            continue
                        x1, y1, x2, y2 = read.bbox
                        height, width = packet.bgr.shape[:2]
                        x1, y1 = max(0, x1), max(0, y1)
                        x2, y2 = min(width, x2), min(height, y2)
                        if x2 <= x1 or y2 <= y1:
                            continue
                        crop = packet.bgr[y1:y2, x1:x2]
                        ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
                        if not ok:
                            continue
                        old = streaks.get(plate)
                        consecutive = bool(old and old[0] == packet.stream_generation
                                           and packet.source_pts is not None
                                           and old[2] is not None
                                           and 0 <= packet.source_pts - old[2] <= 3)
                        high_quality = read.detector_score >= .65 and read.ocr_score >= .80
                        count = (old[1] + 1) if consecutive and high_quality else (1 if high_quality else 0)
                        streaks[plate] = (packet.stream_generation, count,
                                          packet.source_pts, packet.sequence)
                        # Two concordant reads and high detector/OCR scores are needed for an alert.
                        confirmed = count >= 2
                        self.store.record_read(
                            camera_id=camera_id, source_mode=packet.source_mode,
                            source_pts=packet.source_pts, pts_timebase=packet.pts_timebase,
                            stream_generation=packet.stream_generation,
                            received_utc=packet.received_utc, raw_text=read.raw_text,
                            detector_score=read.detector_score, ocr_score=read.ocr_score,
                            bbox=(x1, y1, x2, y2), crop_jpeg=encoded.tobytes(),
                            model_version=model.model_version, confirmed=confirmed,
                        )
                except Exception as error:
                    # Model errors can include internal paths. Expose only the type.
                    self.store.update_counters(camera_id, error=type(error).__name__)
                    if self.recognizer is None:
                        break
        finally:
            self.captures.release(worker)
