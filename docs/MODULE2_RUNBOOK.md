# Module 2: ANPR, evidence, representative watchlist, and alerts

## Status and limits

The local Module 2 path runs on decoded RTSP frames and persists plate sightings, evidence crops, and alerts. It uses a bounded latest-frame sampler and records source PTS, stream generation, raw OCR, confidence, model version, and a SHA-256 evidence hash. The real-model smoke test uses FastALPR's official sample image replayed over an owned localhost RTSP stream. It is **not** a Gujarat Government feed or an Indian-plate accuracy study. Sentinel access, an annotated Indian-road holdout set, false-positive/miss rates, and a multi-camera saturation test are still needed before claiming field performance.

## Install and start on Windows

Use Python 3.12, FFmpeg, Node, and the local MediaMTX fixture for integration tests. From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r backend/requirements-cpu.txt
npm ci --prefix frontend
npm run build --prefix frontend
$env:SAKHYAPATH_OPERATOR_KEY = 'replace-with-a-long-random-local-key'
.\.venv\Scripts\python -m uvicorn app.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` and sign in using the key **you set in your own shell**. This is a local prototype operator key, not a supplied Government credential. The first inference fetches the pinned detector and OCR models from their upstream model repositories into ignored `backend/data/models/`; make that cache available before an offline demonstration. Source URLs, evidence, and model files stay in ignored `backend/data/` by default.

On a Windows NVIDIA machine with a compatible CUDA/cuDNN runtime, install `backend/requirements-gpu.txt` in a **separate environment** instead of the CPU requirements. Set `SAKHYAPATH_CUDA_DLL_DIR` to the directory containing the installed CUDA/cuDNN DLLs if ONNX Runtime cannot locate them. The analysis status reports the **actual** provider used for detector and OCR, including CPU fallback. Do not install CPU and GPU ONNX Runtime wheels together.

The reproducible local smoke fixture requires the MediaMTX binary installed by `scripts/get-mediamtx.ps1`, FFmpeg on PATH, and FastALPR's official sample image at `backend/data/fastalpr_sample.png`. The latter is a test-only image and is not committed. Download that fixture from the [FastALPR repository](https://github.com/ankandrew/fast-alpr/blob/master/assets/test_image.png) when you want the real-model smoke test. The test skips when these are absent. Run:

```powershell
New-Item -ItemType Directory backend/data -Force | Out-Null
Invoke-WebRequest 'https://raw.githubusercontent.com/ankandrew/fast-alpr/master/assets/test_image.png' -OutFile backend/data/fastalpr_sample.png
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python scripts/create_synthetic_plate.py
.\.venv\Scripts\python scripts/benchmark_alpr.py backend/data/synthetic_indian_plate.png --runs 30
```

The generated Indian-style plate image is fully synthetic. It checks wiring and an OCR ambiguity, not accuracy in real Gujarat footage. Import an owned RTSP/HLS feed in the dashboard, select it, choose a sampling rate, and start analysis. Module 4 can change a running worker's rate, and the worker acknowledges it only after an analyzed frame at that rate. An operator must stop an active pursuit before manually changing its scheduled cameras. Analysis stays disabled until explicitly started, except for enabled cameras resumed on server restart.

## What the pipeline does

1. The Module 1 capture worker decodes the camera feed and publishes the newest `(camera_id, BGR frame, source_pts, pts_timebase, stream_generation, source_mode)` packet. Preview and analysis share that capture. A slow model never creates an unbounded frame queue: it skips intermediate decoded frames and increments `dropped`.
2. The sampler selects by **source PTS** when available, resets on reconnect or loop generation change, and uses arrival monotonic time only to pace untimed diagnostic frames. An untimed read cannot join the two-read confirmation streak. Source PTS is per-stream media time and is **not** cross-camera UTC. Sighting responses explicitly expose `event_utc_if_verified: null`, timestamp provenance, and unaligned-clock uncertainty until a verified mapping exists.
3. The pinned FastALPR detector `yolo-v9-t-384-license-plate-end2end` and OCR `cct-xs-v2-global-model` return raw text and confidence. Two temporally close, concordant reads with detector score at least 0.65 and OCR score at least 0.80 can confirm a sighting. These are prototype thresholds, not calibrated safety guarantees.
4. The store groups repeated same-plate reads within 45 seconds per camera and stream generation. It retains up to 20 raw reads, the strongest timed evidence crop, aligned PTS/receipt metadata, model version, and SHA-256. Evidence bytes are checked against the hash on retrieval. A mismatch or missing file returns an explicit error.
5. `GJ` strings that do not fit the expected district/series/digits positions remain review candidates even if the recognizer repeats them. In particular, `GJO1AB1234` is **not** silently treated as `GJ01AB1234`. Exact match against an active, unexpired representative watchlist entry creates an alert only for a confirmed sighting. The 60-second camera/plate/entry cooldown suppresses alert floods; acknowledgement is audited.
6. Sightings and alerts are committed before the authenticated server-sent event is published. The browser can reload and retrieve the same records from SQLite. Raw source URLs and evidence filesystem paths are excluded from API responses.

## Module 2 API

All endpoints except health and login require the local operator session. Mutations require its CSRF token.

| Endpoint | Meaning |
|---|---|
| `POST/GET/DELETE /api/v1/cameras/{id}/analysis` | Start, inspect counters/provider, or stop bounded sampling. |
| `GET /api/v1/sightings?plate=...&camera_id=...` | Search persisted candidate and confirmed sightings. |
| `GET /api/v1/sightings/{id}` | Inspect raw reads, confidence, camera, PTS, generation, and evidence hash. |
| `GET /api/v1/sightings/{id}/evidence.jpg` | Authenticated integrity-checked JPEG crop. |
| `GET/POST /api/v1/watchlist` | List/add representative plates; create supports UTC expiry. |
| `POST /api/v1/watchlist/{id}/disable` | Disable an entry without erasing its history. |
| `GET /api/v1/alerts` | Persisted exact-match alerts. |
| `GET /api/v1/alerts/stream` | Authenticated SSE for sightings, alerts, acknowledgements. |
| `POST /api/v1/alerts/{id}/acknowledge` | Acknowledge with an audit entry. |
| `GET /api/v1/alerts/{id}/history` | Audit trail for that alert. |

## Verification record, 28 September 2026

- **11 local tests passed** with the GPU runtime installed. They include decoded owned H.264/H.265 RTSP and HLS feeds, Sentinel catalogue stubs, the bounded sampler with a fixture recognizer, a real FastALPR RTSP frame-to-alert smoke test, evidence integrity, deduplication, an ambiguous `GJ` read, watchlist expiry/disable, and alert acknowledgement persistence. The real-model test is optional when its downloaded fixture is absent.
- On the actual **NVIDIA GeForce RTX 4060 Laptop GPU, 8,188 MiB**, the pinned pair reported `CUDAExecutionProvider` for both networks. Thirty repeated predictions of **one** official 518×331 sample gave a 16.9 ms median and 22 ms p95 inference time. CPU ONNX Runtime on the same sample gave 68.2 ms median and 119.5 ms p95. These figures exclude decode, queuing, network, and alert delivery; they are **not** multi-camera capacity or Indian-road accuracy measurements.
- A generated 1280×720 Indian-style test image containing `GJ01AB1234` was read as `GJO1AB1234`. This real observed O/0 error is kept as a review candidate by the Gujarat-format gate. One synthetic image cannot establish a miss rate or false-positive rate.
- `npm run build --prefix frontend` succeeded. The dashboard shows provider, selected/analyzed/dropped counts, evidence, representative watchlist, and alerts. Module 1's camera map, health, and preview remain available.

## Remaining acceptance work

- [ ] Obtain authorised Sentinel catalogue/feed access, then repeat actual feed decoding and analysis using the allowed paths. Record discovered, connected, analyzed, and concurrent camera counts separately.
- [ ] Build a labelled, permission-cleared Indian-plate holdout set spanning plate size, angle, lighting, weather, H.264/H.265 compression, and difficult O/0 cases. Report sample count, detections, false positives, misses, exact plate accuracy, and median/p95 **frame-to-alert** latency.
- [ ] Run sustained GPU plus decoder stress across multiple representative feeds and measure dropped frames, per-camera applied rate, memory, GPU/CPU use, and recovery. The current four-camera cap is a conservative prototype setting, **not** a measured capacity claim.
- [ ] Add Government-grade departmental authorization, secret encryption, approved retention, TLS, observability, backup/restore, and a regional worker/database architecture before real deployment. The current SQLite, single local operator, process-local capture, and in-memory sessions are prototype limits.

Module 3 should consume persisted sightings and preserve the distinction between source PTS, unverified receive time, and any future verified common UTC mapping. It must not infer a precise cross-camera route from this module's timestamps alone.
