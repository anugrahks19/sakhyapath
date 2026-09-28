"""Read-only Sentinel catalogue and optional short live-frame preflight.

The command never prints or saves feed URLs or Authorization headers.
It never calls Sentinel's control API or downloads a recording.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ingest.catalogue import SentinelCatalogue  # noqa: E402


def summarize_catalogue(cameras: list[dict]) -> dict:
    return {
        "discovered": len(cameras),
        "catalogue_live_claimed": sum(camera.get("catalogue_live") is True for camera in cameras),
        "rtsp_available": sum(bool(camera.get("rtsp_url")) for camera in cameras),
        "hls_available": sum(bool(camera.get("hls_url")) for camera in cameras),
        "codecs": dict(sorted(Counter(str(camera.get("codec") or "unknown")
                                      for camera in cameras).items())),
        "resolutions": dict(sorted(Counter(
            f"{camera['width']}x{camera['height']}" if camera.get("width") and camera.get("height")
            else "unknown" for camera in cameras).items())),
        "camera_ids": [camera["camera_id"] for camera in cameras],
    }


def probe_camera(camera: dict, duration: float) -> dict:
    import av

    av.logging.set_level(av.logging.PANIC)
    attempts = [("rtsp_tcp", camera.get("rtsp_url"), {"rtsp_transport": "tcp"}),
                ("hls", camera.get("hls_url"), {})]
    failures = []
    for transport, url, options in attempts:
        if not url:
            continue
        count = 0
        pts_values: list[float] = []
        started = time.monotonic()
        try:
            with av.open(url, options=options, timeout=(5.0, 5.0)) as container:
                for frame in container.decode(video=0):
                    if frame.pts is not None and frame.time_base is not None:
                        pts_values.append(float(frame.pts * frame.time_base))
                    count += 1
                    if time.monotonic() - started >= duration:
                        break
            deltas = [later - earlier for earlier, later in zip(pts_values, pts_values[1:])
                      if later > earlier]
            return {"status": "decoded" if count else "no_decoded_frame",
                    "camera_id": camera["camera_id"], "transport": transport,
                    "duration_seconds": round(time.monotonic() - started, 3),
                    "decoded_frames": count, "pts_frames": len(pts_values),
                    "median_pts_interval_seconds": sorted(deltas)[len(deltas) // 2] if deltas else None,
                    "codec": camera.get("codec"), "resolution": (
                        f"{camera.get('width')}x{camera.get('height')}"),
                    "fallback_failures": failures}
        except Exception as error:
            failures.append({"transport": transport, "error_type": type(error).__name__})
    return {"status": "unavailable", "camera_id": camera["camera_id"],
            "fallback_failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-camera", help="Exact ID returned by the catalogue")
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "output/benchmarks/sentinel_preflight.json")
    args = parser.parse_args()
    if args.duration < 5 or args.duration > 60:
        parser.error("Probe duration must be between 5 and 60 seconds")
    origin = os.getenv("SAKHYAPATH_SENTINEL_BASE_URL")
    result = {"checked_utc": datetime.now(timezone.utc).isoformat(),
              "catalogue_method": "GET /api/ingest", "source_system": "sentinel"}
    if not origin:
        result.update(status="pending_access", action=(
            "Obtain organiser-approved catalogue origin and authentication; set local environment variables."))
    else:
        try:
            adapter = SentinelCatalogue(origin, os.getenv("SAKHYAPATH_SENTINEL_AUTHORIZATION"))
            cameras = adapter.fetch()
            result.update(status="catalogue_connected", catalogue=summarize_catalogue(cameras))
            if args.probe_camera:
                camera = next((item for item in cameras
                               if item["camera_id"] == args.probe_camera), None)
                if camera is None:
                    raise ValueError("Requested camera ID is absent from the live catalogue")
                result["probe"] = probe_camera(camera, args.duration)
        except Exception as error:
            # Never print exception text: remote clients may include a URL or token in it.
            result.update(status="failed", error_type=type(error).__name__)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
