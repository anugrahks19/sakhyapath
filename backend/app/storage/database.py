from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=20000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY)")
            version = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
            if version < 1:
                connection.executescript(
                    """
                    CREATE TABLE cameras (
                        camera_id TEXT PRIMARY KEY,
                        source_system TEXT NOT NULL,
                        source_mode TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        department TEXT NOT NULL,
                        latitude REAL NOT NULL,
                        longitude REAL NOT NULL,
                        source_type TEXT NOT NULL,
                        codec TEXT,
                        width INTEGER,
                        height INTEGER,
                        bitrate INTEGER,
                        catalogue_live INTEGER,
                        catalogue_present INTEGER NOT NULL DEFAULT 1,
                        health_status TEXT NOT NULL DEFAULT 'unknown',
                        last_frame_utc TEXT,
                        source_pts REAL,
                        pts_timebase TEXT,
                        measured_fps REAL,
                        stream_generation INTEGER NOT NULL DEFAULT 0,
                        discovered_utc TEXT NOT NULL,
                        updated_utc TEXT NOT NULL
                    );
                    CREATE TABLE camera_sources (
                        camera_id TEXT NOT NULL REFERENCES cameras(camera_id) ON DELETE CASCADE,
                        kind TEXT NOT NULL,
                        url TEXT NOT NULL,
                        PRIMARY KEY (camera_id, kind)
                    );
                    CREATE TABLE camera_health_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        camera_id TEXT NOT NULL REFERENCES cameras(camera_id),
                        at_utc TEXT NOT NULL,
                        status TEXT NOT NULL,
                        detail TEXT
                    );
                    CREATE INDEX camera_health_events_by_camera
                        ON camera_health_events(camera_id, at_utc DESC);
                    INSERT INTO schema_migrations(version) VALUES (1);
                    """
                )
            connection.execute("""CREATE TABLE IF NOT EXISTS camera_capture_errors (
                camera_id TEXT PRIMARY KEY REFERENCES cameras(camera_id),
                count INTEGER NOT NULL DEFAULT 0,
                last_kind TEXT)""")

    def import_owned(self, camera: dict[str, Any]) -> None:
        self.import_owned_many([camera])

    def import_owned_many(self, cameras: list[dict[str, Any]]) -> list[str]:
        now = utc_now()
        with self.connection() as connection:
            changed: list[str] = []
            for camera in cameras:
                if self._import_owned_row(connection, camera, now):
                    changed.append(camera["camera_id"])
            return changed

    def _import_owned_row(self, connection: sqlite3.Connection,
                          camera: dict[str, Any], now: str) -> bool:
        source_type = "rtsp" if camera.get("rtsp_url") else "hls"
        if not camera.get("rtsp_url") and not camera.get("hls_url"):
            raise ValueError("At least one real RTSP or HLS URL is required")
        existing = connection.execute(
            "SELECT source_system FROM cameras WHERE camera_id=?", (camera["camera_id"],)
        ).fetchone()
        if existing and existing["source_system"] != "owned":
            raise ValueError("Cannot replace a Sentinel camera through owned import")
        old_urls = {
            row["kind"]: row["url"]
            for row in connection.execute(
                "SELECT kind,url FROM camera_sources WHERE camera_id=?", (camera["camera_id"],)
            )
        }
        new_urls = {kind: camera[f"{kind}_url"] for kind in ("rtsp", "hls")
                    if camera.get(f"{kind}_url")}
        changed = bool(existing and old_urls != new_urls)
        connection.execute(
            """
            INSERT INTO cameras(camera_id,source_system,source_mode,display_name,department,
                latitude,longitude,source_type,codec,width,height,bitrate,catalogue_present,
                discovered_utc,updated_utc)
            VALUES(?, 'owned', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(camera_id) DO UPDATE SET
                source_mode=excluded.source_mode, display_name=excluded.display_name,
                department=excluded.department, latitude=excluded.latitude,
                longitude=excluded.longitude, source_type=excluded.source_type,
                codec=excluded.codec,width=excluded.width,height=excluded.height,
                bitrate=excluded.bitrate,catalogue_present=1,
                health_status=CASE WHEN ? THEN 'unknown' ELSE cameras.health_status END,
                last_frame_utc=CASE WHEN ? THEN NULL ELSE cameras.last_frame_utc END,
                source_pts=CASE WHEN ? THEN NULL ELSE cameras.source_pts END,
                pts_timebase=CASE WHEN ? THEN NULL ELSE cameras.pts_timebase END,
                measured_fps=CASE WHEN ? THEN NULL ELSE cameras.measured_fps END,
                updated_utc=excluded.updated_utc
            """,
            (
                camera["camera_id"], camera["source_mode"], camera["display_name"],
                camera["department"], camera["latitude"], camera["longitude"], source_type,
                camera.get("codec"), camera.get("width"), camera.get("height"),
                camera.get("bitrate"), now, now,
                changed, changed, changed, changed, changed,
            ),
        )
        connection.execute("DELETE FROM camera_sources WHERE camera_id=?", (camera["camera_id"],))
        self._write_sources(connection, camera["camera_id"], camera)
        if changed:
            connection.execute(
                "INSERT INTO camera_health_events(camera_id,at_utc,status,detail) VALUES(?,?,?,?)",
                (camera["camera_id"], now, "unknown", "Owned source URL changed"),
            )
        return changed

    def sync_sentinel(self, cameras: list[dict[str, Any]]) -> dict[str, Any]:
        now = utc_now()
        with self.connection() as connection:
            existing = {
                row["camera_id"]: dict(row)
                for row in connection.execute("SELECT * FROM cameras WHERE source_system='sentinel'")
            }
            seen: set[str] = set()
            restart_ids: set[str] = set()
            for camera in cameras:
                camera_id = camera["camera_id"]
                if camera_id in seen:
                    raise ValueError(f"Duplicate catalogue camera ID: {camera_id}")
                seen.add(camera_id)
                collision = connection.execute(
                    "SELECT source_system FROM cameras WHERE camera_id=?", (camera_id,)
                ).fetchone()
                if collision and collision["source_system"] != "sentinel":
                    raise ValueError(f"Catalogue ID collides with owned camera: {camera_id}")
                old = existing.get(camera_id)
                old_urls = {
                    row["kind"]: row["url"]
                    for row in connection.execute(
                        "SELECT kind,url FROM camera_sources WHERE camera_id=?", (camera_id,)
                    )
                }
                new_urls = {kind: camera[f"{kind}_url"] for kind in ("rtsp", "hls", "whep")
                            if camera.get(f"{kind}_url")}
                changed_source = old and (
                    not old["catalogue_present"]
                    or
                    old["source_type"] != camera["source_type"]
                    or old["codec"] != camera.get("codec")
                    or old["width"] != camera.get("width")
                    or old["height"] != camera.get("height")
                    or old_urls != new_urls
                )
                if changed_source:
                    restart_ids.add(camera_id)
                connection.execute(
                    """
                    INSERT INTO cameras(camera_id,source_system,source_mode,display_name,department,
                        latitude,longitude,source_type,codec,width,height,bitrate,catalogue_live,
                        catalogue_present,health_status,discovered_utc,updated_utc)
                    VALUES(?, 'sentinel', 'government_live', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1,
                        'unknown', ?, ?)
                    ON CONFLICT(camera_id) DO UPDATE SET
                        display_name=excluded.display_name,department=excluded.department,
                        latitude=excluded.latitude,longitude=excluded.longitude,
                        source_type=excluded.source_type,codec=excluded.codec,width=excluded.width,
                        height=excluded.height,bitrate=excluded.bitrate,
                        catalogue_live=excluded.catalogue_live,catalogue_present=1,
                        health_status=CASE WHEN ? THEN 'unknown' ELSE cameras.health_status END,
                        last_frame_utc=CASE WHEN ? THEN NULL ELSE cameras.last_frame_utc END,
                        source_pts=CASE WHEN ? THEN NULL ELSE cameras.source_pts END,
                        pts_timebase=CASE WHEN ? THEN NULL ELSE cameras.pts_timebase END,
                        measured_fps=CASE WHEN ? THEN NULL ELSE cameras.measured_fps END,
                        updated_utc=excluded.updated_utc
                    """,
                    (
                        camera_id, camera["display_name"], camera["department"],
                        camera["latitude"], camera["longitude"], camera["source_type"],
                        camera.get("codec"), camera.get("width"), camera.get("height"),
                        camera.get("bitrate"), camera.get("catalogue_live"), now, now,
                        bool(changed_source), bool(changed_source), bool(changed_source),
                        bool(changed_source), bool(changed_source),
                    ),
                )
                connection.execute("DELETE FROM camera_sources WHERE camera_id=?", (camera_id,))
                self._write_sources(connection, camera_id, camera)
            removed = {camera_id for camera_id, row in existing.items()
                       if row["catalogue_present"] and camera_id not in seen}
            restart_ids.update(removed)
            for camera_id in removed:
                connection.execute(
                    """UPDATE cameras SET catalogue_present=0,catalogue_live=0,
                       health_status='offline',updated_utc=? WHERE camera_id=?""",
                    (now, camera_id),
                )
                connection.execute("DELETE FROM camera_sources WHERE camera_id=?", (camera_id,))
                connection.execute(
                    "INSERT INTO camera_health_events(camera_id,at_utc,status,detail) VALUES(?,?,?,?)",
                    (camera_id, now, "offline", "Removed from Sentinel catalogue"),
                )
            restored = {camera_id for camera_id in seen if camera_id in existing
                        and not existing[camera_id]["catalogue_present"]}
            return {"discovered": len(cameras), "added": len(seen - set(existing)),
                    "restored": len(restored), "removed": len(removed),
                    "changed": len(restart_ids - removed - restored),
                    "restart_ids": sorted(restart_ids)}

    @staticmethod
    def _write_sources(connection: sqlite3.Connection, camera_id: str, camera: dict[str, Any]) -> None:
        for kind in ("rtsp", "hls", "whep"):
            url = camera.get(f"{kind}_url")
            if url:
                connection.execute(
                    "INSERT INTO camera_sources(camera_id,kind,url) VALUES(?,?,?)",
                    (camera_id, kind, url),
                )

    def cameras(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [self._public(row) for row in connection.execute("SELECT * FROM cameras ORDER BY camera_id")]

    def camera(self, camera_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM cameras WHERE camera_id=?", (camera_id,)).fetchone()
            return self._public(row) if row else None

    def source_urls(self, camera_id: str) -> dict[str, str]:
        with self.connection() as connection:
            return {
                row["kind"]: row["url"]
                for row in connection.execute("SELECT kind,url FROM camera_sources WHERE camera_id=?", (camera_id,))
            }

    def record_capture_error(self, camera_id: str, kind: str) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO camera_capture_errors(camera_id,count,last_kind)
                   VALUES(?,1,?) ON CONFLICT(camera_id) DO UPDATE SET
                   count=count+1,last_kind=excluded.last_kind""", (camera_id, kind)
            )

    def capture_error_count(self, camera_id: str) -> int:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT count FROM camera_capture_errors WHERE camera_id=?", (camera_id,)
            ).fetchone()
        return row["count"] if row else 0

    def health_events(self, camera_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [
                dict(row) for row in connection.execute(
                    """SELECT at_utc,status,detail FROM camera_health_events
                       WHERE camera_id=? ORDER BY id DESC LIMIT ?""", (camera_id, limit)
                )
            ]

    def update_health(self, camera_id: str, status: str, detail: str | None = None,
                      pts: float | None = None, timebase: str | None = None,
                      fps: float | None = None, generation: int | None = None) -> None:
        now = utc_now()
        with self.connection() as connection:
            old = connection.execute(
                "SELECT health_status FROM cameras WHERE camera_id=?", (camera_id,)
            ).fetchone()
            if old is None:
                return
            if status == "online":
                connection.execute(
                    """UPDATE cameras SET health_status=?,last_frame_utc=?,source_pts=?,
                       pts_timebase=?,measured_fps=?,stream_generation=COALESCE(?,stream_generation),
                       updated_utc=? WHERE camera_id=?""",
                    (status, now, pts, timebase, fps, generation, now, camera_id),
                )
            else:
                connection.execute(
                    "UPDATE cameras SET health_status=?,updated_utc=? WHERE camera_id=?",
                    (status, now, camera_id),
                )
            if old["health_status"] != status:
                connection.execute(
                    "INSERT INTO camera_health_events(camera_id,at_utc,status,detail) VALUES(?,?,?,?)",
                    (camera_id, now, status, detail),
                )

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["catalogue_live"] = None if data["catalogue_live"] is None else bool(data["catalogue_live"])
        data["catalogue_present"] = bool(data["catalogue_present"])
        return data
