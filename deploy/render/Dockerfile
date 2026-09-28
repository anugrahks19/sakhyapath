# Single-process SakhyaPath demo image for an x86_64 CPU Render web service.
# Live AI throughput must be measured on the chosen paid instance.
FROM node:24-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 libgomp1 gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --home-dir /home/sakhyapath sakhyapath
COPY backend/requirements.txt backend/requirements-cpu.txt /app/backend/
RUN python -m pip install --upgrade pip \
    && python -m pip install -r backend/requirements-cpu.txt
COPY backend/app/ /app/backend/app/
COPY --from=frontend-build /build/frontend/dist/ /app/frontend/dist/
RUN mkdir -p /var/lib/sakhyapath/evidence /var/lib/sakhyapath/models \
    && chown -R sakhyapath:sakhyapath /var/lib/sakhyapath /home/sakhyapath
ENV SAKHYAPATH_DB=/var/lib/sakhyapath/sakhyapath.sqlite3 \
    SAKHYAPATH_EVIDENCE_DIR=/var/lib/sakhyapath/evidence \
    SAKHYAPATH_MODELS_DIR=/var/lib/sakhyapath/models \
    SAKHYAPATH_PROOF_KEY_PATH=/var/lib/sakhyapath/proof_signing_ed25519.pem \
    SAKHYAPATH_COOKIE_SECURE=1 \
    SAKHYAPATH_ANALYTICS_MAX_CAMERAS=2
CMD ["sh", "-c", "mkdir -p /var/lib/sakhyapath/evidence /var/lib/sakhyapath/models && chown sakhyapath:sakhyapath /var/lib/sakhyapath /var/lib/sakhyapath/evidence /var/lib/sakhyapath/models && exec gosu sakhyapath python -m uvicorn app.main:create_app --factory --app-dir backend --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
