"""Immutable, signed snapshots of what a scoped search actually examined."""
from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.storage.database import Database, utc_now


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


class SearchProof:
    def __init__(self, db: Database, key_path: Path):
        self.db, self.key_path = db, Path(key_path)
        self.private_key: Ed25519PrivateKey | None = None

    def migrate(self) -> None:
        with self.db.connection() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS search_proofs (
                id TEXT PRIMARY KEY, pursuit_id TEXT NOT NULL REFERENCES pursuits(id),
                created_utc TEXT NOT NULL, payload_json TEXT NOT NULL,
                signature_hex TEXT NOT NULL, public_key_hex TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                pdf_blob BLOB, pdf_sha256 TEXT, pdf_signature_hex TEXT)""")
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(search_proofs)")}
            for name, kind in (("pdf_blob", "BLOB"), ("pdf_sha256", "TEXT"), ("pdf_signature_hex", "TEXT")):
                if name not in columns:
                    connection.execute(f"ALTER TABLE search_proofs ADD COLUMN {name} {kind}")
            connection.execute("CREATE INDEX IF NOT EXISTS search_proofs_by_pursuit ON search_proofs(pursuit_id,created_utc DESC)")
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if self.key_path.exists():
            key = serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("Search Proof key is not Ed25519")
            self.private_key = key
        else:
            self.private_key = Ed25519PrivateKey.generate()
            pem = self.private_key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption())
            # Fail closed if the key already appeared during a concurrent start.
            try:
                descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                self.private_key = serialization.load_pem_private_key(self.key_path.read_bytes(), None)
            else:
                with os.fdopen(descriptor, "wb") as target:
                    target.write(pem)

    def public_key(self) -> str:
        assert self.private_key is not None
        return self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()

    def create(self, journey: dict, coverage: dict, cameras: list[dict], counters: dict[str, dict],
               source_ids: set[str]) -> dict:
        pursuit = journey["pursuit"]
        eligible, skipped = [], []
        for camera in cameras:
            if pursuit["department_scope"] and camera["department"] != pursuit["department_scope"]:
                continue
            if pursuit["camera_id"] and camera["camera_id"] != pursuit["camera_id"]:
                continue
            camera_id = camera["camera_id"]
            item = {
                "camera_id": camera_id, "department": camera["department"],
                "source_mode": camera["source_mode"], "catalogue_present": bool(camera["catalogue_present"]),
                "health_status": camera["health_status"], "last_frame_utc": camera["last_frame_utc"],
                "source_pts": camera["source_pts"], "pts_timebase": camera["pts_timebase"],
                "stream_generation": camera["stream_generation"],
                "lifetime_counters_at_receipt": counters.get(camera_id, {}),
            }
            if not camera["catalogue_present"]:
                skipped.append({**item, "skip_reason": "absent_from_latest_catalogue"})
            elif camera_id not in source_ids:
                skipped.append({**item, "skip_reason": "no_authorised_capture_source"})
            else:
                eligible.append(item)
        windows = [{key: row.get(key) for key in (
            "schedule_id", "camera_id", "revision", "window_start_utc", "window_end_utc",
            "timebase", "requested_fps", "applied_fps",
            "received_frames", "analyzed_frames", "decode_errors", "planned_frames",
            "result_code", "reason", "health", "observed_sighting_id")}
            for row in coverage.get("windows", [])]
        records = [{key: row.get(key) for key in (
            "id", "camera_id", "source_pts", "pts_timebase", "stream_generation",
            "received_utc", "display_time_utc", "display_time_is_approximate",
            "effective_plate", "effective_status", "review_history", "model_version",
            "evidence_sha256", "evidence_status")}
            for row in journey["records"]]
        payload = {
            "schema": "sakhyapath.search-proof.v1", "receipt_id": uuid.uuid4().hex,
            "created_utc": utc_now(), "pursuit_id": pursuit["id"],
            "query": {key: pursuit[key] for key in ("target_plate", "from_utc", "to_utc", "camera_id", "review_status", "department_scope")},
            "eligible_cameras": eligible, "skipped_cameras": skipped,
            "coverage_windows": windows,
            "matching_records": records, "alerts": journey["alerts"],
            "journey_gaps": journey["gaps"],
            "scope_warning": "A zero-result search means no matching read in analyzed frames only. It does not establish absence from unsampled video, unavailable feeds, or the road.",
            "counter_warning": "Camera counters are lifetime snapshots; coverage-window deltas measure the search sampling period.",
            "clock_warning": "Source PTS is per stream; cross-camera UTC is approximate unless attested mappings exist.",
        }
        raw = canonical(payload)
        assert self.private_key is not None
        envelope = {"payload": payload, "payload_sha256": hashlib.sha256(raw).hexdigest(),
                    "signature_algorithm": "Ed25519", "signature_hex": self.private_key.sign(raw).hex(),
                    "public_key_hex": self.public_key()}
        pdf = self.pdf(envelope)
        envelope["pdf_sha256"] = hashlib.sha256(pdf).hexdigest()
        envelope["pdf_signature_hex"] = self.private_key.sign(pdf).hex()
        with self.db.connection() as connection:
            connection.execute("INSERT INTO search_proofs VALUES(?,?,?,?,?,?,?,?,?,?)",
                               (payload["receipt_id"], pursuit["id"], payload["created_utc"],
                                raw.decode(), envelope["signature_hex"], envelope["public_key_hex"],
                                envelope["payload_sha256"], pdf,
                                envelope["pdf_sha256"], envelope["pdf_signature_hex"]))
        return envelope

    def get(self, proof_id: str) -> dict | None:
        with self.db.connection() as connection:
            row = connection.execute("SELECT * FROM search_proofs WHERE id=?", (proof_id,)).fetchone()
        if not row:
            return None
        return {"payload": json.loads(row["payload_json"]), "payload_sha256": row["payload_sha256"],
                "signature_algorithm": "Ed25519", "signature_hex": row["signature_hex"],
                "public_key_hex": row["public_key_hex"], "pdf_sha256": row["pdf_sha256"],
                "pdf_signature_hex": row["pdf_signature_hex"]}

    def pdf_bytes(self, proof_id: str) -> bytes:
        with self.db.connection() as connection:
            row = connection.execute("SELECT pdf_blob FROM search_proofs WHERE id=?", (proof_id,)).fetchone()
        if not row or not row["pdf_blob"]:
            raise KeyError(proof_id)
        return row["pdf_blob"]

    def list(self, pursuit_id: str) -> list[dict]:
        with self.db.connection() as connection:
            rows = connection.execute("SELECT id,created_utc,payload_sha256 FROM search_proofs WHERE pursuit_id=? ORDER BY created_utc DESC", (pursuit_id,)).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def verify(envelope: dict) -> bool:
        try:
            raw = canonical(envelope["payload"])
            if hashlib.sha256(raw).hexdigest() != envelope["payload_sha256"]:
                return False
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(envelope["public_key_hex"])).verify(
                bytes.fromhex(envelope["signature_hex"]), raw)
            return True
        except Exception:
            return False

    @staticmethod
    def verify_pdf(pdf: bytes, envelope: dict) -> bool:
        try:
            if hashlib.sha256(pdf).hexdigest() != envelope["pdf_sha256"]:
                return False
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(envelope["public_key_hex"])).verify(
                bytes.fromhex(envelope["pdf_signature_hex"]), pdf)
            return True
        except Exception:
            return False

    @staticmethod
    def pdf(envelope: dict) -> bytes:
        payload = envelope["payload"]
        stream = io.BytesIO()
        page = canvas.Canvas(stream, pagesize=A4)
        y = 800
        lines = ["SAKHYAPATH / SEARCH PROOF", f"Receipt: {payload['receipt_id']}",
                 f"Created UTC: {payload['created_utc']}",
                 f"Plate searched: {payload['query']['target_plate']}",
                 f"Eligible cameras: {len(payload['eligible_cameras'])}",
                 f"Skipped cameras: {len(payload['skipped_cameras'])}",
                 f"Coverage windows: {len(payload['coverage_windows'])}",
                 f"Matching records: {len(payload['matching_records'])}",
                 f"Alerts: {len(payload['alerts'])}",
                 "Coverage is limited to analyzed frames. No road absence is claimed.",
                 "Verify the accompanying JSON with scripts/verify_search_proof.py.",
                 f"SHA-256: {envelope['payload_sha256']}",
                 f"Ed25519 key: {envelope['public_key_hex']}"]
        signature = envelope["signature_hex"]
        lines.extend(["JSON signature (hex):", signature[:64], signature[64:]])
        for line in lines:
            page.setFont("Helvetica", 9)
            page.drawString(40, y, line[:105])
            y -= 23
        page.showPage()
        page.setFont("Helvetica-Bold", 10)
        page.drawString(40, 810, "SIGNED PAYLOAD / COMPLETE JSON FIELD RECORD")
        y = 790
        for line in json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True).splitlines():
            chunks = [line[start:start + 110] for start in range(0, max(len(line), 1), 110)]
            for chunk in chunks:
                if y < 35:
                    page.showPage()
                    y = 810
                page.setFont("Courier", 6)
                page.drawString(35, y, chunk)
                y -= 8
        page.save()
        return stream.getvalue()
