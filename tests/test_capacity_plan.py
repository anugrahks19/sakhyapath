from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from capacity_plan import size_scenario


def test_capacity_equations_keep_registry_separate_from_active_feeds():
    result = size_scenario(registered=80000, active_fraction=.05, sample_fps=1,
                           bitrate_mbps=2, worker_budget_fps=8.447,
                           events_per_camera_day=2, crop_kib=100,
                           retention_days=30)
    assert result["concurrent_analyzed_cameras"] == 4000
    assert result["total_analyzed_fps"] == 4000
    assert result["illustrative_base_workers_at_same_performance"] == 474
    assert result["active_feed_ingress_gbps"] == 8
    assert result["unreplicated_evidence_gib"] > 0
