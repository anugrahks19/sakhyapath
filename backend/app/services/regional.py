"""Isolated regional metadata search and durable, bounded event forwarding."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
from urllib.parse import urlsplit
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx
from fastapi import FastAPI, Header, HTTPException
from contextlib import asynccontextmanager, suppress
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.storage.database import Database, utc_now
from app.storage.intelligence import IntelligenceStore, normalize_plate


class RegionSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plate: str = Field(min_length=4, max_length=16)
    department: str
    limit: int = Field(default=100, ge=1, le=100)


class MetadataEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=8, max_length=80)
    department: str
    kind: str = Field(pattern="^(sighting|feed_gap|feed_restored)$")
    camera_id: str = Field(min_length=1, max_length=100)
    occurred_utc: datetime
    plate: str | None = None
    source_pts: float | None = None
    evidence_sha256: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")

    @field_validator("occurred_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Regional event time requires a timezone")
        return value


class RegionalLedger:
    def __init__(self, db: Database):
        self.db = db

    def migrate(self) -> None:
        with self.db.connection() as connection:
            connection.executescript("""CREATE TABLE IF NOT EXISTS regional_outbox (
                event_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
                created_utc TEXT NOT NULL, delivered_utc TEXT,
                attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT);
                CREATE TABLE IF NOT EXISTS regional_inbox (
                region_id TEXT NOT NULL, event_id TEXT NOT NULL,
                payload_json TEXT NOT NULL, received_utc TEXT NOT NULL,
                PRIMARY KEY(region_id,event_id));
                CREATE TABLE IF NOT EXISTS regional_scan_cursor (
                kind TEXT PRIMARY KEY, last_id INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS regional_camera_state (
                region_id TEXT NOT NULL, camera_id TEXT NOT NULL,
                department TEXT NOT NULL, last_event_kind TEXT NOT NULL,
                last_received_utc TEXT NOT NULL,
                PRIMARY KEY(region_id,camera_id));
                CREATE INDEX IF NOT EXISTS regional_inbox_department_received
                    ON regional_inbox(json_extract(payload_json,'$.department'),received_utc DESC);""")

    def enqueue(self, event: MetadataEvent) -> dict:
        if event.kind == "sighting" and not event.plate:
            raise ValueError("A sighting requires a plate")
        payload = event.model_dump(mode="json")
        if payload["plate"]:
            payload["plate"] = normalize_plate(payload["plate"])
        with self.db.connection() as connection:
            pending = connection.execute("SELECT COUNT(*) FROM regional_outbox WHERE delivered_utc IS NULL").fetchone()[0]
            if pending >= 10000:
                raise ValueError("Regional metadata queue full; operator intervention required")
            connection.execute("INSERT OR IGNORE INTO regional_outbox(event_id,payload_json,created_utc) VALUES(?,?,?)",
                               (event.event_id, json.dumps(payload, sort_keys=True), utc_now()))
        return payload

    def capture_local_changes(self, departments: set[str], batch: int = 200) -> dict:
        """Atomically advance local cursors with queued metadata; no video leaves."""
        counts = {"sighting": 0, "health": 0}
        placeholders = ",".join("?" for _ in departments)
        with self.db.connection() as connection:
            pending = connection.execute("SELECT COUNT(*) FROM regional_outbox WHERE delivered_utc IS NULL").fetchone()[0]
            if pending >= 10000:
                raise ValueError("Regional metadata queue full; scan cursor held")
            for kind, sql in (
                ("sighting", f"""SELECT s.rowid AS seq,s.id,s.camera_id,s.plate_normalized,s.received_utc,
                    s.source_pts,s.evidence_sha256,c.department FROM sightings s JOIN cameras c USING(camera_id)
                    WHERE s.rowid>? AND c.department IN ({placeholders}) ORDER BY s.rowid LIMIT ?"""),
                ("health", f"""SELECT h.id AS seq,h.camera_id,h.at_utc,h.status,c.department
                    FROM camera_health_events h JOIN cameras c USING(camera_id)
                    WHERE h.id>? AND c.department IN ({placeholders}) ORDER BY h.id LIMIT ?"""),
            ):
                cursor = connection.execute("SELECT last_id FROM regional_scan_cursor WHERE kind=?", (kind,)).fetchone()
                last = cursor["last_id"] if cursor else 0
                remaining = max(0, 10000 - pending - sum(counts.values()))
                rows = connection.execute(sql, (last, *sorted(departments), min(batch, remaining))).fetchall()
                for row in rows:
                    item = dict(row)
                    if kind == "health" and item["status"] not in {"offline", "degraded", "online"}:
                        last = item["seq"]
                        continue
                    event = MetadataEvent(
                        event_id=f"{kind}:{item['id'] if kind == 'sighting' else item['seq']}",
                        department=item["department"],
                        kind="sighting" if kind == "sighting" else "feed_restored" if item["status"] == "online" else "feed_gap",
                        camera_id=item["camera_id"],
                        occurred_utc=item["received_utc"] if kind == "sighting" else item["at_utc"],
                        plate=item.get("plate_normalized"), source_pts=item.get("source_pts"),
                        evidence_sha256=item.get("evidence_sha256"))
                    connection.execute("INSERT OR IGNORE INTO regional_outbox(event_id,payload_json,created_utc) VALUES(?,?,?)",
                                       (event.event_id, event.model_dump_json(), utc_now()))
                    last = item["seq"]
                    counts[kind] += 1
                connection.execute("INSERT INTO regional_scan_cursor VALUES(?,?) ON CONFLICT(kind) DO UPDATE SET last_id=excluded.last_id", (kind, last))
        return counts

    def receive(self, region_id: str, event: MetadataEvent) -> dict:
        payload = event.model_dump(mode="json")
        with self.db.connection() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO regional_inbox VALUES(?,?,?,?)",
                (region_id, event.event_id, json.dumps(payload, sort_keys=True), utc_now()))
            if cursor.rowcount and event.kind in {"feed_gap", "feed_restored"}:
                connection.execute("""INSERT INTO regional_camera_state VALUES(?,?,?,?,?)
                    ON CONFLICT(region_id,camera_id) DO UPDATE SET
                    department=excluded.department,last_event_kind=excluded.last_event_kind,
                    last_received_utc=excluded.last_received_utc""",
                    (region_id, event.camera_id, event.department, event.kind, utc_now()))
        return {"accepted": True, "duplicate": cursor.rowcount == 0, "event_id": event.event_id}

    def status(self) -> dict:
        with self.db.connection() as connection:
            pending = connection.execute("SELECT COUNT(*) FROM regional_outbox WHERE delivered_utc IS NULL").fetchone()[0]
            delivered = connection.execute("SELECT COUNT(*) FROM regional_outbox WHERE delivered_utc IS NOT NULL").fetchone()[0]
            inbox = connection.execute("SELECT COUNT(*) FROM regional_inbox").fetchone()[0]
            oldest = connection.execute("SELECT MIN(created_utc) FROM regional_outbox WHERE delivered_utc IS NULL").fetchone()[0]
        return {"pending_metadata": pending, "delivered_metadata": delivered,
                "received_metadata": inbox, "oldest_pending_utc": oldest,
                "gap_state": "metadata_delivery_delayed" if pending else "no_pending_metadata",
                "warning": "A clear outbox is not proof of continuous video coverage."}

    def inbox_events(self, department: str | None, limit: int = 100) -> list[dict]:
        with self.db.connection() as connection:
            if department is None:
                rows = connection.execute("SELECT region_id,event_id,payload_json,received_utc FROM regional_inbox ORDER BY received_utc DESC LIMIT ?", (min(max(limit, 1), 500),)).fetchall()
            else:
                rows = connection.execute("SELECT region_id,event_id,payload_json,received_utc FROM regional_inbox WHERE json_extract(payload_json,'$.department')=? ORDER BY received_utc DESC LIMIT ?", (department, min(max(limit, 1), 500))).fetchall()
        events = [{"region_id": row["region_id"], "event_id": row["event_id"],
                   "received_utc": row["received_utc"], **json.loads(row["payload_json"])} for row in rows]
        return events

    def open_delivered_gaps(self, department: str | None) -> list[dict]:
        with self.db.connection() as connection:
            if department is None:
                rows = connection.execute("SELECT region_id,camera_id,last_received_utc FROM regional_camera_state WHERE last_event_kind='feed_gap' ORDER BY last_received_utc DESC").fetchall()
            else:
                rows = connection.execute("SELECT region_id,camera_id,last_received_utc FROM regional_camera_state WHERE department=? AND last_event_kind='feed_gap' ORDER BY last_received_utc DESC", (department,)).fetchall()
        return [dict(row) for row in rows]

    def flush(self, sender: Callable[[dict], bool], limit: int = 100) -> dict:
        with self.db.connection() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT event_id,payload_json,attempts FROM regional_outbox WHERE delivered_utc IS NULL ORDER BY created_utc,event_id LIMIT ?",
                (min(max(limit, 1), 1000),))]
        sent = 0
        for row in rows:
            try:
                if not sender(json.loads(row["payload_json"])):
                    raise RuntimeError("Central acknowledgement missing")
            except Exception as error:
                with self.db.connection() as connection:
                    connection.execute("UPDATE regional_outbox SET attempts=attempts+1,last_error=? WHERE event_id=?",
                                       (type(error).__name__, row["event_id"]))
                break  # Preserve event order and avoid a tight retry loop.
            with self.db.connection() as connection:
                connection.execute("UPDATE regional_outbox SET delivered_utc=?,attempts=attempts+1,last_error=NULL WHERE event_id=?",
                                   (utc_now(), row["event_id"]))
            sent += 1
        return {"delivered_now": sent, **self.status()}


class RegionalCoordinator:
    def __init__(self, regions: list[dict], transport: httpx.AsyncBaseTransport | None = None):
        if len({row.get("id") for row in regions}) != len(regions):
            raise ValueError("Duplicate regional ID")
        for row in regions:
            parsed = urlsplit(row["url"])
            if (parsed.scheme != "https" and not (parsed.scheme == "http" and
                (parsed.hostname in {"127.0.0.1", "localhost"} or transport is not None))):
                raise ValueError("Regional agents require HTTPS except local testing")
            if parsed.username or parsed.password or parsed.query or parsed.fragment or len(row["token"]) < 16:
                raise ValueError("Invalid regional URL or token")
            if not row.get("departments"):
                raise ValueError("Regional department scope required")
        self.regions = regions
        self.transport = transport

    async def search(self, plate: str, department: str | None) -> dict:
        target = normalize_plate(plate)
        if not 4 <= len(target) <= 16:
            raise ValueError("Plate must have 4-16 alphanumeric characters")
        results, errors = [], []
        requests = [(region, scope) for region in self.regions for scope in region["departments"]
                    if department is None or scope == department]
        if not requests:
            return {"plate": target, "department_scope": department, "hits": [],
                    "regions_queried": 0,
                    "errors": [{"error": "no_regions_configured_for_scope"}],
                    "complete": False,
                    "meaning": "No permitted regional agent was queried; no absence conclusion is supported."}
        limit = asyncio.Semaphore(8)
        async with httpx.AsyncClient(timeout=5.0, transport=self.transport) as client:
            async def one(region: dict, scope: str) -> tuple[list[dict], dict | None]:
                async with limit:
                    try:
                        response = await client.post(
                            region["url"].rstrip("/") + "/v1/search",
                            json={"plate": target, "department": scope, "limit": 100},
                            headers={"X-Region-Token": region["token"]})
                        response.raise_for_status()
                        data = response.json()
                        if data.get("department") != scope or data.get("region_id") != region["id"]:
                            raise ValueError("Regional identity or scope mismatch")
                        if not isinstance(data.get("hits"), list):
                            raise ValueError("Regional hits malformed")
                        if len(data["hits"]) > 100:
                            raise ValueError("Regional result exceeded requested limit")
                        allowed = ("id", "camera_id", "plate_normalized", "received_utc",
                                   "source_pts", "stream_generation", "review_status", "evidence_sha256")
                        hits = []
                        for hit in data["hits"]:
                            if not isinstance(hit, dict) or hit.get("department") != scope or hit.get("plate_normalized") != target:
                                raise ValueError("Regional hit outside requested scope")
                            hits.append({"region_id": region["id"], "department": scope,
                                         **{key: hit.get(key) for key in allowed}})
                        return hits, None
                    except (httpx.HTTPError, ValueError, KeyError) as error:
                        return [], {"region_id": region["id"], "department": scope,
                                    "error": type(error).__name__}
            for hits, error in await asyncio.gather(*(one(region, scope) for region, scope in requests)):
                results.extend(hits)
                if error:
                    errors.append(error)
        results.sort(key=lambda row: (row.get("received_utc", ""), row.get("region_id", ""), row.get("camera_id", "")), reverse=True)
        return {"plate": target, "department_scope": department, "hits": results,
                "regions_queried": len({r["id"] for r in self.regions if department is None or department in r["departments"]}),
                "errors": errors, "complete": not errors,
                "meaning": "Only permitted hit metadata returned; video and crop bytes remain regional."}


def create_regional_app(db_path: Path, region_id: str, departments: set[str], token: str,
                        central_url: str | None = None, central_token: str | None = None) -> FastAPI:
    if len(token) < 16 or not departments:
        raise ValueError("Regional token and department scope required")
    db = Database(db_path)
    db.migrate()
    IntelligenceStore(db, db.path.parent / "evidence").migrate()
    ledger = RegionalLedger(db)
    ledger.migrate()
    if central_url and not central_token:
        raise ValueError("Central event token required")

    def send_event(payload: dict) -> bool:
        if not central_url:
            return False
        response = httpx.post(central_url.rstrip("/") + f"/api/v1/regions/{region_id}/events",
                              json=payload, headers={"X-Region-Token": central_token or ""}, timeout=5)
        response.raise_for_status()
        return bool(response.json().get("accepted"))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async def pump() -> None:
            while True:
                try:
                    await asyncio.to_thread(ledger.capture_local_changes, departments)
                    if central_url:
                        await asyncio.to_thread(ledger.flush, send_event)
                except Exception as error:
                    # Durable outbox and status expose delay. Retry after bounded pause.
                    logging.getLogger(__name__).warning("Regional pump delayed: %s", type(error).__name__)
                await asyncio.sleep(5)
        task = asyncio.create_task(pump())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title=f"SakhyaPath Regional Agent {region_id}", lifespan=lifespan)
    app.state.ledger = ledger

    def authorized(provided: str | None) -> None:
        if not provided or not hmac.compare_digest(provided, token):
            raise HTTPException(status_code=401, detail="Regional authentication required")

    @app.post("/v1/search")
    def search(body: RegionSearch, x_region_token: str | None = Header(default=None)) -> dict:
        authorized(x_region_token)
        if body.department not in departments:
            raise HTTPException(status_code=403, detail="Department outside regional scope")
        plate = normalize_plate(body.plate)
        if not 4 <= len(plate) <= 16:
            raise HTTPException(status_code=422, detail="Invalid plate")
        with db.connection() as connection:
            rows = connection.execute("""SELECT s.id,s.camera_id,s.plate_normalized,s.received_utc,
                s.source_pts,s.stream_generation,s.review_status,s.evidence_sha256,c.department
                FROM sightings s JOIN cameras c USING(camera_id)
                WHERE c.department=? AND s.plate_normalized=? ORDER BY s.received_utc DESC LIMIT ?""",
                (body.department, plate, body.limit)).fetchall()
        return {"region_id": region_id, "department": body.department,
                "hits": [{"region_id": region_id, **dict(row)} for row in rows],
                "video_exported": False}

    @app.post("/v1/local-events")
    def local_event(event: MetadataEvent, x_region_token: str | None = Header(default=None)) -> dict:
        authorized(x_region_token)
        if event.department not in departments:
            raise HTTPException(status_code=403, detail="Department outside regional scope")
        try:
            return ledger.enqueue(event)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/v1/outbox")
    def outbox(x_region_token: str | None = Header(default=None)) -> dict:
        authorized(x_region_token)
        return ledger.status()

    @app.post("/v1/flush")
    def flush(x_region_token: str | None = Header(default=None)) -> dict:
        authorized(x_region_token)
        if not central_url:
            raise HTTPException(status_code=503, detail="Central event destination not configured")
        ledger.capture_local_changes(departments)
        return ledger.flush(send_event)

    return app
