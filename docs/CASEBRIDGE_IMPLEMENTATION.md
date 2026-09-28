# SakhyaPath CaseBridge implementation and demo log

**Status:** Implemented and locally tested on 29 September 2026. This is an internal police-case workflow on top of the existing camera grid, sighting review, pursuit and Search Proof services. Deployment status must be recorded separately. It has not been connected to eGujCop/VAHAN or tested with organiser footage.

## The officer workflow

1. **Open a case:** An operator records a case reference, hit-and-run or stolen-vehicle type, urgency, lead department, incident location/time, exact plate or partial fragment, optional end of search window, and witness vehicle description. Partial plate search is explicitly labelled triage. Duplicate references are rejected. Case records live in SQLite and survive restarts.
2. **Review real observations:** CaseBridge uses the existing evidence journey search and hash check. It shows confirmed, hash-verified reads separately from candidates. A partial match is never promoted automatically. Rejected reads are excluded. Reads outside the incident-to-end window are excluded. The search currently examines at most 5,000 recent records; the UI and API disclose when that bound is hit.
3. **Plan around blind spots:** The case lists nearby registered cameras, their decoded-frame health, unavailable/unverified feeds, and online geographic alternatives. These are camera-proximity suggestions, not verified road routes, actual field of view, or proof a vehicle passed a location. The recipient handoff packet includes up to three recipient-department cameras ordered by online health and straight-line distance from the last confirmed sighting.
4. **Context and pursuit:** A stolen-vehicle case with an exact plate can add a clearly labelled *representative* watchlist entry via the existing endpoint. Matching alerts are shown in the case. After selecting a confirmed, hash-verified sighting, an operator can link the case to the existing pursuit engine. Starting adaptive sampling still requires that engine's measured capacity benchmark and worker limits; CaseBridge does not bypass those checks.
5. **District handoff:** An operator selects a recipient department with at least one registered camera and one matching confirmed, hash-verified sighting. The application queues a metadata-only packet in its internal SQLite inbox. It contains the case reference, plate, description, last sighting ID/camera/time/evidence hash, timestamp uncertainty and camera suggestions. It contains no raw video or stream URL. A reviewer signed in with **that department's separate key** can read and acknowledge it. Other departments cannot access that inbox or acknowledge it. Every action is recorded. This is **not** external dispatch, SMS, email, or eGujCop integration.
6. **Shift briefing and timeline:** The operator dashboard summarizes each open case's last confirmed sighting, pending handoffs and nearby camera gaps. Notes, acknowledgements and closure are append-only case events. An operator can create an immutable JSON case-timeline snapshot signed with the existing persistent Ed25519 Search Proof key. The API can verify a stored snapshot. A later case change requires a new snapshot; signatures do not re-check later evidence or reconstruct a missing video.

## Architecture and boundaries

- New service: `backend/app/services/casebridge.py`; schema: `backend/app/schemas.py`; versioned API: `backend/app/main.py`; React panel: `frontend/src/CaseBridgePanel.jsx` and light-theme CSS.
- New tables: `police_cases`, `case_handoffs`, `case_events`, `case_timeline_snapshots`. Existing camera, sighting, review, watchlist, pursuit, alert, and proof tables remain unchanged.
- Existing session cookies and CSRF protect the API. Operator-only case detail and writes; department-scoped recipient inbox and acknowledgement. The shared-key authentication model remains a prototype limit.
- The handoff is a local database state transition. The recipient must log into the same installation using a configured `SAKHYAPATH_DEPARTMENT_KEYS` entry. In production, replace that with approved police identity and a secure durable cross-district message service.
- A case stores only plate queries and permitted metadata. Official stolen-vehicle context requires an authorised connector; no official FIR/VAHAN lookup is claimed.
- Current partial search scans up to 5,000 recent sightings and shift briefing recomputes evidence for open cases. Move to indexed search, pagination, PostgreSQL/PostGIS and regional event workers for statewide scale. Camera suggestions need validated field of view, direction, road graph and clock trust before becoming route recommendations.

## Demo steps on owned footage

1. Register two or three owned cameras with distinct department labels; configure distinct department sign-in keys for a local demo. Keep source mode `owned_replay` if replaying a recording.
2. Record a representative exact plate in the existing watchlist; start analysis. Open a CaseBridge incident with that plate and a search window covering the test video.
3. Show a candidate OCR read first. The handoff action must be blocked. After a confirmed read with a verified evidence hash, show the case's confirmed list and matching representative alert.
4. Add one unavailable/unverified camera and show it as a gap. Show nearby online alternatives as geographic suggestions with the road-visibility caveat.
5. Queue a handoff to the second department. Sign out and sign in with its department key, acknowledge the packet, then sign in as operator. The shift briefing should show zero pending handoffs and the action history should include acknowledgement.
6. Link the confirmed sighting to a pursuit. Run the existing measured benchmark first, then start its adaptive schedule; show actual applied frame rates and coverage in the Journey panel.
7. Sign and download the case timeline. `SearchProof.verify(envelope)` checks the exported JSON envelope; changing one byte of its payload fails verification. Keep the older signed Search Proof receipt as the sampled-video coverage artifact.

## Verification performed

- `tests/test_casebridge.py`: case creation and restart persistence; duplicate reference and invalid time-window rejection; candidate gating; partial-query triage; confirmed and hash-verified handoff; recipient-only inbox/acknowledgement; pursuit attachment; representative watchlist context; shift briefing; signed timeline verification; old and tampered evidence denied.
- The full backend suite passed **31 tests** after the final time-window and camera-suggestion changes; the CaseBridge suite passed **3 tests**.
- `npm run build` passed after the final UI edits. `git diff --check` reported no whitespace errors.

**Presentation claim:** “SakhyaPath connects a confirmed camera sighting to an auditable case, identifies nearby camera gaps, queues a scoped internal district handoff, and preserves a signed snapshot of the actions. Official police-database and field-dispatch integrations remain approval-gated.”
