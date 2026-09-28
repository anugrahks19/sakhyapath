"""Equal-budget annotated replay, with schedule-only and real-model results.

Both policies see the same official sample/blank frames from reset. This is a
controlled frame replay, not a live-feed or Indian-road accuracy study.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.storage.intelligence import normalize_plate  # noqa: E402
from app.services.pursuit import allocate_rates  # noqa: E402
from app.vision.recognizer import FastAlprRecognizer  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DURATION = 10.0
BUDGET = 3.0
CAMERAS = ("origin", "expected-east", "unexpected-west")
UNIFORM = {camera: 1.0 for camera in CAMERAS}
ACTIVE = allocate_rates([
    {"camera_id": "expected-east", "rank": 1},
    {"camera_id": "origin", "rank": 2},
    {"camera_id": "unexpected-west", "rank": 3},
], BUDGET, True)
FRAME_LIMIT = round(BUDGET * DURATION)
CASES = [
    {"name": "expected branch", "target_camera": "expected-east", "visible_from": 1.2,
     "visible_until": 2.3},
    {"name": "surprise branch", "target_camera": "unexpected-west", "visible_from": 3.85,
     "visible_until": 5.10},
]
TARGET = "5AU5341"


def sample_times(rates: dict[str, float]) -> dict[str, list[float]]:
    events = sorted((index / rate, camera) for camera, rate in rates.items()
                    for index in range(math.ceil(DURATION * rate))
                    if index / rate < DURATION)
    sampled = {camera: [] for camera in rates}
    for at, camera in events[:FRAME_LIMIT]:
        sampled[camera].append(at)
    return sampled


def replay(case: dict, rates: dict[str, float]) -> dict:
    sampled = sample_times(rates)
    hits = [time for time in sampled[case["target_camera"]]
            if case["visible_from"] <= time <= case["visible_until"]]
    return {"rates_fps": rates, "total_budget_fps": BUDGET,
            "requested_total_fps": round(sum(rates.values()), 3),
            "frames_analyzed": sum(len(times) for times in sampled.values()),
            "valid_time_to_next_sighting_seconds": round(hits[1], 3) if len(hits) >= 2 else None,
            "candidate_reads": len(hits),
            "misses": 0 if len(hits) >= 2 else 1, "false_alerts": 0,
            "coverage_gap": "fewer than two concordant target samples" if len(hits) < 2 else None,
            "per_camera_frames": {camera: len(times) for camera, times in sampled.items()}}


def model_replay(case: dict, rates: dict[str, float], model, target_image, blank_image) -> dict:
    sampled = sample_times(rates)
    target_reads = []
    false_reads = []
    for camera in CAMERAS:
        for at in sampled[camera]:
            visible = (camera == case["target_camera"] and
                       case["visible_from"] <= at <= case["visible_until"])
            frame = target_image if visible else blank_image
            reads = [normalize_plate(item.raw_text) for item in model.predict(frame)]
            if TARGET in reads:
                if visible:
                    target_reads.append(at)
                else:
                    false_reads.append({"camera": camera, "at": round(at, 3)})
    target_reads.sort()
    return {"frames_analyzed": sum(map(len, sampled.values())),
            "target_reads": len(target_reads),
            "valid_time_to_next_sighting_seconds": round(target_reads[1], 3)
            if len(target_reads) >= 2 else None,
            "misses": 0 if len(target_reads) >= 2 else 1,
            "false_alerts": 1 if len(false_reads) >= 2 else 0,
            "false_reads": false_reads,
            "coverage_gap": "fewer than two model target reads" if len(target_reads) < 2 else None}


def main() -> None:
    assert sum(UNIFORM.values()) == BUDGET and sum(ACTIVE.values()) <= BUDGET
    results = []
    for case in CASES:
        uniform = replay(case, UNIFORM)
        active = replay(case, ACTIVE)
        assert uniform["frames_analyzed"] == active["frames_analyzed"] == FRAME_LIMIT
        results.append({"case": case, "uniform": uniform, "active_pursuit": active})
    measurement_path = ROOT / "output/benchmarks/module4_owned_pipeline.json"
    capacity = json.loads(measurement_path.read_text(encoding="utf-8")) if measurement_path.exists() else None
    sample = cv2.imread(str(ROOT / "backend/data/fastalpr_sample.png"))
    if sample is None:
        raise RuntimeError("Official local FastALPR sample is required for the model replay")
    blank = np.full_like(sample, 210)
    model = FastAlprRecognizer(ROOT / "backend/data/models")
    probe = {normalize_plate(item.raw_text) for item in model.predict(sample)}
    if TARGET not in probe:
        raise RuntimeError(f"Local model did not read the annotated target: {probe}")
    for item in results:
        item["model_replay"] = {
            "uniform": model_replay(item["case"], UNIFORM, model, sample, blank),
            "active_pursuit": model_replay(item["case"], ACTIVE, model, sample, blank),
        }
    output = {
        "source": "deterministic annotated owned-camera replay simulation",
        "recognition": f"FastALPR {model.model_version} / {model.provider} on official sample and blank frames; two concordant target reads required",
        "method": "Actual allocate_rates policy for adaptive; reset sampler/read streak at t=0; cap both at 30 analyzed frames over 10 seconds; evaluate identical annotated visibility windows",
        "capacity_reference": (str(measurement_path.relative_to(ROOT)) if capacity else None),
        "comparison_budget_within_measured_limit": (BUDGET <= capacity["scheduler_budget_fps_70_percent"]
                                                    if capacity else None),
        "interpretation": "Expected branch favours adaptive sampling; surprise branch exposes its miss. No universal improvement is claimed.",
        "results": results,
    }
    path = ROOT / "output/benchmarks/module4_equal_budget_comparison.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
