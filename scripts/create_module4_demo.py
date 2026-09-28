"""Create a clearly labelled, synthetic Module 4 PDF for visual layout QA."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.report import build_report  # noqa: E402


def main() -> None:
    timestamp = "2026-09-28T07:00:00+00:00"
    windows = []
    cases = [
        ("demo-east", "observed", "Supported target read in sampled frames", 30, 31, 29, 0, "online"),
        ("demo-central", "not observed in sampled frames", "No supported read among sufficient samples", 25, 27, 24, 0, "online"),
        ("demo-west", "feed unavailable", "Owned replay disconnected", 25, 0, 0, 1, "unavailable"),
        ("demo-north", "insufficient coverage", "Worker did not acknowledge enough sampling", 0, 9, 2, 0, "online"),
    ]
    for camera, code, reason, planned, received, analyzed, errors, health in cases:
        windows.append({
            "revision": 2, "camera_id": camera, "window_start_utc": timestamp,
            "window_end_utc": "2026-09-28T07:00:10+00:00", "result_code": code,
            "reason": reason, "planned_frames": planned, "received_frames": received,
            "analyzed_frames": analyzed, "decode_errors": errors, "health": health,
        })
    allocations = [
        {"camera_id": "demo-east", "requested_fps": 3.0, "applied_fps": 2.9,
         "current_applied_fps": 2.9, "allocation_reason": "Highest ranked healthy camera"},
        {"camera_id": "demo-central", "requested_fps": 2.5, "applied_fps": 2.4,
         "current_applied_fps": 2.4, "allocation_reason": "Alternative direction baseline"},
        {"camera_id": "demo-west", "requested_fps": 2.5, "applied_fps": 0.0,
         "current_applied_fps": 0.0, "allocation_reason": "Feed became unavailable"},
        {"camera_id": "demo-north", "requested_fps": 0.0, "applied_fps": 0.0,
         "current_applied_fps": 0.0, "allocation_reason": "Excluded by measured worker budget"},
    ]
    fixture = {
        "pursuit": {"target_plate": "GJ01AB1234", "id": "synthetic-module4-qa",
                    "created_utc": timestamp, "department_scope": "Owned demonstration"},
        "counts": {"records": 0, "observations": 0, "candidates": 0, "rejected": 0},
        "observations": [], "records": [], "links": [], "alerts": [],
        "gaps": ["Synthetic layout fixture only. Counts and coverage are examples, not operational detections."],
        "active_pursuit": {
            "schedule": {"revision": 2, "created_utc": timestamp, "budget_fps": 8.447,
                         "reserved_fps": 0.0, "reason": "Synthetic QA revision after feed health change"},
            "allocations": allocations,
        },
        "coverage": {"windows": windows},
    }
    output = ROOT / "output/pdf/module4_synthetic_layout_qa.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(build_report(fixture))
    print(f"{output} (synthetic PDF layout fixture; no real sighting claims)")


if __name__ == "__main__":
    main()
