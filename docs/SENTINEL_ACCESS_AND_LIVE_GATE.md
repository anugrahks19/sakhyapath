# Sentinel access and authorised live-feed gate

The user-supplied [Sentinel reference](../sentinel_source_index/README.md) specifies a read-only `GET /api/ingest` catalogue and live RTSP, WHEP and HLS endpoints. Exact IDs and URLs must come from that catalogue. Its text does not grant this workspace access, give a real origin, or establish a cross-camera UTC clock.

## Account activation

Send the support team your registered email, team/application ID and the screenshot saying the account is not on the approved list. Ask for account approval, the authorised **catalogue origin** and authentication method, permitted feed use, network/port restrictions, and who to contact about failures. Do not include passwords or stream URLs in the email. Access approval and credentials must come through the organiser's approved channel; this project cannot self-approve an account.

Suggested email for the organiser's published support address:

> **Subject:** Sentinel sandbox access activation for SakhyaPath hackathon team  
> Hello Sentinel support, our Gujarat CCTV Hackathon team is registered under **[registered email]**, team/application ID **[ID]**. The portal reports that this email is not yet on the approved access list (screenshot attached). Please activate the account and confirm the authorised `GET /api/ingest` catalogue origin, authentication method, permitted feed use, and any VPN, IP allowlist or port requirements. We will use the read-only catalogue and authorised live feeds for the evaluation; please also share the private channel for reporting camera failures. Thank you, **[name and team]**.

## Preflight after approval

1. Set `SAKHYAPATH_SENTINEL_BASE_URL` to the organiser-supplied origin only, without `/api/ingest`. Set `SAKHYAPATH_SENTINEL_AUTHORIZATION` only if the organiser supplies an Authorization header. Keep both in local environment variables or an approved secret manager; never commit them.
2. Run `python scripts/sentinel_preflight.py`. It performs only `GET /api/ingest` and writes a URL-free summary to `output/benchmarks/sentinel_preflight.json`: discovered/live-claimed counts, codecs, resolutions and available transport counts.
3. Choose an exact camera ID from that result and run `python scripts/sentinel_preflight.py --probe-camera <id> --duration 12`. The optional probe decodes a short live interval over RTSP/TCP, falls back to HLS, records frame/PTS counts, then closes the stream. It does not seek or download footage. Do not probe all cameras at once.
4. Start the local app with the same approved environment, sign in, select **Sync Sentinel**, then inspect `GET /api/v1/metrics` as operator. Record registered, `sentinel_discovered`, decoded online, connected, viewed and concurrently analyzed separately. These numbers have different meanings.
5. Test the smallest permitted mixed-codec set, interruption/reconnect, decoder warm-up, changing catalogue IDs/properties and idle closure. Run the authorised ~50-feed evaluation only within portal terms. Save CPU/GPU/RAM/network, p95 **frame-to-alert** latency if event UTC is verified, errors and recovery evidence. A p95 model inference number alone is not frame-to-alert latency.

## Camera or feed failure report

The supplied reference asks for camera ID, exact URL, client/version, UTC timestamp and client error log. Check the catalogue live claim first. Share the exact URL only through the organiser's approved private support channel; SakhyaPath's preflight output omits it by design. Record whether TCP 8554 failed and whether HLS succeeded. Never publish to the Sentinel gateway or call its control API.

## Gate result

Until an authorised run has produced a decoded Government frame and an evidence-backed sighting/report, mark the Government integration and demo **pending**. Owned replay, a mocked catalogue and the local benchmark cannot close this gate.
