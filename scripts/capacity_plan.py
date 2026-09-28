"""Scenario sizing from measured prototype throughput and explicit assumptions."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def size_scenario(*, registered: int, active_fraction: float, sample_fps: float,
                  bitrate_mbps: float, worker_budget_fps: float,
                  failover_fraction: float = .2,
                  events_per_camera_day: float = 0,
                  crop_kib: float = 0, retention_days: int = 0) -> dict:
    if registered < 1 or not 0 <= active_fraction <= 1 or sample_fps <= 0:
        raise ValueError("Registered count, active fraction and fps must be valid")
    if bitrate_mbps <= 0 or worker_budget_fps <= 0 or failover_fraction < 0:
        raise ValueError("Bitrate, worker budget and failover fraction must be valid")
    concurrent = math.ceil(registered * active_fraction)
    required_fps = concurrent * sample_fps
    base_workers = math.ceil(required_fps / worker_budget_fps)
    spare_workers = math.ceil(base_workers * failover_fraction)
    feed_gbps = concurrent * bitrate_mbps / 1000
    evidence_gib = (registered * events_per_camera_day * crop_kib * retention_days /
                    (1024 * 1024))
    return {
        "registered_cameras": registered,
        "assumed_active_fraction": active_fraction,
        "concurrent_analyzed_cameras": concurrent,
        "assumed_fps_each": sample_fps,
        "total_analyzed_fps": round(required_fps, 2),
        "measured_worker_budget_fps": worker_budget_fps,
        "illustrative_base_workers_at_same_performance": base_workers,
        "illustrative_failover_workers": spare_workers,
        "illustrative_total_workers": base_workers + spare_workers,
        "assumed_feed_bitrate_mbps": bitrate_mbps,
        "active_feed_ingress_gbps": round(feed_gbps, 3),
        "assumed_events_per_camera_day": events_per_camera_day,
        "assumed_crop_kib": crop_kib,
        "assumed_retention_days": retention_days,
        "unreplicated_evidence_gib": round(evidence_gib, 2),
        "limitations": [
            "Worker estimate extrapolates one laptop's owned two-feed replay and is not procurement sizing",
            "Feed ingress excludes protocol, network replication and backup overhead",
            "Evidence estimate excludes metadata, index, replicas, clips and backups",
            "No costs are calculated until regional hardware and tariffs are supplied",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registered", type=int, required=True)
    parser.add_argument("--active-fraction", type=float, required=True)
    parser.add_argument("--sample-fps", type=float, required=True)
    parser.add_argument("--bitrate-mbps", type=float, required=True)
    parser.add_argument("--worker-budget-fps", type=float)
    parser.add_argument("--failover-fraction", type=float, default=.2)
    parser.add_argument("--events-per-camera-day", type=float, default=0)
    parser.add_argument("--crop-kib", type=float, default=0)
    parser.add_argument("--retention-days", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    benchmark_path = ROOT / "output/benchmarks/module4_owned_pipeline.json"
    budget = args.worker_budget_fps
    if budget is None:
        budget = json.loads(benchmark_path.read_text(encoding="utf-8"))[
            "scheduler_budget_fps_70_percent"]
    result = size_scenario(
        registered=args.registered, active_fraction=args.active_fraction,
        sample_fps=args.sample_fps, bitrate_mbps=args.bitrate_mbps,
        worker_budget_fps=budget, failover_fraction=args.failover_fraction,
        events_per_camera_day=args.events_per_camera_day,
        crop_kib=args.crop_kib, retention_days=args.retention_days,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
