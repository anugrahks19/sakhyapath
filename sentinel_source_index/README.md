# Sentinel sandbox integration reference: indexed copy

This index records the user-supplied **“Consuming the Sentinel Camera Grid”** text as source material for SakhyaPath. It is a reference about the sandbox, not an instruction to access the portal or operate its feeds now. The copied text is preserved byte-for-byte in [`Sentinel_reference.txt`](Sentinel_reference.txt). [`Sentinel_reference_lines.tsv`](Sentinel_reference_lines.tsv) provides all **93 lines**, including blank lines, with source line numbers. [`Sentinel_reference_full.json`](Sentinel_reference_full.json) contains the same lines, source path, byte length, and SHA-256 for integrity. Run `python index_sentinel.py "<source-text-path>"` to regenerate the records.

## Topic lookup

| Topic | Source lines | What the reference says |
|---|---:|---|
| Nature of feeds | 1–6 | Live RTP/RTSP; approximately real-time delivery; monotonic presentation timestamps (PTS); no seek, byte-range retrieval, or accelerated playback on the live feeds. |
| Endpoints | 8–15 | RTSP for inference, WebRTC/WHEP for low-latency preview, HLS for dashboards/restricted networks. Discover exact URLs, IDs, properties, and live status through read-only `GET /api/ingest`; do not construct endpoints from a fixed ID pattern. |
| Client examples | 17–39 | OpenCV, GStreamer, FFmpeg/ffprobe, and NVIDIA DeepStream examples; select H.264 or H.265 depay/parser components as appropriate. |
| TCP and HLS fallback | 41–43, 76–77 | Force RTSP-over-TCP; use HLS if port 8554 is blocked. |
| Reliable timebase | 45–53, 78–80 | Do not use reported FPS or read-arrival wall clock for motion/tracking timing. Use frame PTS/RTP timestamps and actual PTS deltas. Initial GOP replay may arrive faster than real time; frame intervals vary. |
| Reconnection and decoding | 55–59, 81–83 | Reconnect with exponential backoff around 2–30 seconds. Initial decoder warnings before the first IDR can self-resolve and should not immediately abort the feed. |
| Heterogeneous cameras | 61–62, 84–87 | Read codec, resolution, bitrate, and other stream properties per camera from the catalogue; size buffers, decoders, and inference accordingly. |
| Loop discontinuities | 64–65, 88 | Feeds loop; reset or recover persistent tracker/background/re-identification state on an abrupt scene cut. |
| Footage access | 67–68 | Consume the feed live; no complete footage download. The browser `/stream/<id>` fallback may answer range requests, so a simple `curl`/`wget` result can be an incomplete file. |
| Gateway use and load | 70–74 | Consume only; do not publish to Sentinel paths or call **Sentinel's** control API. Each client receives a copy; open only actively processed cameras and close unused captures. |
| Support report | 89–90 | Include camera ID, exact URL, client/version, UTC timestamp, and client error log; check `/api/ingest` live status first. |
| Portal labels | 92–93 | The text labels the Sentinel Gujarat Live Portal as an official Gujarat Police sandbox feed; this index has not independently verified that claim. |

## SakhyaPath integration decisions

1. The Sentinel source adapter must first call `GET /api/ingest`, then store the returned camera identifiers, locations, live status, codec, stream properties, and provided URLs in the Model 1 registry. Refresh the catalogue because cameras and IDs may change. The catalogue is the source of truth, while registry history preserves prior observations.
2. Consume the returned RTSP URL over TCP for inference. The web viewer can use the returned WHEP or HLS URL, subject to the portal's access controls. If RTSP is blocked, use HLS with its higher/variable latency recorded in the coverage ledger.
3. Carry the source PTS and its provenance through decoding, ANPR, tracking, sightings, and the evidence graph. Treat arrival time only as an operational diagnostic. Handle irregular frame intervals, initial GOP replay, reconnects, decoder warm-up, and loop cuts explicitly.
4. **Open question:** monotonic PTS on individual feeds is not, by itself, a shared UTC clock across cameras. The source does not specify a PTS-to-UTC mapping. A cross-camera chronology and a UTC report need a verified common timebase or calibrated mapping; otherwise show timestamp provenance and uncertainty rather than claim precise global event time.
5. Use `GET /api/ingest` as a **read-only catalogue API**. Do not call Sentinel's control API, publish a stream back to it, or attempt to download the looping footage as a file. Any MediaMTX instance under our own control is a separate component, but it must not add unnecessary camera connections or violate sandbox access conditions.
6. The earlier form draft mentioned a “MediaMTX Control API.” That would be accurate only for **our own** relay if deployed and used; it is **not** an API to use on Sentinel. For the Sentinel integration, the API to name is `GET /api/ingest`.

## Pre-submission verification

- Catalogue discovery and refresh work when a camera ID, live status, or stream property changes.
- RTSP uses TCP; HLS fallback is tested if relevant.
- PTS drives frame intervals; declared FPS and bursty frame arrival do not affect motion or route calculations.
- Capture survives a feed restart using bounded exponential backoff and tolerates join-time decoder warnings.
- Mixed H.264/H.265, resolution changes, and loop cuts do not corrupt camera/tracker state.
- Active Pursuit opens only relevant streams and closes idle ones; load is measured.
- A sighting/report discloses its source timestamp and any uncertainty in cross-camera alignment.

The source reference's rules are recorded faithfully here. They do not establish that an implementation or a portal connection has been tested yet.
