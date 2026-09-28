from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from statistics import mean
from typing import Protocol

import numpy as np

DETECTOR_MODEL = "yolo-v9-t-384-license-plate-end2end"
OCR_MODEL = "cct-xs-v2-global-model"
MODEL_VERSION = f"fast-alpr-0.4.0/{DETECTOR_MODEL}/{OCR_MODEL}"


@dataclass(frozen=True)
class PlateRead:
    raw_text: str
    detector_score: float
    ocr_score: float
    bbox: tuple[int, int, int, int]


class Recognizer(Protocol):
    provider: str
    model_version: str

    def predict(self, frame_bgr: np.ndarray) -> list[PlateRead]: ...


class FastAlprRecognizer:
    def __init__(self, models_dir: Path):
        # Both upstream packages currently default to the user's home directory.
        # Keep model artifacts inside this project's ignored data directory.
        import onnxruntime as ort
        from fast_alpr import ALPR
        from fast_plate_ocr.inference import hub as ocr_hub
        from open_image_models.detection.core import hub as detector_hub

        root = Path(models_dir).resolve()
        detector_hub.MODEL_CACHE_DIR = root / "detector"
        ocr_hub.MODEL_CACHE_DIR = root / "ocr"
        available = ort.get_available_providers()
        gpu_available = "CUDAExecutionProvider" in available
        if gpu_available and hasattr(ort, "preload_dlls"):
            try:
                ort.preload_dlls(directory=os.getenv("SAKHYAPATH_CUDA_DLL_DIR") or None)
            except OSError:
                gpu_available = False
        preferred = (["CUDAExecutionProvider", "CPUExecutionProvider"] if gpu_available
                     else ["CPUExecutionProvider"])
        try:
            self.model = ALPR(
                detector_model=DETECTOR_MODEL, ocr_model=OCR_MODEL,
                detector_providers=preferred, ocr_providers=preferred,
                ocr_device="cuda" if gpu_available else "cpu",
            )
        except Exception:
            if not gpu_available:
                raise
            self.model = ALPR(
                detector_model=DETECTOR_MODEL, ocr_model=OCR_MODEL,
                detector_providers=["CPUExecutionProvider"],
                ocr_providers=["CPUExecutionProvider"], ocr_device="cpu",
            )
        detector_used = self.model.detector.detector.model.get_providers()
        ocr_used = self.model.ocr.ocr_model.model.get_providers()
        self.provider = (
            "CUDAExecutionProvider" if "CUDAExecutionProvider" in detector_used
            and "CUDAExecutionProvider" in ocr_used else
            f"mixed detector={detector_used[0]} ocr={ocr_used[0]}"
            if detector_used[0] != ocr_used[0] else detector_used[0]
        )
        self.model_version = MODEL_VERSION

    def predict(self, frame_bgr: np.ndarray) -> list[PlateRead]:
        reads: list[PlateRead] = []
        for item in self.model.predict(frame_bgr):
            if item.ocr is None or not item.ocr.text:
                continue
            confidence = item.ocr.confidence
            ocr_score = float(mean(confidence)) if isinstance(confidence, list) and confidence else (
                float(confidence) if not isinstance(confidence, list) else 0.0
            )
            box = item.detection.bounding_box
            reads.append(PlateRead(
                raw_text=item.ocr.text,
                detector_score=float(item.detection.confidence),
                ocr_score=ocr_score,
                bbox=(int(box.x1), int(box.y1), int(box.x2), int(box.y2)),
            ))
        return reads
