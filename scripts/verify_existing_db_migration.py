"""Migrate an SQLite backup of the current prototype; never modify its source."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def counts(connection: sqlite3.Connection) -> dict:
    return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("cameras", "sightings", "pursuits")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=ROOT / "backend/data/sakhyapath.sqlite3")
    args = parser.parse_args()
    if not args.source.is_file():
        raise SystemExit("Prototype database not found")
    with tempfile.TemporaryDirectory(prefix="sakhyapath-migration-check-") as directory:
        copy = Path(directory) / "backup.sqlite3"
        with closing(sqlite3.connect(args.source)) as source, closing(sqlite3.connect(copy)) as target:
            before = counts(source)
            source.backup(target)
        app = create_app(Settings(copy, "verification-only-key-123456"))
        with TestClient(app) as client:
            client.get("/api/v1/health").raise_for_status()
        with closing(sqlite3.connect(copy)) as migrated:
            after = counts(migrated)
            assert migrated.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            tables = {row[0] for row in migrated.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"cameras", "sightings", "pursuits", "search_proofs",
                    "regional_outbox", "regional_inbox", "regional_camera_state",
                    "shadow_decisions", "pursuit_exploration", "time_mappings"}
        assert before == after
        assert required <= tables
        print(json.dumps({"result": "PASS", "source_unchanged": True,
                          "preserved_counts": after,
                          "new_tables_present": sorted(required - {"cameras", "sightings", "pursuits"})}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
