from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from sentinel_preflight import summarize_catalogue


def test_preflight_summary_never_exposes_catalogue_urls():
    result = summarize_catalogue([{
        "camera_id": "A-42", "catalogue_live": True, "codec": "H.265",
        "width": 1920, "height": 1080,
        "rtsp_url": "rtsp://secret.invalid/user:password@feed",
        "hls_url": "https://secret.invalid/live.m3u8",
    }])
    assert result["discovered"] == result["rtsp_available"] == result["hls_available"] == 1
    assert result["codecs"] == {"H.265": 1}
    assert result["resolutions"] == {"1920x1080": 1}
    assert "secret.invalid" not in str(result)
