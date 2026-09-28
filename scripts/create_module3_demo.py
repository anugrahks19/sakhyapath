"""Produce one clearly labelled, synthetic owned-feed Module 3 PDF for visual QA."""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.journey import JourneyStore  # noqa: E402
from app.services.report import build_report  # noqa: E402
from app.storage.database import Database  # noqa: E402
from app.storage.intelligence import IntelligenceStore  # noqa: E402


def jpeg(plate: str) -> bytes:
    image = np.full((110, 390, 3), 245, dtype=np.uint8)
    cv2.rectangle(image, (4, 4), (386, 106), (52, 73, 103), 2)
    cv2.putText(image, plate, (13, 71), cv2.FONT_HERSHEY_SIMPLEX,
                1.05, (28, 41, 58), 2, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", image)
    if not ok:
        raise RuntimeError("Could not encode synthetic plate")
    return encoded.tobytes()


def main() -> None:
    data_dir = ROOT / "backend/data"
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="module3_demo_", dir=data_dir) as temporary:
        demo = Path(temporary)
        db = Database(demo / "demo.sqlite3")
        db.migrate()
        intelligence = IntelligenceStore(db, demo / "evidence")
        intelligence.migrate()
        journeys = JourneyStore(db, intelligence)
        journeys.migrate()
        cameras = [("ahmedabad-north", 23.04, 72.55),
                   ("ahmedabad-central", 23.07, 72.59),
                   ("ahmedabad-east", 23.10, 72.64)]
        db.import_owned_many([{
            "camera_id": camera_id, "display_name": camera_id.replace("-", " ").title(),
            "department": "Owned demonstration", "latitude": latitude,
            "longitude": longitude, "source_mode": "owned_replay",
            "hls_url": "http://127.0.0.1/synthetic-only.m3u8",
        } for camera_id, latitude, longitude in cameras])
        intelligence.create_watchlist("GJ01AB1234", "representative", "Synthetic PDF QA fixture",
                                      None, "demo-script")
        anchor = datetime(2026, 9, 28, 7, 0, tzinfo=timezone.utc)
        for index, (camera_id, _, _) in enumerate(cameras):
            moment = anchor + timedelta(minutes=index * 6)
            intelligence.record_read(
                camera_id=camera_id, source_mode="owned_replay", source_pts=30.0,
                pts_timebase="1/90000", stream_generation=1,
                received_utc=moment.isoformat(), raw_text="GJ01AB1234",
                detector_score=.96, ocr_score=.93, bbox=(0, 0, 390, 110),
                crop_jpeg=jpeg("GJ01AB1234"),
                model_version="synthetic-annotated-fixture-v1", confirmed=True,
            )
            journeys.add_time_mapping(
                camera_id, 1, 30.0, moment.isoformat(), 100,
                "owned_recording_clock_attested",
                "Controlled synthetic recording UTC anchor for PDF layout QA",
            )
        false_read = intelligence.record_read(
            camera_id="ahmedabad-central", source_mode="owned_replay", source_pts=3.0,
            pts_timebase="1/90000", stream_generation=2,
            received_utc=(anchor + timedelta(minutes=8)).isoformat(),
            raw_text="GJ01AB1234", detector_score=.76, ocr_score=.82,
            bbox=(0, 0, 390, 110), crop_jpeg=jpeg("GJ01AB1234"),
            model_version="synthetic-annotated-fixture-v1", confirmed=False,
        )
        journeys.review(false_read["id"], "rejected", None,
                        "Synthetic false-positive example", None, "demo-reviewer")
        pursuit = journeys.create("GJ01AB1234", from_utc=None, to_utc=None,
                                  camera_id=None, review_status=None,
                                  max_speed_kmh=160, department=None, actor="demo-script")
        result = journeys.journey(pursuit["id"], None)
        if result is None:
            raise RuntimeError("Synthetic journey was not created")
        output = ROOT / "output/pdf/module3_owned_fixture_report.pdf"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(build_report(result))
        print(f"{output} ({result['counts']['observations']} observations, "
              f"{result['counts']['rejected']} rejected example; synthetic owned fixture)")


if __name__ == "__main__":
    main()
