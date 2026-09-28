# Sentinel live-only integration readiness

The organiser's reference says the camera grid is consumed **live**. It does not offer footage downloads or permission to copy Government video into this workspace. SakhyaPath can be checked against that protocol using locally generated live test streams; only the organiser can validate it against private cameras and vehicles. No Government footage is needed from the team or user for the checks below.

| Reference requirement | Local evidence | Boundary |
|---|---|---|
| Discover changing cameras and supplied URLs with read-only `GET /api/ingest` | Catalogue reconciliation and no-URL-leak tests in `tests/test_camera_grid.py` | Exact production JSON/auth remains unknown |
| RTSP over TCP; HLS when RTSP fails or opens without decoded frames | `tests/test_live_rtsp.py`, `tests/test_live_hls.py`, `tests/test_sentinel_preflight.py` | Tested with owned/local streams |
| Use decoded PTS, not reported FPS or arrival time | `backend/app/ingest/capture.py`, `tests/test_sentinel_capture_contract.py` | Cross-camera UTC mapping remains unverified |
| Tolerate varying frame intervals, join warnings and loop cuts | `tests/test_sentinel_capture_contract.py` | Real scene and codec mix remains untested |
| Reconnect with bounded backoff and close unused captures | `tests/test_live_rtsp.py`, `backend/app/ingest/capture.py` | Network and gateway behavior remains untested |
| H.264, H.265 and different resolutions | Owned RTSP/HLS integration tests | Real camera mix remains untested |
| Do not call control API, publish, seek or download | Adapter performs catalogue GET; capture consumes returned RTSP/HLS URLs | Inspect deployment configuration before live evaluation |

The browser uses an authenticated server-managed JPEG preview. The WHEP URL is retained from the catalogue but direct WHEP playback is not currently implemented; the guide calls WHEP a low-latency preview option, not the inference transport.

## Evaluator-side live sequence

1. Organiser supplies the authorised catalogue origin/authentication through its private channel and confirms whether plate crops, metadata, screenshots and reports may be retained or exported. Never put credentials or raw URLs into a submission file.
2. Run `python scripts/sentinel_preflight.py`. Its default output is `backend/data/sentinel_preflight.json`, an ignored local path. It reports counts and codec/resolution mix without stream URLs or camera IDs. The tracked `output/benchmarks/sentinel_preflight.json` is only the earlier **pending-access** record.
3. Sync the app against `GET /api/ingest`, then choose exact IDs shown in the authenticated registry. Probe one authorised H.264 and one H.265 feed if available. Record decoded frame/PTS counts and RTSP/HLS fallback, without downloading a recording.
4. Use the organiser's privately presented target registration to run watchlist, search, route and alert workflows live. Record discovered, connected, viewed and concurrently analysed counts separately. Treat a cross-camera route as approximate unless the organiser verifies shared UTC alignment.
5. Let evaluators inspect the UI and derived timestamped report under their policy. Record or export Government images/video only if expressly permitted. If retention is disallowed, use the live demonstration and ask the organiser which redacted or metadata-only evidence it accepts. The current prototype stores plate crops during analysis, so confirm that permission **before enabling analysis on Government feeds**.

Offline tests establish protocol readiness, not a successful Government integration, Indian-plate accuracy, or an evaluation outcome.
