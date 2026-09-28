"""Operator-owned incident workflow. Handoffs are internal inbox records, not dispatch messages."""
from __future__ import annotations

import hashlib
import math
import uuid
from datetime import datetime, timezone

from app.services.journey import JourneyStore
from app.services.proof import SearchProof, canonical
from app.storage.database import Database, utc_now
from app.storage.intelligence import normalize_plate


def distance_km(a: float, b: float, c: float, d: float) -> float:
    lat1, lat2 = math.radians(a), math.radians(c)
    delta_lat, delta_lon = lat2 - lat1, math.radians(d - b)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


class CaseBridge:
    def __init__(self, db: Database, journeys: JourneyStore, proofs: SearchProof):
        self.db, self.journeys, self.proofs = db, journeys, proofs

    def migrate(self) -> None:
        with self.db.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS police_cases (
                    id TEXT PRIMARY KEY, reference TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL, priority TEXT NOT NULL, plate_query TEXT NOT NULL,
                    query_mode TEXT NOT NULL,
                    vehicle_description TEXT NOT NULL, incident_latitude REAL NOT NULL,
                    incident_longitude REAL NOT NULL, incident_utc TEXT NOT NULL,
                    search_until_utc TEXT,
                    lead_department TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                    pursuit_id TEXT REFERENCES pursuits(id), created_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS police_cases_open ON police_cases(status,updated_utc DESC);
                CREATE TABLE IF NOT EXISTS case_handoffs (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES police_cases(id),
                    recipient_department TEXT NOT NULL, sighting_id TEXT NOT NULL REFERENCES sightings(id),
                    packet_json TEXT NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    created_utc TEXT NOT NULL, acknowledged_utc TEXT, acknowledged_by TEXT,
                    acknowledgement_note TEXT
                );
                CREATE INDEX IF NOT EXISTS case_handoffs_inbox ON case_handoffs(recipient_department,status,created_utc DESC);
                CREATE TABLE IF NOT EXISTS case_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL REFERENCES police_cases(id),
                    at_utc TEXT NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS case_events_case ON case_events(case_id,id);
                CREATE TABLE IF NOT EXISTS case_timeline_snapshots (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES police_cases(id),
                    created_utc TEXT NOT NULL, payload_json TEXT NOT NULL, signature_hex TEXT NOT NULL,
                    public_key_hex TEXT NOT NULL, payload_sha256 TEXT NOT NULL
                );
            """)

    @staticmethod
    def _event(connection, case_id: str, actor: str, kind: str, detail: str) -> None:
        connection.execute(
            "INSERT INTO case_events(case_id,at_utc,actor,kind,detail) VALUES(?,?,?,?,?)",
            (case_id, utc_now(), actor, kind, detail),
        )

    def create(self, body: dict, actor: str) -> dict:
        plate = normalize_plate(body["plate_query"])
        if not 3 <= len(plate) <= 16:
            raise ValueError("Plate query must have 3-16 ASCII alphanumeric characters")
        if body["query_mode"] == "exact" and len(plate) < 4:
            raise ValueError("Exact plate must have at least four characters")
        if not body["reference"].strip():
            raise ValueError("Case reference is required")
        now, case_id = utc_now(), uuid.uuid4().hex
        item = {"id": case_id, "reference": body["reference"].strip(),
                "kind": body["kind"], "priority": body["priority"], "plate_query": plate,
                "query_mode": body["query_mode"],
                "vehicle_description": body["vehicle_description"],
                "incident_latitude": body["incident_latitude"],
                "incident_longitude": body["incident_longitude"],
                "incident_utc": body["incident_utc"].astimezone(timezone.utc).isoformat(),
                "search_until_utc": body["search_until_utc"].astimezone(timezone.utc).isoformat()
                if body["search_until_utc"] else None,
                "lead_department": body["lead_department"], "status": "open",
                "pursuit_id": None, "created_utc": now, "updated_utc": now}
        with self.db.connection() as connection:
            connection.execute("""INSERT INTO police_cases VALUES(
                :id,:reference,:kind,:priority,:plate_query,:query_mode,:vehicle_description,
                :incident_latitude,:incident_longitude,:incident_utc,:search_until_utc,:lead_department,
                :status,:pursuit_id,:created_utc,:updated_utc)""", item)
            self._event(connection, case_id, actor, "case_opened", "Case opened for evidence triage")
        return item

    def get(self, case_id: str) -> dict | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM police_cases WHERE id=?", (case_id,)).fetchone()
        return dict(row) if row else None

    def list(self, status: str | None = None) -> list[dict]:
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM police_cases WHERE (? IS NULL OR status=?) ORDER BY updated_utc DESC LIMIT 100",
                (status, status),
            ).fetchall()
        return [dict(row) for row in rows]

    def evidence(self, case: dict) -> dict:
        # Existing search enforces evidence-hash checks and reviewer state. A partial
        # plate is a triage query, never automatic proof of target identity.
        records = self.journeys.search(
            plate=case["plate_query"] if case["query_mode"] == "exact" else None,
            from_utc=case["incident_utc"], to_utc=case["search_until_utc"],
            department=None, limit=5000)
        matches = [row for row in records if row["effective_status"] != "rejected" and
                   (row["effective_plate"] == case["plate_query"] if case["query_mode"] == "exact"
                    else case["plate_query"] in row["effective_plate"])]
        matches.sort(key=lambda row: (row["display_time_utc"], row["id"]))
        confirmed = [row for row in matches if row["effective_status"] in
                     {"confirmed", "reviewed_confirmed"} and row["evidence_supported"]]
        candidates = [row for row in matches if row not in confirmed]
        return {"confirmed": confirmed[-100:], "candidates": candidates[-100:],
                "partial_query": case["query_mode"] == "partial",
                "truncated_to_recent_search_window": len(records) == 5000,
                "warning": "Partial matches and candidate reads require officer review; receive-time order can be approximate."}

    def camera_plan(self, case: dict) -> dict:
        cameras = [camera for camera in self.db.cameras() if camera["catalogue_present"]]
        rows = []
        for camera in cameras:
            row = {"camera_id": camera["camera_id"], "name": camera["display_name"],
                   "department": camera["department"], "health": camera["health_status"],
                   "last_frame_utc": camera["last_frame_utc"],
                   "distance_km": round(distance_km(case["incident_latitude"], case["incident_longitude"],
                                                    camera["latitude"], camera["longitude"]), 2)}
            rows.append(row)
        rows.sort(key=lambda row: (row["distance_km"], row["camera_id"]))
        nearby = rows[:12]
        gaps = [row for row in nearby if row["health"] != "online"]
        working = [row for row in rows if row["health"] == "online"][:8]
        return {"nearby": nearby, "unavailable_or_unverified": gaps,
                "working_alternatives": working,
                "basis": "Geographic proximity and decoded-frame health only; direction, field of view and road reachability are unverified."}

    def handoffs(self, case_id: str) -> list[dict]:
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM case_handoffs WHERE case_id=? ORDER BY created_utc DESC", (case_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def events(self, case_id: str) -> list[dict]:
        with self.db.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM case_events WHERE case_id=? ORDER BY id", (case_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def detail(self, case_id: str) -> dict | None:
        case = self.get(case_id)
        if not case:
            return None
        evidence = self.evidence(case)
        with self.db.connection() as connection:
            alerts = [dict(row) for row in connection.execute("""
                SELECT a.id,a.status,a.created_utc,s.camera_id,s.plate_normalized
                FROM alerts a JOIN sightings s ON s.id=a.sighting_id
                WHERE s.plate_normalized=? ORDER BY a.created_utc DESC LIMIT 30
            """, (case["plate_query"],))]
            watchlist = [dict(row) for row in connection.execute("""
                SELECT id,category,source_label,active,expires_utc FROM watchlist
                WHERE plate_normalized=? ORDER BY created_utc DESC LIMIT 10
            """, (case["plate_query"],))]
        return {"case": case, "evidence": evidence, "camera_plan": self.camera_plan(case),
                "handoffs": self.handoffs(case_id), "events": self.events(case_id),
                "representative_watchlist": watchlist, "alerts": alerts,
                "integration_warning": "Official eGujCop/VAHAN access and external dispatch are not configured."}

    def create_handoff(self, case: dict, recipient: str, sighting_id: str,
                       note: str, actor: str) -> dict:
        if case["status"] != "open":
            raise ValueError("Closed cases cannot send handoffs")
        if recipient == case["lead_department"]:
            raise ValueError("Handoff recipient must differ from lead department")
        if recipient not in {camera["department"] for camera in self.db.cameras()}:
            raise ValueError("Recipient department has no registered camera")
        source = next((row for row in self.evidence(case)["confirmed"] if row["id"] == sighting_id), None)
        if not source:
            raise ValueError("Handoff requires a matching confirmed, hash-verified sighting")
        suggestions = []
        for camera in self.db.cameras():
            if camera["department"] != recipient or not camera["catalogue_present"]:
                continue
            suggestions.append({"camera_id": camera["camera_id"],
                                "name": camera["display_name"],
                                "health": camera["health_status"],
                                "distance_km": round(distance_km(source["latitude"], source["longitude"],
                                                                 camera["latitude"], camera["longitude"]), 2)})
        suggestions.sort(key=lambda row: (row["health"] != "online", row["distance_km"], row["camera_id"]))
        packet = {"case_reference": case["reference"], "kind": case["kind"],
                  "priority": case["priority"], "plate": source["effective_plate"],
                  "vehicle_description": case["vehicle_description"],
                  "last_confirmed": {"sighting_id": source["id"], "camera_id": source["camera_id"],
                                     "department": source["department"],
                                     "display_time_utc": source["display_time_utc"],
                                     "time_approximate": source["display_time_is_approximate"],
                                     "evidence_sha256": source["evidence_sha256"]},
                  "recipient_department": recipient,
                  "suggested_cameras": suggestions[:3],
                  "suggestion_basis": "Recipient camera health and straight-line distance from the last sighting; road direction and visibility unverified.",
                  "uncertainty": "Investigative lead; source time may be approximate. Confirm independently before field action."}
        import json
        now = utc_now()
        item = {"id": uuid.uuid4().hex, "case_id": case["id"],
                "recipient_department": recipient, "sighting_id": sighting_id,
                "packet_json": json.dumps(packet, sort_keys=True), "note": note,
                "status": "pending", "created_utc": now,
                "acknowledged_utc": None, "acknowledged_by": None, "acknowledgement_note": None}
        with self.db.connection() as connection:
            connection.execute("""INSERT INTO case_handoffs VALUES(
                :id,:case_id,:recipient_department,:sighting_id,:packet_json,:note,:status,
                :created_utc,:acknowledged_utc,:acknowledged_by,:acknowledgement_note)""", item)
            self._event(connection, case["id"], actor, "handoff_sent",
                        f"Internal handoff {item['id']} queued for {recipient}")
            connection.execute("UPDATE police_cases SET updated_utc=? WHERE id=?", (now, case["id"]))
        return {**item, "packet": packet, "packet_json": None}

    def inbox(self, department: str) -> list[dict]:
        import json
        with self.db.connection() as connection:
            rows = connection.execute("""SELECT * FROM case_handoffs
                WHERE recipient_department=? ORDER BY created_utc DESC LIMIT 100""", (department,)).fetchall()
        return [{**dict(row), "packet": json.loads(row["packet_json"]), "packet_json": None}
                for row in rows]

    def acknowledge(self, handoff_id: str, department: str, note: str) -> dict:
        import json
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM case_handoffs WHERE id=? AND recipient_department=?",
                                     (handoff_id, department)).fetchone()
            if not row:
                raise KeyError(handoff_id)
            if row["status"] != "pending":
                raise ValueError("Handoff has already been acknowledged")
            now = utc_now()
            connection.execute("""UPDATE case_handoffs SET status='acknowledged',
                acknowledged_utc=?,acknowledged_by=?,acknowledgement_note=? WHERE id=?""",
                (now, department, note, handoff_id))
            self._event(connection, row["case_id"], department, "handoff_acknowledged",
                        f"Internal handoff {handoff_id} acknowledged: {note}")
            connection.execute("UPDATE police_cases SET updated_utc=? WHERE id=?", (now, row["case_id"]))
        return {"id": handoff_id, "status": "acknowledged", "acknowledged_utc": now,
                "acknowledged_by": department, "packet": json.loads(row["packet_json"])}

    def add_note(self, case: dict, actor: str, note: str) -> dict:
        with self.db.connection() as connection:
            self._event(connection, case["id"], actor, "case_note", note)
            connection.execute("UPDATE police_cases SET updated_utc=? WHERE id=?", (utc_now(), case["id"]))
        return {"recorded": True}

    def set_status(self, case: dict, status: str, actor: str, note: str) -> dict:
        with self.db.connection() as connection:
            connection.execute("UPDATE police_cases SET status=?,updated_utc=? WHERE id=?",
                               (status, utc_now(), case["id"]))
            self._event(connection, case["id"], actor, f"case_{status}", note)
        return self.get(case["id"])

    def attach_pursuit(self, case: dict, sighting_id: str, actor: str) -> dict:
        if case["status"] != "open":
            raise ValueError("Case is closed")
        if case["pursuit_id"]:
            raise ValueError("Case already has an attached pursuit")
        source = next((row for row in self.evidence(case)["confirmed"] if row["id"] == sighting_id), None)
        if not source:
            raise ValueError("A matching confirmed, hash-verified sighting is required")
        pursuit = self.journeys.create(source["effective_plate"], from_utc=case["incident_utc"],
                                       to_utc=None, camera_id=None, review_status=None,
                                       max_speed_kmh=160.0, department=None, actor=actor)
        with self.db.connection() as connection:
            connection.execute("UPDATE police_cases SET pursuit_id=?,updated_utc=? WHERE id=?",
                               (pursuit["id"], utc_now(), case["id"]))
            self._event(connection, case["id"], actor, "pursuit_attached",
                        f"Existing measured pursuit engine linked to {pursuit['id']}")
        return pursuit

    def shift_briefing(self) -> dict:
        rows = []
        for case in self.list("open"):
            confirmed = self.evidence(case)["confirmed"]
            handoffs = self.handoffs(case["id"])
            gaps = self.camera_plan(case)["unavailable_or_unverified"]
            rows.append({"case_id": case["id"], "reference": case["reference"],
                         "kind": case["kind"], "priority": case["priority"],
                         "lead_department": case["lead_department"],
                         "last_confirmed": ({"camera_id": confirmed[-1]["camera_id"],
                                             "time_utc": confirmed[-1]["display_time_utc"],
                                             "time_approximate": confirmed[-1]["display_time_is_approximate"]}
                                            if confirmed else None),
                         "pending_handoffs": sum(row["status"] == "pending" for row in handoffs),
                         "nearby_camera_gaps": len(gaps), "pursuit_id": case["pursuit_id"]})
        return {"generated_utc": utc_now(), "open_cases": rows,
                "warning": "Snapshot for shift review; no dispatch or external database lookup occurred."}

    def signed_timeline(self, case_id: str) -> dict:
        import json
        detail = self.detail(case_id)
        if detail is None:
            raise KeyError(case_id)
        payload = {"snapshot_id": uuid.uuid4().hex, "created_utc": utc_now(),
                   "case": detail["case"], "events": detail["events"],
                   "handoffs": [{key: row[key] for key in ("id", "recipient_department", "sighting_id",
                                   "status", "created_utc", "acknowledged_utc", "acknowledged_by")}
                                for row in detail["handoffs"]],
                   "confirmed_sightings": [{key: row.get(key) for key in
                                           ("id", "camera_id", "effective_plate", "display_time_utc",
                                            "display_time_is_approximate", "evidence_sha256", "model_version")}
                                           for row in detail["evidence"]["confirmed"]],
                   "meaning": "Signed snapshot of current case records; later changes require a new snapshot."}
        data = canonical(payload)
        assert self.proofs.private_key is not None
        result = {"payload": payload, "signature_hex": self.proofs.private_key.sign(data).hex(),
                  "public_key_hex": self.proofs.public_key(), "payload_sha256": hashlib.sha256(data).hexdigest()}
        with self.db.connection() as connection:
            connection.execute("""INSERT INTO case_timeline_snapshots VALUES(?,?,?,?,?,?,?)""",
                               (payload["snapshot_id"], case_id, payload["created_utc"],
                                json.dumps(payload, sort_keys=True), result["signature_hex"],
                                result["public_key_hex"], result["payload_sha256"]))
            self._event(connection, case_id, "operator", "timeline_signed", payload["snapshot_id"])
        return result

    def timeline(self, snapshot_id: str, case_id: str) -> dict | None:
        import json
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM case_timeline_snapshots WHERE id=? AND case_id=?",
                                     (snapshot_id, case_id)).fetchone()
        return {"payload": json.loads(row["payload_json"]), "signature_hex": row["signature_hex"],
                "public_key_hex": row["public_key_hex"], "payload_sha256": row["payload_sha256"]} if row else None
