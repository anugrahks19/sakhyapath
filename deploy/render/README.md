# Fastest managed, always-on SakhyaPath demo: paid Render web service

This deploys **the whole React + FastAPI prototype as one service and one HTTPS URL**. Render builds the image from [`Dockerfile`](Dockerfile), runs one Uvicorn process, and mounts a persistent disk for SQLite, evidence, model cache and the Search Proof signing key. You do **not** need Vercel or an Oracle VM for this option.

**Use a paid instance with a persistent disk.** Render's [Free service sleeps after 15 minutes and loses local files on restart](https://render.com/docs/free). Paid services remain active, and [persistent disks](https://render.com/docs/disks) preserve local files. The current [compute plans](https://render.com/docs/compute-plans) include a 2 CPU / 4 GB RAM option; start there for a **one-feed CPU demo**, then measure actual inference and increase resources if necessary. This is not a GPU service or a Government-scale deployment. No provider promises literally zero downtime; monitor the link and keep a backup video for submission.

## Setup in the Render dashboard

1. Commit the current tested source to a private Git repository you control. `backend/data/`, `.env`, model files, camera URLs and evidence must stay out of Git. The working tree currently contains uncommitted changes, so commit the intended state before connecting Render.
2. Create a **Web Service** from that repository. Select **Docker** runtime and set **Dockerfile Path** to `deploy/render/Dockerfile`. Keep the repository root as the build context; the Dockerfile copies both `frontend/` and `backend/`.
3. Choose a **paid, always-on** plan with enough RAM. Start at 4 GB for one owned feed, but regard that as a trial configuration until model, decoder, RAM and frame-to-alert latency are measured on Render.
4. Attach a **persistent disk mounted at `/var/lib/sakhyapath`**. Choose enough space for model cache, demo evidence and database; monitor used space. All four application data paths in the Dockerfile are under this mount. [Only mounted paths persist](https://render.com/docs/disks).
5. In Environment settings, add `SAKHYAPATH_OPERATOR_KEY` as a long random secret, and confirm `SAKHYAPATH_COOKIE_SECURE=1`. The container already sets database/evidence/models/proof-key paths and a conservative two-camera analysis cap. Do not set Sentinel origin/auth unless the organiser authorises this public-cloud deployment and its evidence policy.
6. Deploy. Render provides an HTTPS service URL. Once live, open `/api/v1/health`, sign in, and import an **owned feed reachable from Render's network**. A laptop's `127.0.0.1` feed is not reachable from Render. Let the model cache warm before recording the demo.
7. Run the [operational demo checklist](../../docs/DEMO_AND_LINK_CHECKLIST.md): real decoded preview, PTS, one actual plate read and alert, journey, pursuit/coverage, signed Search Proof, restart persistence, and an incognito link test. Record the separate 2-3 minute own-feed video.

## The limits of this option

- The service runs a single process because sessions, capture and pursuit are process-local. Do not add multiple workers or replicas to this prototype.
- Render's persistent disk is attached to one service instance; it does not make the app a distributed system.
- This CPU image may decode and recognize **one low-rate owned feed** if the chosen plan is adequate; benchmark it. If recognition is too slow, either choose a suitable GPU VM for the full demo or use the hosted site for inspection with a separately recorded real own-feed AI demo. Never present manually inserted sightings as live model output.
- Camera URLs imported by an authenticated operator can make the server connect outward. Use a strong key, share it only with judges through an approved private channel, and import only controlled sources. The current shared-key login is a hackathon prototype, not public production identity.
- If the organiser's private streams are network restricted, the Render service may not be allowed to access them. Keep Government-feed evaluation inside the authorised environment.
- Back up **the SQLite file, evidence, and Ed25519 signing key together**. The paid disk preserves files across normal redeploys; it is not a substitute for a tested backup and restore process.

## Local verification boundary

The Dockerfile has been reviewed against the pinned Python/Node dependencies and the backend's static `frontend/dist` path. It has **not** been built on this Windows host because Docker is unavailable here, and it has not been run on Render. Treat first image build, model download, cookie/session behavior and one-feed inference as deployment acceptance gates before submitting its URL.
