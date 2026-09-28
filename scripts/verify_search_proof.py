"""Verify an exported Search Proof against a pinned public key.

Usage: python scripts/verify_search_proof.py receipt.json --public-key HEX [--pdf receipt.pdf]
Get the public key from the authenticated server over approved TLS and pin it separately.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.proof import SearchProof  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--public-key", required=True, help="Pinned Ed25519 public key hex")
    parser.add_argument("--pdf", type=Path, help="Matching signed PDF receipt")
    args = parser.parse_args()
    envelope = json.loads(args.receipt.read_text(encoding="utf-8"))
    if envelope.get("public_key_hex") != args.public_key.lower():
        print("FAIL: signing key does not match trusted pinned key")
        return 1
    if not SearchProof.verify(envelope):
        print("FAIL: JSON receipt changed or signature invalid")
        return 1
    if args.pdf and not SearchProof.verify_pdf(args.pdf.read_bytes(), envelope):
        print("FAIL: PDF receipt changed or signature invalid")
        return 1
    print("PASS: JSON signature valid" + ("; PDF signature valid" if args.pdf else ""))
    print("Scope: verified receipt integrity only, not vehicle absence or source-video accuracy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
