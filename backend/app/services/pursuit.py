"""Measured-budget active sampling and an operational coverage ledger.

Scores are transparent heuristics, never calibrated route probabilities. Coverage
uses worker acknowledgements and counter deltas, not requested sampling rates.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.storage.database import Database, utc_now
from app.services.journey import JourneyStore
from app.vision.pipeline import AnalyticsCoordinator
from app.ingest.capture import CaptureManager


def _distance_km(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (
        a["latitude"], a["longitude"], b["latitude"], b["longitude"]
    ))
    angle = 2 * math.asin(math.sqrt(
        math.sin((lat2 - lat1) / 2) ** 2 +
        math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    ))
    return 6371.0 * angle


def allocate_rates(selected: list[dict], available_fps: float,
                   has_confirmed_origin: bool) -> dict[str, float]:
    """Pure, reproducible allocation shared with the equal-budget replay."""
    if not selected:
        return {}
    baseline = max(.2, min(1.0, available_fps * .4 / len(selected)))
    rates = {row["camera_id"]: baseline for row in selected}
    spare = max(0.0, available_fps - baseline * len(selected))
    if has_confirmed_origin:
        weights = {row["camera_id"]: 1 / row["rank"] for row in selected}
        total_weight = sum(weights.values())
        for row in selected:
            camera_id = row["camera_id"]
            rates[camera_id] += min(spare * weights[camera_id] / total_weight,
                                    10 - rates[camera_id])
    else:
        for row in selected:
            rates[row["camera_id"]] += min(spare / len(selected),
                                            10 - rates[row["camera_id"]])
    return {camera_id: math.floor(rate * 1000) / 1000
            for camera_id, rate in rates.items()}


class ActivePursuit:
    def __init__(self, db: Database, journeys: JourneyStore,
                 analytics: AnalyticsCoordinator, captures: CaptureManager):
        self.db, self.journeys = db, journeys
        self.analytics, self.captures = analytics, captures
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.monitor: threading.Thread | None = None
        self.saturation_seen: dict[str, int] = {}
        self.monitor_last_tick_utc: str | None = None
        self.monitor_last_error: str | None = None

    def migrate(self) -> None:
        with self.db.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS camera_capture_errors (
                    camera_id TEXT PRIMARY KEY REFERENCES cameras(camera_id),
                    count INTEGER NOT NULL DEFAULT 0,
                    last_kind TEXT
                );
                CREATE TABLE IF NOT EXISTS capacity_measurements (
                    id TEXT PRIMARY KEY, measured_utc TEXT NOT NULL,
                    duration_seconds REAL NOT NULL, feed_count INTEGER NOT NULL,
                    analyzed_frames INTEGER NOT NULL, decoded_frames INTEGER NOT NULL,
                    sustainable_fps REAL NOT NULL, codec TEXT NOT NULL,
                    resolution TEXT NOT NULL, model_provider TEXT NOT NULL,
                    source_mode TEXT NOT NULL, method TEXT NOT NULL,
                    evidence_note TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pursuit_schedules (
                    id TEXT PRIMARY KEY, pursuit_id TEXT NOT NULL REFERENCES pursuits(id),
                    revision INTEGER NOT NULL, created_utc TEXT NOT NULL,
                    ended_utc TEXT, measurement_id TEXT NOT NULL REFERENCES capacity_measurements(id),
                    budget_fps REAL NOT NULL, reserved_fps REAL NOT NULL,
                    latest_sighting_id TEXT, input_signature TEXT NOT NULL,
                    reason TEXT NOT NULL, UNIQUE(pursuit_id,revision)
                );
                CREATE INDEX IF NOT EXISTS pursuit_schedule_latest
                    ON pursuit_schedules(pursuit_id,revision DESC);
                CREATE TABLE IF NOT EXISTS schedule_allocations (
                    schedule_id TEXT NOT NULL REFERENCES pursuit_schedules(id),
                    camera_id TEXT NOT NULL REFERENCES cameras(camera_id),
                    rank INTEGER NOT NULL, requested_fps REAL NOT NULL,
                    applied_fps REAL NOT NULL DEFAULT 0,
                    acknowledged_utc TEXT, baseline_received INTEGER NOT NULL,
                    baseline_analyzed INTEGER NOT NULL,
                    baseline_decode_errors INTEGER NOT NULL,
                    end_received INTEGER, end_analyzed INTEGER,
                    end_decode_errors INTEGER,
                    end_health TEXT,
                    factors_json TEXT NOT NULL, allocation_reason TEXT NOT NULL,
                    PRIMARY KEY(schedule_id,camera_id)
                );
                INSERT OR IGNORE INTO schema_migrations(version) VALUES(4);
            """)
            columns = {row["name"] for row in
                       connection.execute("PRAGMA table_info(schedule_allocations)")}
            for name, kind in (("end_received", "INTEGER"),
                               ("end_analyzed", "INTEGER"),
                               ("end_decode_errors", "INTEGER"),
                               ("end_health", "TEXT")):
                if name not in columns:
                    connection.execute(f"ALTER TABLE schedule_allocations ADD COLUMN {name} {kind}")

    def start_monitor(self) -> None:
        self.stop_event.clear()
        self.monitor = threading.Thread(target=self._monitor_loop, name="pursuit-monitor", daemon=True)
        self.monitor.start()

    def shutdown(self) -> None:
        self.stop_event.set()
        if self.monitor:
            self.monitor.join(timeout=5)

    def _monitor_loop(self) -> None:
        while not self.stop_event.wait(3):
            try:
                with self.db.connection() as connection:
                    rows = connection.execute(
                        "SELECT DISTINCT pursuit_id FROM pursuit_schedules WHERE ended_utc IS NULL"
                    ).fetchall()
                for row in rows:
                    self.tick(row["pursuit_id"])
                self.monitor_last_tick_utc = utc_now()
                self.monitor_last_error = None
            except Exception as error:
                self.monitor_last_error = type(error).__name__
                logging.getLogger(__name__).warning(
                    "Active Pursuit monitor iteration failed: %s", type(error).__name__
                )
                continue

    def monitor_status(self) -> dict:
        return {"running": bool(self.monitor and self.monitor.is_alive()),
                "last_tick_utc": self.monitor_last_tick_utc,
                "last_error_type": self.monitor_last_error}

    def add_measurement(self, body: dict) -> dict:
        duration = float(body["duration_seconds"])
        analyzed = int(body["analyzed_frames"])
        decoded = int(body["decoded_frames"])
        if duration < 10 or analyzed <= 0 or decoded < analyzed:
            raise ValueError("Benchmark needs at least 10 seconds and consistent decoded/analyzed counts")
        fps = analyzed / duration
        row = {
            "id": uuid.uuid4().hex, "measured_utc": utc_now(),
            "duration_seconds": duration, "feed_count": int(body["feed_count"]),
            "analyzed_frames": analyzed, "decoded_frames": decoded,
            "sustainable_fps": round(fps, 4), "codec": body["codec"],
            "resolution": body["resolution"], "model_provider": body["model_provider"],
            "source_mode": body["source_mode"], "method": body["method"],
            "evidence_note": body["evidence_note"],
        }
        if row["feed_count"] < 1 or row["feed_count"] > self.analytics.max_cameras:
            raise ValueError("Benchmark feed count exceeds prototype worker count")
        with self.db.connection() as connection:
            connection.execute(
                """INSERT INTO capacity_measurements VALUES
                   (:id,:measured_utc,:duration_seconds,:feed_count,:analyzed_frames,
                    :decoded_frames,:sustainable_fps,:codec,:resolution,:model_provider,
                    :source_mode,:method,:evidence_note)""", row,
            )
        return {**row, "budget_fps": round(.7 * fps, 4), "headroom_fraction": .30}

    def latest_measurement(self) -> dict | None:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT * FROM capacity_measurements ORDER BY measured_utc DESC,id DESC LIMIT 1"
            ).fetchone()
        return {**dict(row), "budget_fps": round(.7 * row["sustainable_fps"], 4),
                "headroom_fraction": .30} if row else None

    def _measurement(self, measurement_id: str) -> dict | None:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT * FROM capacity_measurements WHERE id=?", (measurement_id,)
            ).fetchone()
        return {**dict(row), "budget_fps": round(.7 * row["sustainable_fps"], 4),
                "headroom_fraction": .30} if row else None

    def _journey(self, pursuit_id: str, department: str | None) -> dict:
        result = self.journeys.journey(pursuit_id, department)
        if result is None:
            raise KeyError(pursuit_id)
        return result

    def _latest_operational_observation(self, journey: dict) -> dict | None:
        observations = journey["observations"]
        if not observations:
            return None
        by_id = {item["id"]: item for item in observations}
        placeholders = ",".join("?" for _ in by_id)
        with self.db.connection() as connection:
            row = connection.execute(
                f"""SELECT sighting_id FROM sighting_read_events
                    WHERE sighting_id IN ({placeholders})
                    ORDER BY received_utc DESC,id DESC LIMIT 1""",
                list(by_id),
            ).fetchone()
        return by_id[row["sighting_id"]] if row else journey["latest_confirmed"]

    def rankings(self, pursuit_id: str, department: str | None) -> dict:
        journey = self._journey(pursuit_id, department)
        source = self._latest_operational_observation(journey)
        pursuit = journey["pursuit"]
        cameras = [camera for camera in self.db.cameras()
                   if camera["catalogue_present"] and
                   (pursuit["department_scope"] is None or
                    camera["department"] == pursuit["department_scope"])]
        results = []
        for camera in cameras:
            if not self.db.source_urls(camera["camera_id"]):
                continue
            distance = _distance_km(source, camera) if source else None
            proximity = round(1 / (1 + distance / 12), 4) if distance is not None else .5
            health = {"online": 1.0, "unknown": .55, "idle": .55,
                      "degraded": .15, "offline": .05}.get(camera["health_status"], .5)
            pixels = (camera["width"] or 0) * (camera["height"] or 0)
            readability_proxy = min(1.0, max(.25, pixels / (1280 * 720))) if pixels else .5
            analysis = self.analytics.status(camera["camera_id"])
            queue_age = analysis["last_queue_age_ms"]
            queue_factor = round(1 / (1 + queue_age / 250), 4) if queue_age is not None else .5
            cost_factor = round(1 / (1 + pixels / (1920 * 1080)), 4) if pixels else .65
            factors = {"distance_km_straight_line": round(distance, 2) if distance is not None else None,
                       "proximity": proximity, "health": health,
                       "readability_resolution_proxy": round(readability_proxy, 4),
                       "queue_age_ms": round(queue_age, 2) if queue_age is not None else None,
                       "queue_delay_proxy": queue_factor, "analysis_cost_proxy": cost_factor}
            score = round(.38 * proximity + .27 * health + .15 * readability_proxy +
                          .12 * queue_factor + .08 * cost_factor, 4)
            if source and camera["camera_id"] == source["camera_id"]:
                score = round(score - .30, 4)
            results.append({"camera_id": camera["camera_id"],
                            "display_name": camera["display_name"],
                            "health_status": camera["health_status"],
                            "source_mode": camera["source_mode"], "score": score,
                            "factors": factors,
                            "readability_note": "Resolution proxy only; plate readability uncalibrated"})
        results.sort(key=lambda row: (-row["score"], row["camera_id"]))
        for index, row in enumerate(results, 1):
            row["rank"] = index
        return {"pursuit_id": pursuit_id,
                "latest_confirmed_sighting_id": source["id"] if source else None,
                "latest_confirmed_camera_id": source["camera_id"] if source else None,
                "basis": "latest supported confirmed read by operational receive time; media/event clock may differ" if source else "uniform fallback: no supported confirmed sighting",
                "score_meaning": "deterministic heuristic, not a route probability",
                "direction": "unknown; candidates remain in multiple directions",
                "travel_window": "No ETA inferred without a validated road network and live clock",
                "rankings": results}

    def _current(self, pursuit_id: str) -> dict | None:
        with self.db.connection() as connection:
            row = connection.execute(
                """SELECT * FROM pursuit_schedules WHERE pursuit_id=?
                   ORDER BY revision DESC LIMIT 1""", (pursuit_id,)
            ).fetchone()
        return dict(row) if row else None

    def _allocations(self, schedule_id: str) -> list[dict]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM schedule_allocations WHERE schedule_id=? ORDER BY rank,camera_id",
                (schedule_id,),
            )]

    def guard_manual_analysis(self, camera_id: str, proposed_fps: float | None) -> None:
        """Prevent an API rate change from silently crossing an active budget."""
        with self.lock:
            with self.db.connection() as connection:
                row = connection.execute(
                    """SELECT * FROM pursuit_schedules WHERE ended_utc IS NULL
                       ORDER BY created_utc DESC LIMIT 1"""
                ).fetchone()
            if not row:
                return
            allocations = self._allocations(row["id"])
            managed = {item["camera_id"] for item in allocations if item["requested_fps"] > 0}
            if camera_id in managed:
                raise ValueError("Stop Active Pursuit before changing a scheduled worker")
            if proposed_fps is None:
                return
            requested = sum(item["requested_fps"] for item in allocations)
            external = sum(self.analytics.status(camera["camera_id"])["sample_fps"]
                           for camera in self.db.cameras()
                           if camera["camera_id"] not in managed and
                           camera["camera_id"] != camera_id and
                           self.analytics.status(camera["camera_id"])["running"])
            if requested + external + proposed_fps > row["budget_fps"] + 1e-6:
                raise ValueError("Manual analysis would exceed the measured pursuit frame budget")

    def _signature(self, ranks: dict, measurement: dict) -> str:
        return json.dumps({"sighting": ranks["latest_confirmed_sighting_id"],
                           "measurement": measurement["id"],
                           "rankings": [(r["camera_id"], r["health_status"])
                                        for r in ranks["rankings"]]},
                          sort_keys=True)

    def schedule(self, pursuit_id: str, department: str | None, reason: str = "operator started",
                 budget_scale: float = 1.0) -> dict:
        with self.lock:
            ranks = self.rankings(pursuit_id, department)
            measurement = self.latest_measurement()
            if not measurement:
                raise ValueError("No measured end-to-end capacity benchmark is recorded")
            with self.db.connection() as connection:
                other = connection.execute(
                    """SELECT pursuit_id FROM pursuit_schedules WHERE ended_utc IS NULL
                       AND pursuit_id<>? LIMIT 1""", (pursuit_id,),
                ).fetchone()
            if other:
                raise ValueError("Prototype supports one active pursuit at a time")
            prior = self._current(pursuit_id)
            old_allocations = self._allocations(prior["id"]) if prior and not prior["ended_utc"] else []
            old_ids = {row["camera_id"] for row in old_allocations if row["requested_fps"] > 0}
            active_external = [camera for camera in self.db.cameras()
                               if camera["camera_id"] not in old_ids and
                               self.analytics.status(camera["camera_id"])["running"]]
            external_ids = {camera["camera_id"] for camera in active_external}
            reserved = sum(self.analytics.status(camera["camera_id"])["sample_fps"]
                           for camera in active_external)
            remaining = round(measurement["budget_fps"] * budget_scale - reserved, 4)
            if remaining < .2:
                raise ValueError("Measured budget is consumed by existing analysis workers")
            slots = self.analytics.max_cameras - len(active_external)
            if slots < 1:
                raise ValueError("No analysis worker slot is available")
            # Every selected camera gets at least 0.2 fps; others are explicit gaps.
            eligible = [row for row in ranks["rankings"] if row["camera_id"] not in external_ids]
            count = min(slots, len(eligible), math.floor(remaining / .2))
            if count < 1:
                raise ValueError("Measured budget cannot sustain the minimum per-camera rate")
            selected = eligible[:count]
            selected_ids = {row["camera_id"] for row in selected}
            rates = allocate_rates(selected, remaining,
                                   bool(ranks["latest_confirmed_sighting_id"]))
            assert sum(rates.values()) + reserved <= measurement["budget_fps"] + 1e-6
            created = utc_now()
            schedule_id = uuid.uuid4().hex
            signature = self._signature(ranks, measurement)
            revision = (prior["revision"] + 1) if prior else 1
            if prior and not prior["ended_utc"]:
                self._finalize(prior["id"])
            for camera_id in old_ids - selected_ids:
                self.analytics.stop(camera_id)
            with self.db.connection() as connection:
                if prior and not prior["ended_utc"]:
                    connection.execute("UPDATE pursuit_schedules SET ended_utc=? WHERE id=?",
                                       (created, prior["id"]))
                connection.execute(
                    """INSERT INTO pursuit_schedules VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (schedule_id, pursuit_id, revision, created, None, measurement["id"],
                     measurement["budget_fps"], round(reserved, 3),
                     ranks["latest_confirmed_sighting_id"], signature, reason),
                )
                for row in ranks["rankings"]:
                    camera_id = row["camera_id"]
                    status = self.analytics.status(camera_id)
                    connection.execute(
                        """INSERT INTO schedule_allocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (schedule_id, camera_id, row["rank"], rates.get(camera_id, 0),
                         0, None, status["received"], status["analyzed"],
                         self.db.capture_error_count(camera_id), None, None, None, None,
                         json.dumps(row["factors"], sort_keys=True),
                         "baseline + ranked spare" if camera_id in rates else "capacity excluded"),
                    )
            for camera_id, rate in rates.items():
                try:
                    self.analytics.start(camera_id, rate)
                except (KeyError, ValueError):
                    # The failed worker has applied 0 fps; the ledger exposes the gap.
                    pass
            return self.get_schedule(pursuit_id, department)

    def _reconcile(self, schedule_id: str) -> None:
        allocations = self._allocations(schedule_id)
        with self.db.connection() as connection:
            for row in allocations:
                if row["requested_fps"] <= 0:
                    continue
                status = self.analytics.status(row["camera_id"])
                applied = (row["requested_fps"] if
                           abs(row["requested_fps"] - status["applied_fps"]) < .005 else 0)
                if applied > 0:
                    connection.execute(
                        """UPDATE schedule_allocations SET applied_fps=?,
                           acknowledged_utc=COALESCE(acknowledged_utc,?)
                           WHERE schedule_id=? AND camera_id=?""",
                        (applied, status["acknowledged_utc"], schedule_id, row["camera_id"]),
                    )

    def _finalize(self, schedule_id: str) -> None:
        self._reconcile(schedule_id)
        with self.db.connection() as connection:
            for row in self._allocations(schedule_id):
                status = self.analytics.status(row["camera_id"])
                connection.execute(
                    """UPDATE schedule_allocations SET end_received=?,end_analyzed=?,
                       end_decode_errors=?,end_health=? WHERE schedule_id=? AND camera_id=?""",
                    (status["received"], status["analyzed"],
                     self.db.capture_error_count(row["camera_id"]),
                     (self.db.camera(row["camera_id"]) or {}).get("health_status"),
                     schedule_id, row["camera_id"]),
                )

    def get_schedule(self, pursuit_id: str, department: str | None) -> dict:
        self._journey(pursuit_id, department)
        with self.lock:
            current = self._current(pursuit_id)
            if not current:
                return {"pursuit_id": pursuit_id, "active": False, "schedule": None,
                        "measurement": self.latest_measurement(), "allocations": []}
            self._reconcile(current["id"])
            allocations = self._allocations(current["id"])
            for row in allocations:
                row["factors"] = json.loads(row.pop("factors_json"))
                status = self.analytics.status(row["camera_id"])
                row["current_applied_fps"] = (
                    row["requested_fps"] if not current["ended_utc"] and
                    abs(row["requested_fps"] - status["applied_fps"]) < .005 else 0
                )
                row["health_status"] = (self.db.camera(row["camera_id"]) or {}).get("health_status")
            return {"pursuit_id": pursuit_id, "active": current["ended_utc"] is None,
                    "schedule": current, "measurement": self._measurement(current["measurement_id"]),
                    "allocations": allocations,
                    "requested_total_fps": round(sum(x["requested_fps"] for x in allocations), 3),
                    "current_applied_total_fps": round(sum(x["current_applied_fps"] for x in allocations), 3)}

    def coverage(self, pursuit_id: str, department: str | None) -> dict:
        journey = self._journey(pursuit_id, department)
        with self.db.connection() as connection:
            runs = [dict(row) for row in connection.execute(
                "SELECT * FROM pursuit_schedules WHERE pursuit_id=? ORDER BY revision DESC",
                (pursuit_id,),
            )]
        windows = []
        for run in runs:
            self._reconcile(run["id"])
            end = run["ended_utc"] or utc_now()
            duration = max(0, (datetime.fromisoformat(end) -
                               datetime.fromisoformat(run["created_utc"])).total_seconds())
            for allocation in self._allocations(run["id"]):
                camera_id = allocation["camera_id"]
                camera = self.db.camera(camera_id)
                health = allocation["end_health"] or camera["health_status"]
                status = self.analytics.status(camera_id)
                received = max(0, (allocation["end_received"] if allocation["end_received"] is not None
                                   else status["received"]) - allocation["baseline_received"])
                analyzed = max(0, (allocation["end_analyzed"] if allocation["end_analyzed"] is not None
                                   else status["analyzed"]) - allocation["baseline_analyzed"])
                errors = max(0, (allocation["end_decode_errors"] if allocation["end_decode_errors"] is not None
                                  else self.db.capture_error_count(camera_id)) -
                             allocation["baseline_decode_errors"])
                # An acknowledged rate is historical intent made real by a worker;
                # coverage still requires the actual analyzed count in this window.
                if allocation["acknowledged_utc"]:
                    acknowledged = datetime.fromisoformat(allocation["acknowledged_utc"])
                    active_seconds = max(0, (datetime.fromisoformat(end) -
                                             max(datetime.fromisoformat(run["created_utc"]), acknowledged)).total_seconds())
                else:
                    active_seconds = 0
                planned = math.floor(allocation["applied_fps"] * active_seconds)
                supported_ids = {record["id"] for record in journey["observations"]
                                 if record["camera_id"] == camera_id}
                with self.db.connection() as connection:
                    read_ids = [row["sighting_id"] for row in connection.execute(
                        """SELECT sighting_id FROM sighting_read_events
                           WHERE camera_id=? AND received_utc>=? AND received_utc<=?
                           ORDER BY received_utc""",
                        (camera_id, run["created_utc"], end),
                    )]
                matching = [sighting_id for sighting_id in read_ids
                            if sighting_id in supported_ids]
                if matching and analyzed > 0:
                    result, reason = "observed", "Evidence-supported confirmed sighting during this sampled window"
                elif health in {"offline", "degraded"} and analyzed == 0:
                    result, reason = "feed unavailable", "No analyzed frames; feed health unavailable"
                elif allocation["requested_fps"] <= 0:
                    result, reason = "insufficient coverage", "Camera excluded by measured capacity/worker limit"
                elif planned < 2 or analyzed < max(2, math.floor(planned * .7)):
                    result, reason = "insufficient coverage", "Worker did not analyze enough of its acknowledged plan"
                else:
                    result, reason = "not observed in sampled frames", "Target absent only from frames actually sampled"
                windows.append({"schedule_id": run["id"], "revision": run["revision"],
                                "camera_id": camera_id, "window_start_utc": run["created_utc"],
                                "window_end_utc": end, "timebase": "operational server UTC; not camera event UTC",
                                "planned_frames": planned, "received_frames": received,
                                "analyzed_frames": analyzed, "decode_errors": errors,
                                "health": health,
                                "requested_fps": allocation["requested_fps"],
                                "applied_fps": allocation["applied_fps"],
                                "result_code": result, "reason": reason,
                                "observed_sighting_id": matching[-1] if matching and analyzed else None})
        return {"pursuit_id": pursuit_id, "windows": windows,
                "negative_result_contract": "Not observed in sampled frames never proves absence",
                "clock_contract": "Window times are operational UTC; sighting event UTC remains separately qualified"}

    def stop(self, pursuit_id: str, department: str | None) -> dict:
        self._journey(pursuit_id, department)
        with self.lock:
            current = self._current(pursuit_id)
            if current and not current["ended_utc"]:
                self._finalize(current["id"])
                with self.db.connection() as connection:
                    connection.execute("UPDATE pursuit_schedules SET ended_utc=? WHERE id=?",
                                       (utc_now(), current["id"]))
                for row in self._allocations(current["id"]):
                    if row["requested_fps"] > 0:
                        self.analytics.stop(row["camera_id"])
            return self.get_schedule(pursuit_id, department)

    def tick(self, pursuit_id: str) -> None:
        with self.lock:
            current = self._current(pursuit_id)
            if not current or current["ended_utc"]:
                return
            measurement = self.latest_measurement()
            ranks = self.rankings(pursuit_id, None)
            signature = self._signature(ranks, measurement)
            age = (datetime.now(timezone.utc) -
                   datetime.fromisoformat(current["created_utc"])).total_seconds()
            overloaded = False
            for row in self._allocations(current["id"]):
                if row["requested_fps"] > 0:
                    status = self.analytics.status(row["camera_id"])
                    if status["last_latency_ms"] and status["last_latency_ms"] > (
                        900 / row["requested_fps"]
                    ):
                        overloaded = True
            self.saturation_seen[pursuit_id] = (self.saturation_seen.get(pursuit_id, 0) + 1
                                                 if overloaded else 0)
            if self.saturation_seen[pursuit_id] >= 2:
                already_shed = current["reason"] == "worker latency saturation: load shed"
                if already_shed and signature == current["input_signature"]:
                    self._reconcile(current["id"])
                    return
                if (already_shed and age < 8 and
                        ranks["latest_confirmed_sighting_id"] == current["latest_sighting_id"]):
                    return
                self.saturation_seen[pursuit_id] = 0
                self.schedule(pursuit_id, None, "worker latency saturation: load shed",
                              budget_scale=.75)
                return
            if signature != current["input_signature"]:
                if (ranks["latest_confirmed_sighting_id"] == current["latest_sighting_id"]
                        and age < 8):
                    return
                self.schedule(pursuit_id, None, "confirmed sighting / feed / queue change")
                return
            self._reconcile(current["id"])
