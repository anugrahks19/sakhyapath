"""Compare uniform and Active Pursuit on one annotated, clock-aligned frame manifest.

All frame predictions must be computed once with the same model before comparing
policies. No footage or Government result is bundled with this script.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.pursuit import allocate_rates  # noqa: E402
from app.storage.intelligence import normalize_plate  # noqa: E402


def sample_policy(frames: list[dict], rates: dict[str, float], frame_limit: int,
                  target_plate: str) -> dict:
    selected = []
    next_due = {camera_id: 0.0 for camera_id in rates}
    for frame in sorted(frames, key=lambda row: (row["timeline_seconds"], row["camera_id"])):
        camera_id = frame["camera_id"]
        rate = rates.get(camera_id, 0)
        if rate <= 0 or len(selected) >= frame_limit:
            continue
        at = float(frame["timeline_seconds"])
        if at + 1e-9 < next_due[camera_id]:
            continue
        selected.append(frame)
        next_due[camera_id] = at + 1 / rate
    streaks: dict[str, tuple[int, float]] = {}
    valid_time = None
    false_alerts = 0
    target_reads = 0
    per_camera = {camera_id: 0 for camera_id in rates}
    for frame in selected:
        camera_id = frame["camera_id"]
        per_camera[camera_id] += 1
        at = float(frame["timeline_seconds"])
        model_hit = target_plate in {normalize_plate(text) for text in frame.get("model_reads", [])}
        if not model_hit:
            streaks.pop(camera_id, None)
            continue
        if frame.get("target_visible"):
            target_reads += 1
        previous = streaks.get(camera_id)
        count = previous[0] + 1 if previous and at - previous[1] <= 3 else 1
        streaks[camera_id] = (count, at)
        if count == 2:
            if frame.get("target_visible") and valid_time is None:
                valid_time = at
            elif not frame.get("target_visible"):
                false_alerts += 1
    truth_cameras = {row["camera_id"] for row in frames if row.get("target_visible")}
    return {
        "requested_rates_fps": rates,
        "frame_budget": frame_limit,
        "frames_analyzed": len(selected),
        "per_camera_frames": per_camera,
        "valid_time_to_next_sighting_seconds": round(valid_time, 3) if valid_time is not None else None,
        "target_reads": target_reads,
        "misses": 0 if valid_time is not None else 1,
        "false_alerts": false_alerts,
        "coverage_gaps": sorted(camera for camera in truth_cameras if per_camera.get(camera, 0) < 2),
    }


def compare_scenario(scenario: dict) -> dict:
    if scenario.get("clock_basis") != "verified_common_timeline":
        raise ValueError("A verified common timeline is required for cross-camera time comparison")
    cameras = scenario.get("ranked_camera_ids")
    if not isinstance(cameras, list) or not 2 <= len(cameras) <= 4 or len(set(cameras)) != len(cameras):
        raise ValueError("Provide 2-4 distinct ranked camera IDs")
    duration = float(scenario["duration_seconds"])
    budget = float(scenario["budget_fps"])
    if duration <= 0 or budget < .2 * len(cameras):
        raise ValueError("Duration or measured frame budget is invalid")
    frames = scenario.get("frames", [])
    if not frames or any(row.get("camera_id") not in cameras or
                         not 0 <= float(row.get("timeline_seconds", -1)) < duration
                         for row in frames):
        raise ValueError("Every annotated frame needs a selected camera and valid timeline time")
    target = normalize_plate(scenario["target_plate"])
    if not target:
        raise ValueError("Target plate is missing")
    uniform = {camera: budget / len(cameras) for camera in cameras}
    adaptive = allocate_rates([{"camera_id": camera, "rank": index}
                               for index, camera in enumerate(cameras, 1)], budget, True)
    limit = math.floor(budget * duration)
    return {
        "scenario_id": scenario["scenario_id"],
        "clock_basis": scenario["clock_basis"],
        "source_mode": scenario["source_mode"],
        "source_note": scenario.get("source_note", ""),
        "method": "Same precomputed frame predictions, same annotated timeline, reset per policy, same total frame cap",
        "uniform": sample_policy(frames, uniform, limit, target),
        "active_pursuit": sample_policy(frames, adaptive, limit, target),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "output/benchmarks/recorded_sampling_comparison.json")
    args = parser.parse_args()
    scenario = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = compare_scenario(scenario)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
