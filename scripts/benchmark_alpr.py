"""Measure local FastALPR latency on a supplied, authorised image.

Example:
  python scripts/benchmark_alpr.py backend/data/fastalpr_sample.png --runs 30
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.vision.recognizer import FastAlprRecognizer  # noqa: E402


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--runs", type=int, default=30)
    args = parser.parse_args()
    if args.runs < 2:
        parser.error("--runs must be at least 2")
    frame = cv2.imread(str(args.image))
    if frame is None:
        parser.error("Image could not be decoded")
    started = time.perf_counter()
    model = FastAlprRecognizer(ROOT / "backend/data/models")
    load_ms = (time.perf_counter() - started) * 1000
    latencies: list[float] = []
    predictions = []
    for _ in range(args.runs):
        started = time.perf_counter()
        predictions = model.predict(frame)
        latencies.append((time.perf_counter() - started) * 1000)
    print(json.dumps({
        "provider": model.provider,
        "model_version": model.model_version,
        "image": str(args.image),
        "image_dimensions": [frame.shape[1], frame.shape[0]],
        "unique_images": 1,
        "runs": args.runs,
        "model_load_ms": round(load_ms, 1),
        "median_inference_ms": round(statistics.median(latencies), 1),
        "p95_inference_ms": round(percentile(latencies, .95), 1),
        "recognized": [item.raw_text for item in predictions],
        "note": "Repeated timing of one image; not an accuracy or multi-camera capacity study.",
    }, indent=2))


if __name__ == "__main__":
    main()
