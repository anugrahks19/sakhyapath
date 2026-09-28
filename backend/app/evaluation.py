"""Deterministic holdout scoring; no claim about footage that was not supplied."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from statistics import median
from typing import Any

from app.storage.intelligence import needs_manual_review, normalize_plate


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = int(position), min(len(ordered) - 1, int(position) + 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 2)


def _score(frames: list[dict], predictions: dict[str, list[dict]],
           auto_eligible: bool = False) -> dict[str, Any]:
    true_positive = false_positive = missed = 0
    frame_hits = 0
    model_latencies: list[float] = []
    for frame in frames:
        expected = Counter(normalize_plate(plate) for plate in frame.get("plates", []))
        actual = Counter()
        for read in predictions.get(frame["id"], []):
            raw = normalize_plate(read["plate"])
            if not raw:
                continue
            if auto_eligible and (float(read.get("detector_score", 0)) < .65 or
                                  float(read.get("ocr_score", 0)) < .80 or
                                  needs_manual_review(raw)):
                continue
            actual[raw] += 1
            latency = read.get("model_latency_ms")
            if latency is not None:
                model_latencies.append(float(latency))
        matches = expected & actual
        matched = sum(matches.values())
        true_positive += matched
        false_positive += sum((actual - expected).values())
        missed += sum((expected - actual).values())
        if expected and matched == sum(expected.values()):
            frame_hits += 1
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else None
    recall = true_positive / (true_positive + missed) if true_positive + missed else None
    return {
        "true_positive_plates": true_positive,
        "false_positive_reads": false_positive,
        "missed_plates": missed,
        "exact_plate_precision": round(precision, 4) if precision is not None else None,
        "exact_plate_recall": round(recall, 4) if recall is not None else None,
        "frames_with_all_expected_plates_read": frame_hits,
        "model_read_latency_ms_median": round(median(model_latencies), 2) if model_latencies else None,
        "model_read_latency_ms_p95": _percentile(model_latencies, .95),
    }


def evaluate_holdout(manifest: dict, predictions: dict, alerts: dict | None = None) -> dict:
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("An annotated manifest with at least one frame is required")
    if not manifest.get("dataset_id") or not manifest.get("source_mode"):
        raise ValueError("Manifest requires dataset_id and source_mode")
    ids = [frame.get("id") for frame in frames]
    if any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Frame IDs must be non-empty and unique")
    reads = predictions.get("frames")
    if not isinstance(reads, list):
        raise ValueError("Predictions require a frames array")
    by_id = {}
    for item in reads:
        if item.get("id") not in ids or item["id"] in by_id:
            raise ValueError("Prediction frame IDs must uniquely match manifest IDs")
        by_id[item["id"]] = item.get("reads", [])
    if set(by_id) != set(ids):
        raise ValueError("A prediction row is required for every annotated frame")
    raw = _score(frames, by_id)
    eligible = _score(frames, by_id, auto_eligible=True)
    conditions = sorted({str(tag) for frame in frames for tag in frame.get("conditions", [])})
    per_condition = {
        tag: _score([frame for frame in frames if tag in frame.get("conditions", [])], by_id)
        for tag in conditions
    }
    alert_latencies = []
    unverified_alerts = 0
    frame_by_id = {frame["id"]: frame for frame in frames}
    for alert in (alerts or {}).get("alerts", []):
        frame = frame_by_id.get(alert.get("frame_id"))
        if not frame:
            raise ValueError("Alert refers to an unknown annotated frame")
        origin = frame.get("event_utc_if_verified")
        if not origin:
            unverified_alerts += 1
            continue
        start = datetime.fromisoformat(origin)
        end = datetime.fromisoformat(alert["alert_created_utc"])
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Verified frame and alert times must have timezones")
        latency = (end - start).total_seconds() * 1000
        if latency < 0:
            raise ValueError("Alert timestamp precedes the verified frame timestamp")
        alert_latencies.append(latency)
    return {
        "dataset_id": manifest["dataset_id"],
        "source_mode": manifest["source_mode"],
        "frame_count": len(frames),
        "plate_count": sum(len(frame.get("plates", [])) for frame in frames),
        "raw_ocr": raw,
        "auto_eligible_single_reads": eligible,
        "conditions": per_condition,
        "verified_frame_to_alert_latency": {
            "count": len(alert_latencies), "unverified_excluded": unverified_alerts,
            "median_ms": round(median(alert_latencies), 2) if alert_latencies else None,
            "p95_ms": _percentile(alert_latencies, .95),
        },
        "interpretation": "Auto-eligible single reads meet prototype score/format gates; production alerts also require two concordant reads. No accuracy claim extends beyond this manifest.",
    }
