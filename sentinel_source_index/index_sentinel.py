"""Preserve and line-index the user-supplied Sentinel integration reference."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python index_sentinel.py <source-text-path>")

    source = Path(sys.argv[1])
    destination = Path(__file__).resolve().parent
    raw = source.read_bytes()
    decoded = raw.decode("utf-8-sig")
    lines = decoded.splitlines()

    (destination / "Sentinel_reference.txt").write_bytes(raw)
    with (destination / "Sentinel_reference_lines.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as file:
        writer = csv.writer(file, delimiter="\t")
        writer.writerow(("line", "text"))
        writer.writerows((number, line) for number, line in enumerate(lines, 1))

    metadata = {
        "source_path": str(source),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "line_count": len(lines),
        "lines": lines,
    }
    (destination / "Sentinel_reference_full.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Indexed {len(lines)} lines; SHA-256 {metadata['sha256']}")


if __name__ == "__main__":
    main()
