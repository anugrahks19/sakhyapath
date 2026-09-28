"""HTTP smoke test for an isolated SakhyaPath instance with disposable data.

Run only against a throwaway database. This script imports one owned replay
camera and creates a search and receipt; it never opens the dummy stream.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.proof import SearchProof  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--allow-test-data", action="store_true", required=True)
    args = parser.parse_args()
    key = os.getenv("SAKHYAPATH_OPERATOR_KEY")
    if not key:
        raise SystemExit("Set SAKHYAPATH_OPERATOR_KEY in this shell")
    camera_id = "owned-verification-" + uuid.uuid4().hex[:10]
    with httpx.Client(base_url=args.base_url, timeout=10) as client:
        def request(method: str, path: str, **kwargs) -> httpx.Response:
            response = client.request(method, "/api/v1" + path, **kwargs)
            response.raise_for_status()
            return response
        assert request("GET", "/health").json()["status"] == "ok"
        assert client.get("/").status_code == 200
        login = request("POST", "/auth/login", json={"operator_key": key}).json()
        headers = {"X-CSRF-Token": login["csrf_token"]}
        request("POST", "/cameras/import", headers=headers, json=[{
            "camera_id": camera_id, "display_name": "Owned verification source",
            "department": "Owned verification", "latitude": 23.0,
            "longitude": 72.5, "source_mode": "owned_replay",
            "hls_url": "http://127.0.0.1:9/owned-verification.m3u8",
        }])
        listed = request("GET", "/cameras").json()
        assert any(row["camera_id"] == camera_id for row in listed)
        assert "owned-verification.m3u8" not in json.dumps(listed)
        trust = request("GET", f"/cameras/{camera_id}/trust").json()
        assert trust["cross_camera_travel_time"] == "blocked_approximate_only"
        pursuit = request("POST", "/pursuits", headers=headers,
                          json={"plate": "GJ01AB1234"}).json()
        pursuit_id = pursuit["id"]
        journey = request("GET", f"/pursuits/{pursuit_id}/journey").json()
        assert journey["counts"]["observations"] == 0
        shadow = request("GET", f"/pursuits/{pursuit_id}/shadow").json()
        assert shadow["decisions"] == []
        proof = request("POST", f"/pursuits/{pursuit_id}/proofs",
                        headers=headers).json()
        proof_id = proof["payload"]["receipt_id"]
        exported = request("GET", f"/proofs/{proof_id}.json").json()
        pdf = request("GET", f"/proofs/{proof_id}.pdf").content
        assert SearchProof.verify(exported)
        assert SearchProof.verify_pdf(pdf, exported)
        assert request("GET", f"/proofs/{proof_id}/verify").json()["signature_valid"]
        assert "owned-verification.m3u8" not in json.dumps(exported)
        federated = request("POST", "/federation/search", headers=headers,
                            json={"plate": "GJ01AB1234"}).json()
        assert federated["regions_queried"] == 0 and not federated["complete"]
        events = request("GET", "/regions/events").json()
        assert events["open_delivered_gaps"] == []
        request("POST", "/auth/logout", headers=headers)
    print(json.dumps({"result": "PASS", "camera_id": camera_id,
                      "pursuit_id": pursuit_id, "proof_id": proof_id,
                      "checks": ["HTTP startup/static", "auth/CSRF", "camera registry",
                                 "clock trust", "journey", "shadow standby",
                                 "signed JSON/PDF", "unconfigured federation honesty",
                                 "region event view", "logout"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
