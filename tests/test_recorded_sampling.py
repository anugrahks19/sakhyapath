from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compare_recorded_sampling import compare_scenario


def test_recorded_comparison_uses_equal_cap_and_real_policy():
    frames = []
    for camera in ("east", "west"):
        for tenth in range(100):
            at = tenth / 10
            visible = camera == "east" and 1.1 <= at <= 2.5
            frames.append({"camera_id": camera, "timeline_seconds": at,
                           "target_visible": visible,
                           "model_reads": ["GJ01AB1234"] if visible else []})
    scenario = {"scenario_id": "controlled", "source_mode": "owned_replay",
                "clock_basis": "verified_common_timeline", "duration_seconds": 10,
                "budget_fps": 3, "target_plate": "GJ01AB1234",
                "ranked_camera_ids": ["east", "west"], "frames": frames}
    result = compare_scenario(scenario)
    assert result["uniform"]["frame_budget"] == result["active_pursuit"]["frame_budget"] == 30
    assert result["uniform"]["frames_analyzed"] <= 30
    assert result["active_pursuit"]["frames_analyzed"] <= 30
    assert result["active_pursuit"]["requested_rates_fps"]["east"] > result["uniform"]["requested_rates_fps"]["east"]
    with pytest.raises(ValueError, match="verified common timeline"):
        compare_scenario({**scenario, "clock_basis": "receive_time_only"})
