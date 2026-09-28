"""Create a shareable pre-footage source package without runtime data or secrets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/package/SakhyaPath_PreFootage_Package.zip"
ROOT_FILES = ["README.md", "pytest.ini", ".gitignore", ".gitattributes",
              "SakhyaPath_4_module_implementation_plan.md",
              "SakhyaPath_integrated_concept.md", "SakhyaPath_technical_blueprint.md"]
TREES = ["backend/app", "backend/requirements.txt", "frontend/src", "frontend/index.html",
         "frontend/package.json", "frontend/package-lock.json", "frontend/vite.config.js",
         "docs", "scripts", "tests", "hackathon_source_index",
         "sentinel_source_index", "output/benchmarks",
         "output/presentation/SakhyaPath_Hackathon_Pitch.pptx",
         "output/presentation/assets"]
SKIP_NAMES = {"__pycache__", ".pytest_cache", "node_modules", "dist", ".env"}


def files_for_bundle() -> list[Path]:
    found: set[Path] = set()
    for item in ROOT_FILES + TREES:
        candidate = ROOT / item
        if not candidate.exists():
            raise FileNotFoundError(candidate)
        if candidate.is_file():
            found.add(candidate)
        else:
            for file in candidate.rglob("*"):
                if (file.is_file() and not any(part in SKIP_NAMES for part in file.relative_to(ROOT).parts)
                        and file.suffix not in {".pyc", ".db", ".sqlite3"}):
                    found.add(file)
    return sorted(found, key=lambda file: file.relative_to(ROOT).as_posix())


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    files = files_for_bundle()
    manifest = {file.relative_to(ROOT).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
                for file in files}
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED, compresslevel=6) as bundle:
        for file in files:
            bundle.write(file, file.relative_to(ROOT).as_posix())
        bundle.writestr("BUNDLE_MANIFEST.json", json.dumps({
            "status": "pre_footage_pre_access", "file_count": len(files),
            "sha256_by_path": manifest}, indent=2))
    with ZipFile(OUTPUT) as bundle:
        if bundle.testzip() is not None:
            raise RuntimeError("ZIP integrity check failed")
        for member, expected in manifest.items():
            if hashlib.sha256(bundle.read(member)).hexdigest() != expected:
                raise RuntimeError(f"Bundle checksum mismatch: {member}")
    print(json.dumps({"path": str(OUTPUT), "file_count": len(files),
                      "bytes": OUTPUT.stat().st_size, "checksums_verified": True}, indent=2))


if __name__ == "__main__":
    main()
