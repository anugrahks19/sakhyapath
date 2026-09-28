from __future__ import annotations

import pytest

from app.evaluation import evaluate_holdout


def test_holdout_counts_misses_false_reads_and_only_verified_alert_latency():
    manifest = {"dataset_id": "controlled-test", "source_mode": "owned_replay", "frames": [
        {"id": "day", "plates": ["GJ01AB1234"], "conditions": ["day"],
         "event_utc_if_verified": "2026-09-28T00:00:00+00:00"},
        {"id": "night", "plates": ["GJ02CD5678"], "conditions": ["night"]},
        {"id": "blank", "plates": [], "conditions": ["night"]},
    ]}
    predictions = {"frames": [
        {"id": "day", "reads": [{"plate": "GJ01AB1234", "detector_score": .96,
                                  "ocr_score": .92}]},
        {"id": "night", "reads": [{"plate": "GJO2CD5678", "detector_score": .8,
                                    "ocr_score": .85}]},
        {"id": "blank", "reads": [{"plate": "FALSE123", "detector_score": .8,
                                    "ocr_score": .85}]},
    ]}
    alerts = {"alerts": [
        {"frame_id": "day", "alert_created_utc": "2026-09-28T00:00:00.250+00:00"},
        {"frame_id": "night", "alert_created_utc": "2026-09-28T00:00:01+00:00"},
    ]}
    result = evaluate_holdout(manifest, predictions, alerts)
    assert result["raw_ocr"]["true_positive_plates"] == 1
    assert result["raw_ocr"]["false_positive_reads"] == 2
    assert result["raw_ocr"]["missed_plates"] == 1
    assert result["auto_eligible_single_reads"]["false_positive_reads"] == 1
    assert result["conditions"]["night"]["missed_plates"] == 1
    assert result["verified_frame_to_alert_latency"] == {
        "count": 1, "unverified_excluded": 1, "median_ms": 250.0, "p95_ms": 250.0,
    }


def test_holdout_rejects_empty_or_unmatched_manifest():
    with pytest.raises(ValueError, match="at least one frame"):
        evaluate_holdout({"dataset_id": "x", "source_mode": "owned_replay", "frames": []},
                         {"frames": []})
    with pytest.raises(ValueError, match="prediction row"):
        evaluate_holdout({"dataset_id": "x", "source_mode": "owned_replay",
                          "frames": [{"id": "f", "plates": []}]}, {"frames": []})
