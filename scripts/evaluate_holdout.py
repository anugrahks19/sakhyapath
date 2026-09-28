"""Score an annotated image holdout or generate predictions with the pinned model."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation import evaluate_holdout  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--predictions", type=Path)
    source.add_argument("--run-model", action="store_true")
    parser.add_argument("--alerts", type=Path, help="Optional alert events with verified frame UTC")
    parser.add_argument("--output", type=Path, default=ROOT / "output/benchmarks/holdout_evaluation.json")
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if args.run_model:
        import cv2
        from app.vision.recognizer import FastAlprRecognizer

        model = FastAlprRecognizer(ROOT / "backend/data/models")
        rows = []
        for frame in manifest.get("frames", []):
            image_path = (manifest_path.parent / frame["image"]).resolve()
            image = cv2.imread(str(image_path))
            if image is None:
                raise ValueError(f"Could not decode annotated frame {frame['id']}")
            started = time.perf_counter()
            detections = model.predict(image)
            elapsed_ms = (time.perf_counter() - started) * 1000
            rows.append({"id": frame["id"], "reads": [{
                "plate": read.raw_text, "detector_score": read.detector_score,
                "ocr_score": read.ocr_score, "model_latency_ms": round(elapsed_ms, 2),
            } for read in detections]})
        predictions = {"frames": rows, "model_version": model.model_version,
                       "execution_provider": model.provider}
    else:
        predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    alerts = json.loads(args.alerts.read_text(encoding="utf-8")) if args.alerts else None
    result = evaluate_holdout(manifest, predictions, alerts)
    result["model_version"] = predictions.get("model_version", "supplied predictions")
    result["execution_provider"] = predictions.get("execution_provider", "not recorded")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
