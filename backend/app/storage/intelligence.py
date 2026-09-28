from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.storage.database import Database, utc_now


def normalize_plate(raw: str) -> str:
    return "".join(character for character in raw.upper() if character.isalnum() and character.isascii())


def needs_manual_review(plate: str) -> bool:
    # A Gujarat registration has two state letters, two district digits,
    # one to three series letters, then four digits. OCR O/0 or I/1 mistakes
    # in those slots are candidates, never automatic watchlist hits.
    return plate.startswith("GJ") and not bool(
        re.fullmatch(r"GJ[0-9]{2}[A-Z]{1,3}[0-9]{4}", plate)
    )


class IntelligenceStore:
    def __init__(self, database: Database, evidence_dir: Path):
        self.db = database
        self.evidence_dir = Path(evidence_dir)

    def migrate(self) -> None:
        with self.db.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS analysis_settings (
                    camera_id TEXT PRIMARY KEY REFERENCES cameras(camera_id),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    sample_fps REAL NOT NULL DEFAULT 2,
                    updated_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analysis_counters (
                    camera_id TEXT PRIMARY KEY REFERENCES cameras(camera_id),
                    received INTEGER NOT NULL DEFAULT 0,
                    selected INTEGER NOT NULL DEFAULT 0,
                    analyzed INTEGER NOT NULL DEFAULT 0,
                    dropped INTEGER NOT NULL DEFAULT 0,
                    detections INTEGER NOT NULL DEFAULT 0,
                    last_latency_ms REAL,
                    last_queue_age_ms REAL,
                    last_error TEXT,
                    execution_provider TEXT NOT NULL DEFAULT 'uninitialized',
                    model_version TEXT
                );
                CREATE TABLE IF NOT EXISTS sightings (
                    id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL REFERENCES cameras(camera_id),
                    source_mode TEXT NOT NULL,
                    source_pts REAL,
                    pts_timebase TEXT,
                    stream_generation INTEGER NOT NULL,
                    received_utc TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    plate_normalized TEXT NOT NULL,
                    detector_score REAL NOT NULL,
                    ocr_score REAL NOT NULL,
                    review_status TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    evidence_path TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    bbox_json TEXT NOT NULL,
                    first_seen_utc TEXT NOT NULL,
                    last_seen_utc TEXT NOT NULL,
                    read_count INTEGER NOT NULL DEFAULT 1,
                    raw_reads_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sightings_search ON sightings(plate_normalized,received_utc DESC);
                CREATE INDEX IF NOT EXISTS sightings_camera ON sightings(camera_id,last_seen_utc DESC);
                CREATE TABLE IF NOT EXISTS watchlist (
                    id TEXT PRIMARY KEY,
                    plate_normalized TEXT NOT NULL,
                    category TEXT NOT NULL,
                    source_label TEXT NOT NULL,
                    created_utc TEXT NOT NULL,
                    expires_utc TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    actor TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS watchlist_match ON watchlist(plate_normalized,active);
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    sighting_id TEXT NOT NULL REFERENCES sightings(id),
                    watchlist_id TEXT NOT NULL REFERENCES watchlist(id),
                    status TEXT NOT NULL DEFAULT 'new',
                    match_basis TEXT NOT NULL,
                    created_utc TEXT NOT NULL,
                    acknowledged_utc TEXT,
                    acknowledged_by TEXT,
                    UNIQUE(sighting_id,watchlist_id)
                );
                CREATE INDEX IF NOT EXISTS alerts_newest ON alerts(created_utc DESC);
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT NOT NULL REFERENCES alerts(id),
                    at_utc TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS intelligence_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at_utc TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sighting_read_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sighting_id TEXT NOT NULL REFERENCES sightings(id),
                    camera_id TEXT NOT NULL REFERENCES cameras(camera_id),
                    received_utc TEXT NOT NULL,
                    source_pts REAL,
                    stream_generation INTEGER NOT NULL,
                    model_confirmed INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sighting_read_events_window
                    ON sighting_read_events(camera_id,received_utc,sighting_id);
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(analysis_counters)")}
            if "last_queue_age_ms" not in columns:
                connection.execute("ALTER TABLE analysis_counters ADD COLUMN last_queue_age_ms REAL")
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(2)")

    def set_analysis(self, camera_id: str, enabled: bool, sample_fps: float) -> None:
        now = utc_now()
        with self.db.connection() as connection:
            connection.execute(
                """INSERT INTO analysis_settings(camera_id,enabled,sample_fps,updated_utc)
                   VALUES(?,?,?,?) ON CONFLICT(camera_id) DO UPDATE SET
                   enabled=excluded.enabled,sample_fps=excluded.sample_fps,updated_utc=excluded.updated_utc""",
                (camera_id, int(enabled), sample_fps, now),
            )
            connection.execute(
                "INSERT OR IGNORE INTO analysis_counters(camera_id) VALUES(?)", (camera_id,)
            )

    def enabled_analyses(self) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM analysis_settings WHERE enabled=1 ORDER BY camera_id"
            )]

    def analysis_status(self, camera_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute(
                """SELECT s.enabled,s.sample_fps,c.received,c.selected,c.analyzed,c.dropped,
                   c.detections,c.last_latency_ms,c.last_queue_age_ms,c.last_error,
                   c.execution_provider,c.model_version
                   FROM analysis_settings s LEFT JOIN analysis_counters c USING(camera_id)
                   WHERE s.camera_id=?""", (camera_id,)
            ).fetchone()
        return {"camera_id": camera_id, **dict(row)} if row else {
            "camera_id": camera_id, "enabled": False, "sample_fps": 2.0,
            "received": 0, "selected": 0, "analyzed": 0, "dropped": 0,
            "detections": 0, "last_latency_ms": None, "last_queue_age_ms": None,
            "last_error": None,
            "execution_provider": "uninitialized", "model_version": None,
        }

    def update_counters(self, camera_id: str, *, received: int = 0, selected: int = 0,
                        analyzed: int = 0, dropped: int = 0, detections: int = 0,
                        latency_ms: float | None = None,
                        queue_age_ms: float | None = None, error: str | None = None,
                        provider: str | None = None, model_version: str | None = None) -> None:
        with self.db.connection() as connection:
            connection.execute("INSERT OR IGNORE INTO analysis_counters(camera_id) VALUES(?)", (camera_id,))
            connection.execute(
                """UPDATE analysis_counters SET received=received+?,selected=selected+?,
                   analyzed=analyzed+?,dropped=dropped+?,detections=detections+?,
                   last_latency_ms=COALESCE(?,last_latency_ms),
                   last_queue_age_ms=COALESCE(?,last_queue_age_ms),
                   last_error=?,execution_provider=COALESCE(?,execution_provider),
                   model_version=COALESCE(?,model_version) WHERE camera_id=?""",
                (received, selected, analyzed, dropped, detections, latency_ms,
                 queue_age_ms, error,
                 provider, model_version, camera_id),
            )

    def _write_evidence(self, image: bytes) -> tuple[str, str]:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.jpg"
        path = self.evidence_dir / name
        temporary = self.evidence_dir / f".{name}.tmp"
        temporary.write_bytes(image)
        os.replace(temporary, path)
        return str(path), hashlib.sha256(image).hexdigest()

    @staticmethod
    def _public_sighting(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item.pop("evidence_path", None)
        item["bbox"] = json.loads(item.pop("bbox_json"))
        item["raw_reads"] = json.loads(item.pop("raw_reads_json"))
        item["evidence_url"] = f"/api/v1/sightings/{item['id']}/evidence.jpg"
        item["event_utc_if_verified"] = None
        item["timestamp_provenance"] = (
            "source_pts_per_stream" if item["source_pts"] is not None
            else "receive_time_diagnostic_only"
        )
        item["timestamp_uncertainty"] = "no_verified_cross_camera_utc_alignment"
        return item

    def record_read(self, *, camera_id: str, source_mode: str, source_pts: float | None,
                    pts_timebase: str | None, stream_generation: int, received_utc: str,
                    raw_text: str, detector_score: float, ocr_score: float,
                    bbox: tuple[int, int, int, int], crop_jpeg: bytes,
                    model_version: str, confirmed: bool) -> dict[str, Any]:
        plate = normalize_plate(raw_text)
        if len(plate) < 4 or len(plate) > 16:
            raise ValueError("OCR text is not a useful plate candidate")
        now = utc_now()
        raw_read = {"text": raw_text, "detector_score": detector_score,
                    "ocr_score": ocr_score, "source_pts": source_pts,
                    "received_utc": received_utc}
        with self.db.connection() as connection:
            previous = connection.execute(
                """SELECT * FROM sightings WHERE camera_id=? AND plate_normalized=?
                   AND stream_generation=? ORDER BY last_seen_utc DESC LIMIT 1""",
                (camera_id, plate, stream_generation),
            ).fetchone()
            same_encounter = previous is not None and (
                datetime.fromisoformat(now) - datetime.fromisoformat(previous["last_seen_utc"])
                <= timedelta(seconds=45)
            )
            if same_encounter:
                sighting_id = previous["id"]
                reads = json.loads(previous["raw_reads_json"])[-19:] + [raw_read]
                # The stored PTS, receipt time, box, and image must describe the
                # same observation. Prefer a timed read over an untimed one even
                # when its score is slightly lower.
                better = (
                    (previous["source_pts"] is None and source_pts is not None)
                    or (
                        (source_pts is not None or previous["source_pts"] is None)
                        and detector_score * ocr_score >
                        previous["detector_score"] * previous["ocr_score"]
                    )
                )
                path, digest = (
                    self._write_evidence(crop_jpeg) if better
                    else (previous["evidence_path"], previous["evidence_sha256"])
                )
                status = ("confirmed" if not needs_manual_review(plate) and
                          (confirmed or previous["review_status"] == "confirmed")
                          else "candidate")
                connection.execute(
                    """UPDATE sightings SET source_pts=?,pts_timebase=?,received_utc=?,
                       raw_text=?,detector_score=?,ocr_score=?,review_status=?,
                       evidence_path=?,evidence_sha256=?,bbox_json=?,last_seen_utc=?,
                       read_count=read_count+1,raw_reads_json=? WHERE id=?""",
                    (source_pts if better else previous["source_pts"],
                     pts_timebase if better else previous["pts_timebase"],
                     received_utc if better else previous["received_utc"],
                     raw_text if better else previous["raw_text"],
                     detector_score if better else previous["detector_score"],
                     ocr_score if better else previous["ocr_score"], status, path, digest,
                     json.dumps(bbox if better else json.loads(previous["bbox_json"])),
                     now, json.dumps(reads), sighting_id),
                )
            else:
                sighting_id = uuid.uuid4().hex
                path, digest = self._write_evidence(crop_jpeg)
                status = "confirmed" if confirmed and not needs_manual_review(plate) else "candidate"
                connection.execute(
                    """INSERT INTO sightings(id,camera_id,source_mode,source_pts,pts_timebase,
                       stream_generation,received_utc,raw_text,plate_normalized,detector_score,
                       ocr_score,review_status,model_version,evidence_path,evidence_sha256,
                       bbox_json,first_seen_utc,last_seen_utc,raw_reads_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sighting_id, camera_id, source_mode, source_pts, pts_timebase,
                     stream_generation, received_utc, raw_text, plate, detector_score,
                     ocr_score, status, model_version, path, digest, json.dumps(bbox),
                     now, now, json.dumps([raw_read])),
                )
            connection.execute(
                """INSERT INTO sighting_read_events(sighting_id,camera_id,received_utc,
                   source_pts,stream_generation,model_confirmed) VALUES(?,?,?,?,?,?)""",
                (sighting_id, camera_id, received_utc, source_pts,
                 stream_generation, int(status == "confirmed")),
            )
            item = self._public_sighting(connection.execute(
                "SELECT * FROM sightings WHERE id=?", (sighting_id,)
            ).fetchone())
            if not same_encounter:
                self._event(connection, "SightingCreated", {
                    "sighting_id": sighting_id, "camera_id": camera_id,
                    "plate_normalized": plate, "review_status": status,
                })
            # Only an exact, high-confidence, confirmed sighting may create a hit.
            if status == "confirmed":
                entries = connection.execute(
                    """SELECT id FROM watchlist WHERE plate_normalized=? AND active=1
                       AND (expires_utc IS NULL OR expires_utc>?)""", (plate, now)
                ).fetchall()
                for entry in entries:
                    cooldown_since = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
                    recent = connection.execute(
                        """SELECT a.id FROM alerts a JOIN sightings s ON a.sighting_id=s.id
                           WHERE a.watchlist_id=? AND s.camera_id=? AND s.plate_normalized=?
                           AND a.created_utc>=? LIMIT 1""",
                        (entry["id"], camera_id, plate, cooldown_since),
                    ).fetchone()
                    if recent:
                        continue
                    alert_id = uuid.uuid4().hex
                    cursor = connection.execute(
                        """INSERT OR IGNORE INTO alerts(id,sighting_id,watchlist_id,status,
                           match_basis,created_utc) VALUES(?,?,?,'new','exact_high_confidence',?)""",
                        (alert_id, sighting_id, entry["id"], now),
                    )
                    if cursor.rowcount:
                        connection.execute(
                            "INSERT INTO alert_history(alert_id,at_utc,actor,action) VALUES(?,?,?,?)",
                            (alert_id, now, "system", "created"),
                        )
                        self._event(connection, "AlertCreated", {
                            "alert_id": alert_id, "sighting_id": sighting_id,
                            "camera_id": camera_id, "plate_normalized": plate,
                        })
        return item

    @staticmethod
    def _event(connection: sqlite3.Connection, kind: str, payload: dict) -> None:
        connection.execute(
            "INSERT INTO intelligence_events(at_utc,kind,payload_json) VALUES(?,?,?)",
            (utc_now(), kind, json.dumps(payload)),
        )

    def sightings(self, plate: str | None = None, camera_id: str | None = None,
                  limit: int = 100) -> list[dict[str, Any]]:
        clauses, values = [], []
        if plate:
            clauses.append("plate_normalized=?")
            values.append(normalize_plate(plate))
        if camera_id:
            clauses.append("camera_id=?")
            values.append(camera_id)
        sql = "SELECT * FROM sightings"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY last_seen_utc DESC LIMIT ?"
        values.append(limit)
        with self.db.connection() as connection:
            return [self._public_sighting(row) for row in connection.execute(sql, values)]

    def sighting(self, sighting_id: str) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM sightings WHERE id=?", (sighting_id,)).fetchone()
            return self._public_sighting(row) if row else None

    def evidence(self, sighting_id: str) -> bytes | None:
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT evidence_path,evidence_sha256 FROM sightings WHERE id=?", (sighting_id,)
            ).fetchone()
        if not row:
            return None
        path = Path(row["evidence_path"])
        if not path.resolve().is_relative_to(self.evidence_dir.resolve()):
            return None
        try:
            data = path.read_bytes()
        except OSError:
            return None
        return data if hashlib.sha256(data).hexdigest() == row["evidence_sha256"] else None

    def create_watchlist(self, plate: str, category: str, source_label: str,
                         expires_utc: str | None, actor: str) -> dict[str, Any]:
        normalized = normalize_plate(plate)
        if not 4 <= len(normalized) <= 16:
            raise ValueError("Plate must have 4–16 alphanumeric characters")
        if expires_utc and datetime.fromisoformat(expires_utc) <= datetime.now(timezone.utc):
            raise ValueError("Expiry must be in the future")
        item = {"id": uuid.uuid4().hex, "plate_normalized": normalized,
                "category": category, "source_label": source_label, "created_utc": utc_now(),
                "expires_utc": expires_utc, "active": True, "actor": actor}
        with self.db.connection() as connection:
            connection.execute(
                """INSERT INTO watchlist(id,plate_normalized,category,source_label,
                   created_utc,expires_utc,active,actor) VALUES(?,?,?,?,?,?,1,?)""",
                (item["id"], normalized, category, source_label, item["created_utc"],
                 expires_utc, actor),
            )
        return item

    def watchlist(self) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM watchlist ORDER BY created_utc DESC"
            )]

    def disable_watchlist(self, entry_id: str) -> bool:
        with self.db.connection() as connection:
            return bool(connection.execute(
                "UPDATE watchlist SET active=0 WHERE id=?", (entry_id,)
            ).rowcount)

    def alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT a.*,s.camera_id,s.plate_normalized,w.category,w.source_label
                   FROM alerts a JOIN sightings s ON a.sighting_id=s.id
                   JOIN watchlist w ON a.watchlist_id=w.id
                   ORDER BY a.created_utc DESC LIMIT ?""", (limit,)
            )]

    def acknowledge_alert(self, alert_id: str, actor: str) -> bool:
        now = utc_now()
        with self.db.connection() as connection:
            cursor = connection.execute(
                """UPDATE alerts SET status='acknowledged',acknowledged_utc=?,
                   acknowledged_by=? WHERE id=? AND status='new'""",
                (now, actor, alert_id),
            )
            if cursor.rowcount:
                connection.execute(
                    "INSERT INTO alert_history(alert_id,at_utc,actor,action) VALUES(?,?,?,'acknowledged')",
                    (alert_id, now, actor),
                )
                camera = connection.execute(
                    """SELECT s.camera_id FROM alerts a JOIN sightings s ON a.sighting_id=s.id
                       WHERE a.id=?""", (alert_id,)
                ).fetchone()
                self._event(connection, "AlertAcknowledged", {
                    "alert_id": alert_id, "camera_id": camera["camera_id"] if camera else None,
                })
            return bool(cursor.rowcount)

    def alert_history(self, alert_id: str) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT at_utc,actor,action FROM alert_history WHERE alert_id=? ORDER BY id",
                (alert_id,),
            )]

    def events_after(self, event_id: int, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            return [{"id": row["id"], "kind": row["kind"],
                     "at_utc": row["at_utc"], "payload": json.loads(row["payload_json"])}
                    for row in connection.execute(
                        "SELECT * FROM intelligence_events WHERE id>? ORDER BY id LIMIT ?",
                        (event_id, limit),
                    )]
