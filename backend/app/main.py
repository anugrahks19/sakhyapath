from __future__ import annotations

import hmac
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
import cv2
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.auth import Session, SessionManager
from app.config import Settings
from app.ingest.capture import CaptureManager
from app.ingest.catalogue import SentinelCatalogue
from app.schemas import (AnalysisInput, CapacityMeasurementInput, LoginInput, OwnedCameraInput, PursuitInput,
                         ReviewInput, TimeMappingInput, WatchlistInput, CaseInput,
                         CaseHandoffInput, HandoffAcknowledgeInput, CaseNoteInput, CaseStatusInput)
from app.services.journey import JourneyStore
from app.services.pursuit import ActivePursuit
from app.services.report import build_report
from app.services.proof import SearchProof
from app.services.trust import CameraTrust
from app.services.casebridge import CaseBridge
from app.services.regional import MetadataEvent, RegionalCoordinator, RegionalLedger
from app.storage.database import Database
from app.storage.intelligence import IntelligenceStore
from app.vision.pipeline import AnalyticsCoordinator


def create_app(settings: Settings | None = None, catalogue: SentinelCatalogue | None = None,
               regional_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    database = Database(settings.database_path)
    sessions = SessionManager(settings.operator_key, settings.department_keys)
    captures = CaptureManager(database, settings.idle_capture_seconds)
    intelligence = IntelligenceStore(
        database, settings.evidence_dir or settings.database_path.parent / "evidence"
    )
    journeys = JourneyStore(database, intelligence)
    analytics = AnalyticsCoordinator(
        database, intelligence, captures,
        settings.models_dir or settings.database_path.parent / "models",
        settings.analytics_max_cameras,
    )
    active_pursuit = ActivePursuit(database, journeys, analytics, captures)
    proofs = SearchProof(database, settings.proof_key_path or settings.database_path.parent / "proof_signing_ed25519.pem")
    casebridge = CaseBridge(database, journeys, proofs)
    trust = CameraTrust(database)
    regional_ledger = RegionalLedger(database)
    regional = RegionalCoordinator(settings.regions or [], regional_transport)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.migrate()
        intelligence.migrate()
        journeys.migrate()
        active_pursuit.migrate()
        proofs.migrate()
        casebridge.migrate()
        regional_ledger.migrate()
        analytics.restore()
        active_pursuit.start_monitor()
        yield
        active_pursuit.shutdown()
        analytics.shutdown()
        captures.shutdown()

    app = FastAPI(title="SakhyaPath Camera Intelligence", version="0.4.0", lifespan=lifespan)
    app.state.database = database
    app.state.captures = captures
    app.state.intelligence = intelligence
    app.state.journeys = journeys
    app.state.analytics = analytics
    app.state.active_pursuit = active_pursuit
    app.state.proofs = proofs
    app.state.casebridge = casebridge
    app.state.regional_ledger = regional_ledger

    def require_session(sakhyapath_session: str | None = Cookie(default=None)) -> Session:
        session = sessions.get(sakhyapath_session)
        if not session:
            raise HTTPException(status_code=401, detail="Authentication required")
        return session

    def require_write(
        session: Session = Depends(require_session),
        x_csrf_token: str | None = Header(default=None),
    ) -> Session:
        if not x_csrf_token or not hmac.compare_digest(session.csrf, x_csrf_token):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
        return session

    def require_operator(session: Session = Depends(require_write)) -> Session:
        if session.department is not None:
            raise HTTPException(status_code=403, detail="Operator permission required")
        return session

    def camera_for(session: Session, camera_id: str) -> dict:
        camera = database.camera(camera_id)
        if not camera or (session.department is not None and
                          camera["department"] != session.department):
            raise HTTPException(status_code=404, detail="Camera not found")
        return camera

    def sighting_for(session: Session, sighting_id: str) -> dict:
        item = intelligence.sighting(sighting_id)
        if not item:
            raise HTTPException(status_code=404, detail="Sighting not found")
        camera_for(session, item["camera_id"])
        return item

    def alert_for(session: Session, alert_id: str) -> dict:
        with database.connection() as connection:
            row = connection.execute(
                """SELECT a.id,s.camera_id FROM alerts a JOIN sightings s
                   ON a.sighting_id=s.id WHERE a.id=?""", (alert_id,)
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
        camera_for(session, row["camera_id"])
        return dict(row)

    def checked_utc(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise HTTPException(status_code=422, detail="Time filter must include a timezone")
        return value.astimezone(timezone.utc).isoformat()

    def operator_case(case_id: str, session: Session) -> dict:
        if session.department is not None:
            raise HTTPException(status_code=403, detail="Operator permission required")
        case = casebridge.get(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        return case

    @app.post("/api/v1/cases", status_code=201)
    def create_case(body: CaseInput, _: Session = Depends(require_operator)) -> dict:
        try:
            return casebridge.create(body.model_dump(), "operator")
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="Case reference already exists") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/v1/cases")
    def cases(_: Session = Depends(require_session)) -> list[dict]:
        if _.department is not None:
            raise HTTPException(status_code=403, detail="Operator permission required")
        return casebridge.list()

    @app.get("/api/v1/cases/shift-briefing")
    def case_shift_briefing(session: Session = Depends(require_session)) -> dict:
        if session.department is not None:
            raise HTTPException(status_code=403, detail="Operator permission required")
        return casebridge.shift_briefing()

    @app.get("/api/v1/cases/inbox")
    def case_inbox(session: Session = Depends(require_session)) -> list[dict]:
        if session.department is None:
            raise HTTPException(status_code=403, detail="Department sign-in required")
        return casebridge.inbox(session.department)

    @app.post("/api/v1/cases/handoffs/{handoff_id}/acknowledge")
    def case_acknowledge(handoff_id: str, body: HandoffAcknowledgeInput,
                         session: Session = Depends(require_write)) -> dict:
        if session.department is None:
            raise HTTPException(status_code=403, detail="Recipient department sign-in required")
        try:
            return casebridge.acknowledge(handoff_id, session.department, body.note)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Handoff not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v1/cases/{case_id}")
    def case_detail(case_id: str, session: Session = Depends(require_session)) -> dict:
        operator_case(case_id, session)
        return casebridge.detail(case_id)

    @app.post("/api/v1/cases/{case_id}/handoffs", status_code=201)
    def case_handoff(case_id: str, body: CaseHandoffInput,
                     session: Session = Depends(require_operator)) -> dict:
        case = operator_case(case_id, session)
        try:
            return casebridge.create_handoff(case, body.recipient_department,
                                             body.sighting_id, body.note, "operator")
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v1/cases/{case_id}/notes")
    def case_note(case_id: str, body: CaseNoteInput,
                  session: Session = Depends(require_operator)) -> dict:
        return casebridge.add_note(operator_case(case_id, session), "operator", body.note)

    @app.put("/api/v1/cases/{case_id}/status")
    def case_status(case_id: str, body: CaseStatusInput,
                    session: Session = Depends(require_operator)) -> dict:
        return casebridge.set_status(operator_case(case_id, session), body.status, "operator", body.note)

    @app.post("/api/v1/cases/{case_id}/pursuit", status_code=201)
    def case_pursuit(case_id: str, sighting_id: str,
                     session: Session = Depends(require_operator)) -> dict:
        try:
            return casebridge.attach_pursuit(operator_case(case_id, session), sighting_id, "operator")
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/v1/cases/{case_id}/timeline", status_code=201)
    def case_timeline(case_id: str, session: Session = Depends(require_operator)) -> dict:
        operator_case(case_id, session)
        return casebridge.signed_timeline(case_id)

    @app.get("/api/v1/cases/{case_id}/timeline/{snapshot_id}")
    def case_timeline_snapshot(case_id: str, snapshot_id: str,
                               session: Session = Depends(require_session)) -> dict:
        operator_case(case_id, session)
        result = casebridge.timeline(snapshot_id, case_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Timeline snapshot not found")
        return result

    @app.get("/api/v1/cases/{case_id}/timeline/{snapshot_id}/verify")
    def verify_case_timeline(case_id: str, snapshot_id: str,
                             session: Session = Depends(require_session)) -> dict:
        operator_case(case_id, session)
        result = casebridge.timeline(snapshot_id, case_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Timeline snapshot not found")
        return {"snapshot_id": snapshot_id, "signature_valid": SearchProof.verify(result),
                "meaning": "Verifies stored snapshot bytes and signature, not later case changes."}

    @app.get("/api/v1/health")
    def health() -> dict:
        return {"status": "ok", "module": "camera-grid-and-plate-intelligence", "database": "sqlite"}

    @app.post("/api/v1/auth/login")
    def login(body: LoginInput, response: Response) -> dict:
        result = sessions.login(body.operator_key)
        if not result:
            raise HTTPException(status_code=401, detail="Invalid operator key")
        token, session = result
        response.set_cookie(
            "sakhyapath_session", token, max_age=8 * 3600,
            httponly=True, secure=settings.cookie_secure, samesite="strict", path="/",
        )
        return {"authenticated": True, "csrf_token": session.csrf,
                "role": session.role, "department": session.department}

    @app.get("/api/v1/auth/me")
    def me(session: Session = Depends(require_session)) -> dict:
        return {"authenticated": True, "csrf_token": session.csrf,
                "role": session.role, "department": session.department}

    @app.post("/api/v1/auth/logout")
    def logout(response: Response, sakhyapath_session: str | None = Cookie(default=None),
               _: Session = Depends(require_write)) -> dict:
        sessions.logout(sakhyapath_session)
        response.delete_cookie("sakhyapath_session", path="/")
        return {"authenticated": False}

    @app.get("/api/v1/cameras")
    def list_cameras(session: Session = Depends(require_session)) -> list[dict]:
        return [camera for camera in database.cameras() if session.department is None
                or camera["department"] == session.department]

    @app.post("/api/v1/cameras/import", status_code=status.HTTP_201_CREATED)
    def import_cameras(cameras: list[OwnedCameraInput], _: Session = Depends(require_operator)) -> dict:
        if not cameras:
            raise HTTPException(status_code=400, detail="No cameras supplied")
        ids = [item.camera_id for item in cameras]
        if len(ids) != len(set(ids)):
            raise HTTPException(status_code=400, detail="Duplicate camera ID in import")
        try:
            changed = database.import_owned_many([camera.model_dump() for camera in cameras])
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        for camera_id in changed:
            resume = intelligence.analysis_status(camera_id)["enabled"]
            if analytics.status(camera_id)["running"]:
                analytics.stop(camera_id)
            captures.stop(camera_id)
            if resume:
                analytics.start(camera_id, intelligence.analysis_status(camera_id)["sample_fps"])
        return {"imported": len(cameras), "camera_ids": ids, "restarted": changed}

    @app.post("/api/v1/cameras/sync-sentinel")
    def sync_sentinel(_: Session = Depends(require_operator)) -> dict:
        source = catalogue
        if source is None:
            if not settings.sentinel_base_url:
                raise HTTPException(status_code=503, detail="Sentinel base URL is not configured")
            source = SentinelCatalogue(settings.sentinel_base_url, settings.sentinel_authorization)
        try:
            discovered = source.fetch()
            result = database.sync_sentinel(discovered)
            for camera_id in result["restart_ids"]:
                resume = intelligence.analysis_status(camera_id)["enabled"]
                if analytics.status(camera_id)["running"]:
                    analytics.stop(camera_id)
                captures.stop(camera_id)
                camera = database.camera(camera_id)
                if camera and camera["catalogue_present"] and resume:
                    analytics.start(camera_id, intelligence.analysis_status(camera_id)["sample_fps"])
        except (httpx.HTTPError, ValueError) as error:
            # Never echo remote URLs or tokens from exception strings.
            raise HTTPException(status_code=502, detail=f"Catalogue sync failed: {type(error).__name__}") from error
        return result

    @app.delete("/api/v1/cameras/{camera_id}")
    def delete_camera(camera_id: str, _: Session = Depends(require_operator)) -> dict:
        if analytics.status(camera_id)["running"]:
            analytics.stop(camera_id)
        captures.stop(camera_id)
        if not database.delete_camera(camera_id):
            raise HTTPException(status_code=404, detail="Camera not found")
        return {"deleted": True}

    @app.get("/api/v1/metrics")
    def metrics(session: Session = Depends(require_session)) -> dict:
        if session.department is not None:
            raise HTTPException(status_code=403, detail="Operator permission required")
        cameras = database.cameras()
        counts = captures.counts()
        analyzed = analytics.running_count()
        return {
            "registered": len(cameras),
            "sentinel_discovered": sum(1 for camera in cameras if camera["source_system"] == "sentinel"
                                       and camera["catalogue_present"]),
            "decoded_online": sum(1 for camera in cameras if camera["health_status"] == "online"),
            **counts,
            "concurrently_analyzed": analyzed,
            "capacity_measurement": active_pursuit.latest_measurement(),
            "pursuit_monitor": active_pursuit.monitor_status(),
        }

    @app.get("/api/v1/capacity/measurement")
    def capacity_measurement(session: Session = Depends(require_session)) -> dict:
        if session.department is not None:
            raise HTTPException(status_code=403, detail="Operator permission required")
        return {"latest": active_pursuit.latest_measurement()}

    @app.post("/api/v1/capacity/measurements", status_code=status.HTTP_201_CREATED)
    def record_capacity(body: CapacityMeasurementInput,
                        _: Session = Depends(require_operator)) -> dict:
        try:
            return active_pursuit.add_measurement(body.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/cameras/{camera_id}/analysis")
    def start_analysis(camera_id: str, body: AnalysisInput,
                       session: Session = Depends(require_write)) -> dict:
        camera_for(session, camera_id)
        try:
            with active_pursuit.lock:
                active_pursuit.guard_manual_analysis(camera_id, body.sample_fps)
                analytics.start(camera_id, body.sample_fps)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Camera not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return analytics.status(camera_id)

    @app.delete("/api/v1/cameras/{camera_id}/analysis")
    def stop_analysis(camera_id: str, session: Session = Depends(require_write)) -> dict:
        camera_for(session, camera_id)
        try:
            with active_pursuit.lock:
                active_pursuit.guard_manual_analysis(camera_id, None)
                analytics.stop(camera_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return analytics.status(camera_id)

    @app.get("/api/v1/cameras/{camera_id}/analysis")
    def analysis_status(camera_id: str, session: Session = Depends(require_session)) -> dict:
        camera_for(session, camera_id)
        return analytics.status(camera_id)

    @app.get("/api/v1/sightings")
    def sightings(plate: str | None = None, camera_id: str | None = None,
                  from_utc: datetime | None = None, to_utc: datetime | None = None,
                  review_status: Literal["candidate", "confirmed", "reviewed_confirmed", "rejected"] | None = None,
                  limit: int = Query(default=100, ge=1, le=500),
                  session: Session = Depends(require_session)) -> list[dict]:
        if camera_id:
            camera_for(session, camera_id)
        return journeys.search(plate=plate, camera_id=camera_id,
                               from_utc=checked_utc(from_utc), to_utc=checked_utc(to_utc),
                               review_status=review_status, department=session.department,
                               limit=limit)

    @app.get("/api/v1/sightings/{sighting_id}")
    def sighting(sighting_id: str, session: Session = Depends(require_session)) -> dict:
        return sighting_for(session, sighting_id)

    @app.get("/api/v1/sightings/{sighting_id}/evidence.jpg")
    def sighting_evidence(sighting_id: str, session: Session = Depends(require_session)) -> Response:
        sighting_for(session, sighting_id)
        data = intelligence.evidence(sighting_id)
        if data is None:
            raise HTTPException(status_code=409, detail="Evidence missing or hash mismatch")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})

    @app.get("/api/v1/watchlist")
    def watchlist(session: Session = Depends(require_session)) -> list[dict]:
        if session.department is not None:
            raise HTTPException(status_code=403, detail="Operator permission required")
        return intelligence.watchlist()

    @app.post("/api/v1/watchlist", status_code=status.HTTP_201_CREATED)
    def add_watchlist(body: WatchlistInput, _: Session = Depends(require_operator)) -> dict:
        try:
            return intelligence.create_watchlist(
                body.plate, body.category, body.source_label, body.expires_utc, "local-operator"
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/v1/watchlist/{entry_id}/disable")
    def disable_watchlist(entry_id: str, _: Session = Depends(require_operator)) -> dict:
        if not intelligence.disable_watchlist(entry_id):
            raise HTTPException(status_code=404, detail="Entry not found")
        return {"id": entry_id, "active": False}

    @app.get("/api/v1/alerts")
    def alerts(session: Session = Depends(require_session)) -> list[dict]:
        entries = intelligence.alerts()
        if session.department is None:
            return entries
        return [item for item in entries if (database.camera(item["camera_id"]) or {}).get(
            "department") == session.department]

    @app.get("/api/v1/alerts/stream")
    async def alert_stream(after_id: int = Query(default=0, ge=0),
                           sakhyapath_session: str | None = Cookie(default=None),
                           session: Session = Depends(require_session)) -> StreamingResponse:
        async def messages():
            cursor = after_id
            while sessions.get(sakhyapath_session):
                events = intelligence.events_after(cursor)
                if events:
                    for event in events:
                        cursor = event["id"]
                        if session.department is not None:
                            camera_id = event["payload"].get("camera_id")
                            if not camera_id or (database.camera(camera_id) or {}).get(
                                "department") != session.department:
                                continue
                        yield f"id: {cursor}\nevent: {event['kind']}\ndata: {json.dumps(event)}\n\n"
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(messages(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/v1/alerts/{alert_id}/acknowledge")
    def acknowledge_alert(alert_id: str, session: Session = Depends(require_write)) -> dict:
        alert_for(session, alert_id)
        if not intelligence.acknowledge_alert(alert_id, "local-operator"):
            raise HTTPException(status_code=409, detail="Alert not found or already acknowledged")
        return {"id": alert_id, "status": "acknowledged",
                "history": intelligence.alert_history(alert_id)}

    @app.get("/api/v1/alerts/{alert_id}/history")
    def alert_history(alert_id: str, session: Session = Depends(require_session)) -> list[dict]:
        alert_for(session, alert_id)
        return intelligence.alert_history(alert_id)

    @app.post("/api/v1/cameras/{camera_id}/time-mappings", status_code=status.HTTP_201_CREATED)
    def add_time_mapping(camera_id: str, body: TimeMappingInput,
                         session: Session = Depends(require_operator)) -> dict:
        camera_for(session, camera_id)
        try:
            return journeys.add_time_mapping(camera_id, body.stream_generation,
                                             body.pts_anchor, body.utc_anchor,
                                             body.uncertainty_ms, body.basis,
                                             body.evidence_note)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/v1/pursuits")
    def list_pursuits(session: Session = Depends(require_session)) -> list[dict]:
        return journeys.pursuits(session.department)

    @app.post("/api/v1/pursuits", status_code=status.HTTP_201_CREATED)
    def create_pursuit(body: PursuitInput, session: Session = Depends(require_write)) -> dict:
        try:
            return journeys.create(
                body.plate, from_utc=body.from_utc, to_utc=body.to_utc,
                camera_id=body.camera_id, review_status=body.review_status,
                max_speed_kmh=body.max_speed_kmh, department=session.department,
                actor=session.role if session.department is None else session.department,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Camera not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/v1/pursuits/{pursuit_id}")
    def pursuit_detail(pursuit_id: str, session: Session = Depends(require_session)) -> dict:
        result = journeys.pursuit(pursuit_id, session.department)
        if not result:
            raise HTTPException(status_code=404, detail="Search not found")
        return result

    @app.get("/api/v1/pursuits/{pursuit_id}/journey")
    def pursuit_journey(pursuit_id: str, session: Session = Depends(require_session)) -> dict:
        result = journeys.journey(pursuit_id, session.department)
        if not result:
            raise HTTPException(status_code=404, detail="Search not found")
        result["active_pursuit"] = active_pursuit.get_schedule(pursuit_id, session.department)
        result["coverage"] = active_pursuit.coverage(pursuit_id, session.department)
        return result

    @app.get("/api/v1/pursuits/{pursuit_id}/rankings")
    def pursuit_rankings(pursuit_id: str, session: Session = Depends(require_session)) -> dict:
        try:
            return active_pursuit.rankings(pursuit_id, session.department)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Search not found") from error

    @app.get("/api/v1/pursuits/{pursuit_id}/schedule")
    def pursuit_schedule(pursuit_id: str, session: Session = Depends(require_session)) -> dict:
        try:
            return active_pursuit.get_schedule(pursuit_id, session.department)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Search not found") from error

    @app.post("/api/v1/pursuits/{pursuit_id}/schedule")
    def start_pursuit_schedule(pursuit_id: str,
                               session: Session = Depends(require_operator)) -> dict:
        try:
            return active_pursuit.schedule(pursuit_id, session.department)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Search not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.delete("/api/v1/pursuits/{pursuit_id}/schedule")
    def stop_pursuit_schedule(pursuit_id: str,
                              session: Session = Depends(require_operator)) -> dict:
        try:
            return active_pursuit.stop(pursuit_id, session.department)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Search not found") from error

    @app.get("/api/v1/pursuits/{pursuit_id}/coverage")
    def pursuit_coverage(pursuit_id: str, session: Session = Depends(require_session)) -> dict:
        try:
            return active_pursuit.coverage(pursuit_id, session.department)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Search not found") from error

    @app.get("/api/v1/pursuits/{pursuit_id}/shadow")
    def pursuit_shadow(pursuit_id: str, session: Session = Depends(require_session)) -> dict:
        if not journeys.pursuit(pursuit_id, session.department):
            raise HTTPException(status_code=404, detail="Search not found")
        return active_pursuit.shadow.history(pursuit_id)

    @app.put("/api/v1/pursuits/{pursuit_id}/exploration")
    def set_exploration(pursuit_id: str, enabled: bool,
                        session: Session = Depends(require_operator)) -> dict:
        if not journeys.pursuit(pursuit_id, session.department):
            raise HTTPException(status_code=404, detail="Search not found")
        result = active_pursuit.shadow.set_enabled(pursuit_id, enabled)
        result["effective_after_next_schedule_revision"] = True
        return result

    @app.post("/api/v1/pursuits/{pursuit_id}/proofs", status_code=201)
    def create_proof(pursuit_id: str, session: Session = Depends(require_write)) -> dict:
        journey = journeys.journey(pursuit_id, session.department)
        if not journey:
            raise HTTPException(status_code=404, detail="Search not found")
        coverage = active_pursuit.coverage(pursuit_id, session.department)
        cameras = database.cameras()
        with database.connection() as connection:
            counters = {row["camera_id"]: dict(row) for row in connection.execute(
                "SELECT camera_id,received,selected,analyzed,dropped,model_version FROM analysis_counters")}
            source_ids = {row["camera_id"] for row in connection.execute("SELECT DISTINCT camera_id FROM camera_sources")}
        return proofs.create(journey, coverage, cameras, counters, source_ids)

    @app.get("/api/v1/pursuits/{pursuit_id}/proofs")
    def list_proofs(pursuit_id: str, session: Session = Depends(require_session)) -> list[dict]:
        if not journeys.pursuit(pursuit_id, session.department):
            raise HTTPException(status_code=404, detail="Search not found")
        return proofs.list(pursuit_id)

    def scoped_proof(proof_id: str, session: Session) -> dict:
        envelope = proofs.get(proof_id)
        if not envelope or not journeys.pursuit(envelope["payload"]["pursuit_id"], session.department):
            raise HTTPException(status_code=404, detail="Receipt not found")
        return envelope

    @app.get("/api/v1/proofs/public-key")
    def proof_public_key(_: Session = Depends(require_session)) -> dict:
        return {"algorithm": "Ed25519", "public_key_hex": proofs.public_key()}

    @app.get("/api/v1/proofs/{proof_id}.json")
    def proof_json(proof_id: str, session: Session = Depends(require_session)) -> dict:
        return scoped_proof(proof_id, session)

    @app.get("/api/v1/proofs/{proof_id}/verify")
    def verify_proof(proof_id: str, session: Session = Depends(require_session)) -> dict:
        envelope = scoped_proof(proof_id, session)
        return {"receipt_id": proof_id, "signature_valid": proofs.verify(envelope),
                "stored_pdf_signature_valid": proofs.verify_pdf(proofs.pdf_bytes(proof_id), envelope),
                "signed_by_current_server_key": envelope["public_key_hex"] == proofs.public_key(),
                "meaning": "Checks stored receipt bytes and signature; does not re-evaluate current evidence or video."}

    @app.get("/api/v1/proofs/{proof_id}.pdf")
    def proof_pdf(proof_id: str, session: Session = Depends(require_session)) -> Response:
        scoped_proof(proof_id, session)
        return Response(proofs.pdf_bytes(proof_id), media_type="application/pdf",
                        headers={"Cache-Control": "private, no-store",
                                 "Content-Disposition": f'attachment; filename="SakhyaPath_Proof_{proof_id}.pdf"'})

    @app.post("/api/v1/federation/search")
    async def federated_search(body: dict, session: Session = Depends(require_write)) -> dict:
        try:
            return await regional.search(str(body.get("plate", "")), session.department)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/v1/regions/{region_id}/events")
    def receive_region_event(region_id: str, event: MetadataEvent,
                             x_region_token: str | None = Header(default=None)) -> dict:
        source = next((row for row in settings.regions or [] if row["id"] == region_id), None)
        if not source or not x_region_token or not hmac.compare_digest(source["token"], x_region_token):
            raise HTTPException(status_code=401, detail="Regional authentication required")
        if event.department not in source["departments"]:
            raise HTTPException(status_code=403, detail="Department outside regional scope")
        return regional_ledger.receive(region_id, event)

    @app.get("/api/v1/regions/status")
    def regions_status(session: Session = Depends(require_session)) -> dict:
        if session.department is not None:
            raise HTTPException(status_code=403, detail="Operator permission required")
        result = regional_ledger.status()
        result["central_inbox_events"] = result.pop("received_metadata")
        result.pop("pending_metadata")
        result.pop("delivered_metadata")
        result.pop("oldest_pending_utc")
        result["gap_state"] = "remote_outbox_unknown_without_agent_contact"
        result["warning"] = "Central inbox counts cannot prove a remote region is connected or its video is continuous."
        result["configured_regions"] = [row["id"] for row in (settings.regions or [])]
        return result

    @app.get("/api/v1/regions/events")
    def region_events(session: Session = Depends(require_session)) -> dict:
        events = regional_ledger.inbox_events(session.department)
        open_gaps = regional_ledger.open_delivered_gaps(session.department)
        return {"events": events, "open_delivered_gaps": open_gaps,
                "warning": "Undelivered regional events are invisible while a link is down; a quiet inbox does not imply healthy video."}

    @app.get("/api/v1/pursuits/{pursuit_id}/report")
    def pursuit_report(pursuit_id: str, session: Session = Depends(require_session)) -> Response:
        result = pursuit_journey(pursuit_id, session)
        filename = f"SakhyaPath_Journey_{result['pursuit']['target_plate']}.pdf"
        return Response(build_report(result), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                 "Cache-Control": "private, no-store"})

    @app.post("/api/v1/sightings/{sighting_id}/review")
    def review_sighting(sighting_id: str, body: ReviewInput,
                        session: Session = Depends(require_write)) -> dict:
        try:
            return journeys.review(
                sighting_id, body.decision, body.corrected_plate, body.note,
                session.department,
                session.role if session.department is None else session.department,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Sighting not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/v1/sightings/{sighting_id}/review-history")
    def sighting_review_history(sighting_id: str,
                                session: Session = Depends(require_session)) -> list[dict]:
        try:
            return journeys.review_history(sighting_id, session.department)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Sighting not found") from error

    @app.get("/api/v1/cameras/{camera_id}")
    def camera_detail(camera_id: str, session: Session = Depends(require_session)) -> dict:
        return camera_for(session, camera_id)

    @app.get("/api/v1/cameras/{camera_id}/health")
    def camera_health(camera_id: str, session: Session = Depends(require_session)) -> dict:
        camera = camera_for(session, camera_id)
        return {
            "camera_id": camera_id,
            "health_status": camera["health_status"],
            "catalogue_live": camera["catalogue_live"],
            "catalogue_present": camera["catalogue_present"],
            "last_frame_utc": camera["last_frame_utc"],
            "source_pts": camera["source_pts"],
            "pts_timebase": camera["pts_timebase"],
            "measured_fps": camera["measured_fps"],
            "stream_generation": camera["stream_generation"],
            "capture": captures.state(camera_id),
            "history": database.health_events(camera_id),
        }

    @app.get("/api/v1/cameras/{camera_id}/trust")
    def camera_trust(camera_id: str, session: Session = Depends(require_session)) -> dict:
        return trust.scorecard(camera_for(session, camera_id), analytics.status(camera_id), captures.state(camera_id))

    @app.get("/api/v1/cameras/{camera_id}/snapshot.jpg")
    def snapshot(camera_id: str, session: Session = Depends(require_session)) -> Response:
        camera_for(session, camera_id)
        try:
            worker = captures.acquire(camera_id, preview=True)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Camera unavailable") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        try:
            packet = worker.wait_frame(None, timeout=8.0, require_fresh=True)
            if not packet:
                raise HTTPException(status_code=503, detail="No decoded frame available")
            ok, encoded = cv2.imencode(".jpg", packet.bgr, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                raise HTTPException(status_code=503, detail="Preview frame unavailable")
            return Response(
                encoded.tobytes(), media_type="image/jpeg",
                headers={
                    "Cache-Control": "no-store",
                    "X-Camera-Id": packet.camera_id,
                    "X-Source-PTS": "" if packet.source_pts is None else str(packet.source_pts),
                    "X-PTS-Timebase": packet.pts_timebase or "unavailable",
                    "X-Stream-Generation": str(packet.stream_generation),
                },
            )
        finally:
            captures.release(worker, preview=True)

    built_frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if built_frontend.is_dir():
        app.mount("/", StaticFiles(directory=built_frontend, html=True), name="frontend")

    return app

