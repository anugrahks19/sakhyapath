from __future__ import annotations

import hashlib
import math
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.storage.database import Database, utc_now
from app.storage.intelligence import IntelligenceStore, normalize_plate


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _distance_km(first: dict, second: dict) -> float:
    lat1, lon1 = math.radians(first["latitude"]), math.radians(first["longitude"])
    lat2, lon2 = math.radians(second["latitude"]), math.radians(second["longitude"])
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    arc = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(arc), math.sqrt(max(0, 1 - arc)))


class JourneyStore:
    """Historical search and evidence journey; never fabricates a shared clock."""

    def __init__(self, db: Database, intelligence: IntelligenceStore):
        self.db = db
        self.intelligence = intelligence

    def migrate(self) -> None:
        with self.db.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS pursuits (
                    id TEXT PRIMARY KEY,
                    target_plate TEXT NOT NULL,
                    from_utc TEXT,
                    to_utc TEXT,
                    camera_id TEXT,
                    review_status TEXT,
                    max_speed_kmh REAL NOT NULL,
                    department_scope TEXT,
                    created_by TEXT NOT NULL,
                    created_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS pursuits_newest ON pursuits(created_utc DESC);
                CREATE TABLE IF NOT EXISTS sighting_reviews (
                    sighting_id TEXT PRIMARY KEY REFERENCES sightings(id),
                    decision TEXT NOT NULL CHECK(decision IN ('confirmed','rejected')),
                    corrected_plate TEXT,
                    note TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reviewed_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sighting_review_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sighting_id TEXT NOT NULL REFERENCES sightings(id),
                    decision TEXT NOT NULL,
                    corrected_plate TEXT,
                    note TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reviewed_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS time_mappings (
                    camera_id TEXT NOT NULL REFERENCES cameras(camera_id),
                    stream_generation INTEGER NOT NULL,
                    pts_anchor REAL NOT NULL,
                    utc_anchor TEXT NOT NULL,
                    uncertainty_ms REAL NOT NULL,
                    basis TEXT NOT NULL,
                    evidence_note TEXT NOT NULL,
                    created_utc TEXT NOT NULL,
                    PRIMARY KEY(camera_id, stream_generation)
                );
            """)
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(3)")

    def add_time_mapping(self, camera_id: str, stream_generation: int, pts_anchor: float,
                         utc_anchor: str, uncertainty_ms: float, basis: str,
                         evidence_note: str) -> dict[str, Any]:
        camera = self.db.camera(camera_id)
        if not camera:
            raise KeyError(camera_id)
        if camera["source_system"] != "owned":
            raise ValueError("Manual clock mapping is available only for owned sources")
        if basis != "owned_recording_clock_attested":
            raise ValueError("Clock basis is not supported")
        parsed = _utc(utc_anchor)
        item = {"camera_id": camera_id, "stream_generation": stream_generation,
                "pts_anchor": pts_anchor, "utc_anchor": parsed.isoformat(),
                "uncertainty_ms": uncertainty_ms, "basis": basis,
                "evidence_note": evidence_note, "created_utc": utc_now()}
        with self.db.connection() as connection:
            connection.execute(
                """INSERT INTO time_mappings(camera_id,stream_generation,pts_anchor,
                   utc_anchor,uncertainty_ms,basis,evidence_note,created_utc)
                   VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(camera_id,stream_generation)
                   DO UPDATE SET pts_anchor=excluded.pts_anchor,utc_anchor=excluded.utc_anchor,
                   uncertainty_ms=excluded.uncertainty_ms,basis=excluded.basis,
                   evidence_note=excluded.evidence_note,created_utc=excluded.created_utc""",
                tuple(item.values()),
            )
        return item

    def create(self, plate: str, *, from_utc: str | None, to_utc: str | None,
               camera_id: str | None, review_status: str | None,
               max_speed_kmh: float, department: str | None, actor: str) -> dict[str, Any]:
        target = normalize_plate(plate)
        if not 4 <= len(target) <= 16:
            raise ValueError("Plate must have 4-16 alphanumeric characters")
        if from_utc and to_utc and _utc(from_utc) > _utc(to_utc):
            raise ValueError("from_utc must be before to_utc")
        if camera_id:
            camera = self.db.camera(camera_id)
            if not camera or (department and camera["department"] != department):
                raise KeyError(camera_id)
        item = {"id": uuid.uuid4().hex, "target_plate": target,
                "from_utc": from_utc, "to_utc": to_utc, "camera_id": camera_id,
                "review_status": review_status, "max_speed_kmh": max_speed_kmh,
                "department_scope": department, "created_by": actor,
                "created_utc": utc_now()}
        with self.db.connection() as connection:
            connection.execute(
                """INSERT INTO pursuits(id,target_plate,from_utc,to_utc,camera_id,
                   review_status,max_speed_kmh,department_scope,created_by,created_utc)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""", tuple(item.values()),
            )
        return item

    def pursuit(self, pursuit_id: str, department: str | None) -> dict[str, Any] | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM pursuits WHERE id=?", (pursuit_id,)).fetchone()
        if not row or (department is not None and row["department_scope"] != department):
            return None
        return dict(row)

    def pursuits(self, department: str | None, limit: int = 30) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            if department is None:
                rows = connection.execute(
                    "SELECT * FROM pursuits ORDER BY created_utc DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM pursuits WHERE department_scope=? ORDER BY created_utc DESC LIMIT ?",
                    (department, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def review(self, sighting_id: str, decision: str, corrected_plate: str | None,
               note: str, department: str | None, actor: str) -> dict[str, Any]:
        if decision not in {"confirmed", "rejected"}:
            raise ValueError("Decision must be confirmed or rejected")
        corrected = normalize_plate(corrected_plate) if corrected_plate else None
        if corrected and not 4 <= len(corrected) <= 16:
            raise ValueError("Corrected plate must have 4-16 alphanumeric characters")
        if decision == "rejected" and corrected:
            raise ValueError("A rejected sighting cannot have a corrected plate")
        with self.db.connection() as connection:
            row = connection.execute(
                """SELECT s.id,c.department FROM sightings s JOIN cameras c USING(camera_id)
                   WHERE s.id=?""", (sighting_id,),
            ).fetchone()
            if not row or (department is not None and row["department"] != department):
                raise KeyError(sighting_id)
            now = utc_now()
            values = (sighting_id, decision, corrected, note, actor, now)
            connection.execute(
                """INSERT INTO sighting_reviews(sighting_id,decision,corrected_plate,note,
                   actor,reviewed_utc) VALUES(?,?,?,?,?,?) ON CONFLICT(sighting_id)
                   DO UPDATE SET decision=excluded.decision,corrected_plate=excluded.corrected_plate,
                   note=excluded.note,actor=excluded.actor,reviewed_utc=excluded.reviewed_utc""",
                values,
            )
            connection.execute(
                """INSERT INTO sighting_review_history(sighting_id,decision,corrected_plate,
                   note,actor,reviewed_utc) VALUES(?,?,?,?,?,?)""", values,
            )
        return {"sighting_id": sighting_id, "decision": decision,
                "corrected_plate": corrected, "note": note, "actor": actor,
                "reviewed_utc": now}

    def review_history(self, sighting_id: str, department: str | None) -> list[dict[str, Any]]:
        with self.db.connection() as connection:
            permitted = connection.execute(
                """SELECT c.department FROM sightings s JOIN cameras c USING(camera_id)
                   WHERE s.id=?""", (sighting_id,),
            ).fetchone()
            if not permitted or (department is not None and permitted["department"] != department):
                raise KeyError(sighting_id)
            rows = connection.execute(
                "SELECT * FROM sighting_review_history WHERE sighting_id=? ORDER BY id",
                (sighting_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _evidence_status(self, item: dict) -> str:
        path = Path(item["evidence_path"])
        if not path.resolve().is_relative_to(self.intelligence.evidence_dir.resolve()):
            return "invalid_reference"
        try:
            data = path.read_bytes()
        except OSError:
            return "missing"
        return ("verified" if hashlib.sha256(data).hexdigest() == item["evidence_sha256"]
                else "hash_mismatch")

    def search(self, *, plate: str | None = None, from_utc: str | None = None,
               to_utc: str | None = None, camera_id: str | None = None,
               review_status: str | None = None, department: str | None = None,
               limit: int = 500) -> list[dict[str, Any]]:
        clauses, values = [], []
        if plate:
            target = normalize_plate(plate)
            clauses.append("(s.plate_normalized=? OR (r.decision='confirmed' AND r.corrected_plate=?))")
            values += [target, target]
        if camera_id:
            clauses.append("s.camera_id=?")
            values.append(camera_id)
        if department is not None:
            clauses.append("c.department=?")
            values.append(department)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            """SELECT s.*,c.display_name,c.department,c.latitude,c.longitude,
               c.source_type,c.source_system,r.decision AS reviewer_decision,
               r.corrected_plate,r.note AS review_note,r.actor AS review_actor,
               r.reviewed_utc,m.pts_anchor,m.utc_anchor,m.uncertainty_ms,
               m.basis AS mapping_basis FROM sightings s
               JOIN cameras c ON c.camera_id=s.camera_id
               LEFT JOIN sighting_reviews r ON r.sighting_id=s.id
               LEFT JOIN time_mappings m ON m.camera_id=s.camera_id
                    AND m.stream_generation=s.stream_generation"""
            + where + " ORDER BY s.received_utc DESC,s.id DESC LIMIT 5000"
        )
        with self.db.connection() as connection:
            rows = connection.execute(sql, values).fetchall()
        result = []
        for row in rows:
            raw = dict(row)
            item = self.intelligence._public_sighting(raw)
            item.pop("pts_anchor", None)
            item.pop("utc_anchor", None)
            item["effective_plate"] = (
                raw["corrected_plate"] if raw["reviewer_decision"] == "confirmed"
                and raw["corrected_plate"] else raw["plate_normalized"]
            )
            item["effective_status"] = (
                "rejected" if raw["reviewer_decision"] == "rejected" else
                "reviewed_confirmed" if raw["reviewer_decision"] == "confirmed" else
                raw["review_status"]
            )
            if raw["source_pts"] is not None and raw["utc_anchor"] is not None:
                event_time = _utc(raw["utc_anchor"]) + timedelta(
                    seconds=raw["source_pts"] - raw["pts_anchor"]
                )
                item["event_utc_if_verified"] = event_time.isoformat()
                item["timestamp_provenance"] = raw["mapping_basis"]
                item["timestamp_uncertainty"] = f"+/- {raw['uncertainty_ms']} ms attested mapping"
                item["mapping_basis"] = raw["mapping_basis"]
            else:
                item["mapping_basis"] = None
            item["display_time_utc"] = item["event_utc_if_verified"] or raw["received_utc"]
            item["display_time_is_approximate"] = item["event_utc_if_verified"] is None
            item["evidence_status"] = self._evidence_status(raw)
            item["evidence_supported"] = item["evidence_status"] == "verified"
            if review_status and item["effective_status"] != review_status:
                continue
            display_time = _utc(item["display_time_utc"])
            if from_utc and display_time < _utc(from_utc):
                continue
            if to_utc and display_time > _utc(to_utc):
                continue
            result.append(item)
            if len(result) >= limit:
                break
        return result

    def journey(self, pursuit_id: str, department: str | None) -> dict[str, Any] | None:
        pursuit = self.pursuit(pursuit_id, department)
        if pursuit is None:
            return None
        records = self.search(
            plate=pursuit["target_plate"], from_utc=pursuit["from_utc"],
            to_utc=pursuit["to_utc"], camera_id=pursuit["camera_id"],
            review_status=pursuit["review_status"],
            department=pursuit["department_scope"], limit=500,
        )
        records.sort(key=lambda item: (item["display_time_utc"], item["id"]))
        alerts: list[dict[str, Any]] = []
        if records:
            sighting_ids = [item["id"] for item in records]
            placeholders = ",".join("?" for _ in sighting_ids)
            with self.db.connection() as connection:
                alerts = [dict(row) for row in connection.execute(
                    f"""SELECT a.id,a.sighting_id,a.status,a.match_basis,a.created_utc,
                       a.acknowledged_utc,a.acknowledged_by,w.category,w.source_label
                       FROM alerts a JOIN watchlist w ON w.id=a.watchlist_id
                       WHERE a.sighting_id IN ({placeholders}) ORDER BY a.created_utc""",
                    sighting_ids,
                )]
                history_rows = connection.execute(
                    f"""SELECT sighting_id,decision,corrected_plate,note,actor,reviewed_utc
                       FROM sighting_review_history WHERE sighting_id IN ({placeholders})
                       ORDER BY id""", sighting_ids,
                ).fetchall()
            history: dict[str, list[dict]] = {}
            for row in history_rows:
                history.setdefault(row["sighting_id"], []).append(dict(row))
            for item in records:
                item["review_history"] = history.get(item["id"], [])
        observations = [item for item in records if item["effective_status"] in
                        {"confirmed", "reviewed_confirmed"} and item["evidence_supported"]]
        links: list[dict[str, Any]] = []
        for first, second in zip(observations, observations[1:]):
            if first["camera_id"] == second["camera_id"]:
                continue
            distance = _distance_km(first, second)
            verified_pair = bool(first["event_utc_if_verified"] and second["event_utc_if_verified"])
            duration_seconds = (_utc(second["event_utc_if_verified"]) -
                                _utc(first["event_utc_if_verified"])).total_seconds() if verified_pair else None
            uncertainty_seconds = ((first["uncertainty_ms"] + second["uncertainty_ms"]) / 1000
                                   if verified_pair else None)
            # Use the longest travel time allowed by both clock-error bounds.
            # A jump is implausible only if even this favourable bound is too fast.
            favourable_duration = ((duration_seconds + uncertainty_seconds)
                                   if verified_pair else None)
            speed = (distance / (favourable_duration / 3600)
                     if favourable_duration is not None and favourable_duration > 0 else None)
            status = ("implausible" if verified_pair and
                      (favourable_duration is None or favourable_duration <= 0 or
                       speed is not None and speed > pursuit["max_speed_kmh"])
                      else "possible_inferred" if verified_pair else "time_unaligned")
            links.append({"from_sighting_id": first["id"], "to_sighting_id": second["id"],
                          "from_camera_id": first["camera_id"],
                          "to_camera_id": second["camera_id"],
                          "distance_km_straight_line": round(distance, 2),
                          "verified_duration_seconds": duration_seconds,
                          "duration_uncertainty_seconds": uncertainty_seconds,
                          "minimum_required_speed_kmh": round(speed, 1) if speed is not None else None,
                          "status": status, "line_style": "dashed",
                          "meaning": "candidate connection, not a road route"})
        gaps = []
        if not observations:
            gaps.append("No supported confirmed observation")
        if any(item["display_time_is_approximate"] for item in records):
            gaps.append("Cross-camera clock alignment unverified for at least one sighting")
        if any(not item["evidence_supported"] for item in records):
            gaps.append("At least one evidence crop is missing or failed SHA-256 verification")
        if any(item["effective_status"] == "candidate" for item in records):
            gaps.append("Candidate readings need human review")
        return {"pursuit": pursuit, "time_contract": {
                    "order": "verified UTC where attested; otherwise receive time is approximate",
                    "source_pts": "per-stream media time, not common UTC",
                    "links": "dashed inferences, not actual road routes",
                }, "records": records, "observations": observations, "links": links,
                "alerts": alerts,
                "gaps": gaps, "latest_confirmed": observations[-1] if observations else None,
                "counts": {"records": len(records), "observations": len(observations),
                           "candidates": sum(item["effective_status"] == "candidate" for item in records),
                           "rejected": sum(item["effective_status"] == "rejected" for item in records)}}
