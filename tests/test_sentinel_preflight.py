from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

import av

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from sentinel_preflight import probe_camera, summarize_catalogue


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
    assert "A-42" not in str(result)


def test_probe_falls_back_when_rtsp_opens_without_frames(monkeypatch):
    class Packet:
        def __init__(self, frames):
            self.frames = frames

        def decode(self):
            return self.frames

    class Frame:
        pts = 90000
        time_base = Fraction(1, 90000)

    class Container:
        def __init__(self, frames):
            self.frames = frames

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def demux(self, *, video):
            assert video == 0
            return iter([Packet(self.frames)])

    def fake_open(url, **_kwargs):
        return Container([] if url.startswith("rtsp://") else [Frame()])

    monkeypatch.setattr(av, "open", fake_open)
    result = probe_camera({"camera_id": "A-42", "rtsp_url": "rtsp://test/stream",
                           "hls_url": "http://test/live", "codec": "H.265",
                           "width": 1920, "height": 1080}, duration=5)
    assert result["status"] == "decoded"
    assert result["transport"] == "hls"
    assert result["pts_frames"] == 1
    assert result["fallback_failures"] == [
        {"transport": "rtsp_tcp", "error_type": "NoDecodedFrame"}]
