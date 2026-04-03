from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

MODEL_PATH = Path(__file__).parent / "best.pt"

DISPLAY_CLASS_NAME = "display"
DIGIT_CLASS_NAMES = {str(i) for i in range(10)}

CONF_DISPLAY = 0.25
CONF_DIGIT = 0.25

@dataclass
class Det:
    cls: int
    name: str
    conf: float
    xyxy: Tuple[float, float, float, float]

_model: Optional[YOLO] = None

def _load_model() -> YOLO:
    global _model
    if _model is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"Modelo não encontrado: {MODEL_PATH}")
        _model = YOLO(str(MODEL_PATH))
    return _model

def _yolo_predict(img_bgr: np.ndarray, conf: float) -> Tuple[List[Det], Dict[int, str]]:
    model = _load_model()
    res = model.predict(source=img_bgr, conf=conf, verbose=False)
    r0 = res[0]
    names = r0.names

    dets: List[Det] = []
    if r0.boxes is None:
        return dets, names

    boxes = r0.boxes
    for i in range(len(boxes)):
        cls = int(boxes.cls[i].item())
        c = float(boxes.conf[i].item())
        x1, y1, x2, y2 = boxes.xyxy[i].tolist()
        dets.append(Det(cls=cls, name=str(names.get(cls, cls)), conf=c, xyxy=(x1, y1, x2, y2)))

    return dets, names

def _clip_xyxy(xyxy, w, h, pad=0) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = xyxy
    x1 = int(max(0, x1 - pad))
    y1 = int(max(0, y1 - pad))
    x2 = int(min(w - 1, x2 + pad))
    y2 = int(min(h - 1, y2 + pad))
    if x2 <= x1: x2 = min(w - 1, x1 + 1)
    if y2 <= y1: y2 = min(h - 1, y1 + 1)
    return x1, y1, x2, y2

def _find_display_bbox(dets: List[Det]) -> Optional[Det]:
    displays = [d for d in dets if d.name.lower() == DISPLAY_CLASS_NAME]
    if not displays:
        return None
    displays.sort(key=lambda d: d.conf, reverse=True)
    return displays[0]

def _read_digits_from_dets(dets: List[Det]) -> Tuple[Optional[str], float]:
    """
    Espera dígitos como classes 0..9 (nomes "0".."9").
    Retorna string e confiança média.
    """
    digits = [d for d in dets if d.name in DIGIT_CLASS_NAMES or d.name.isdigit()]
    if not digits:
        return None, 0.0

    digits.sort(key=lambda d: d.xyxy[0])

    value_str = "".join(str(int(d.name)) if d.name.isdigit() else d.name for d in digits)
    conf_avg = float(sum(d.conf for d in digits) / len(digits))
    return value_str, conf_avg

def _preprocess_for_digits(img_bgr: np.ndarray) -> np.ndarray:
    """
    Pequena melhora para aumentar contraste (pode ajudar em modelos fracos).
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    eq = clahe.apply(gray)
    return cv2.cvtColor(eq, cv2.COLOR_GRAY2BGR)

def run_inference(input_path: str) -> Dict[str, Any]:
    """
    Pipeline:
      1) YOLO detecta display (se existir)
      2) recorta display
      3) YOLO detecta dígitos no recorte (ou imagem inteira se não houver display)
      4) monta leitura ordenando dígitos por X
    """
    img_bgr = cv2.imread(input_path)
    if img_bgr is None:
        raise ValueError(f"Não consegui ler a imagem: {input_path}")

    h, w = img_bgr.shape[:2]

    dets1, names = _yolo_predict(img_bgr, conf=CONF_DISPLAY)

    display_det = _find_display_bbox(dets1)
    if display_det is not None:
        x1, y1, x2, y2 = _clip_xyxy(display_det.xyxy, w, h, pad=8)
        roi = img_bgr[y1:y2, x1:x2].copy()
        roi_for_digits = _preprocess_for_digits(roi)

        dets2, _ = _yolo_predict(roi_for_digits, conf=CONF_DIGIT)
        value, conf = _read_digits_from_dets(dets2)

        return {
            "meter_type": "digital",
            "display_bbox": [x1, y1, x2, y2],
            "value": value,
            "confidence": conf,
            "debug": {
                "stage1_dets": [d.__dict__ for d in dets1],
                "stage2_dets": [d.__dict__ for d in dets2],
                "classes": names,
            },
        }

    img_for_digits = _preprocess_for_digits(img_bgr)
    dets2, _ = _yolo_predict(img_for_digits, conf=CONF_DIGIT)
    value, conf = _read_digits_from_dets(dets2)

    return {
        "meter_type": "unknown",
        "display_bbox": None,
        "value": value,
        "confidence": conf,
        "debug": {
            "stage1_dets": [d.__dict__ for d in dets1],
            "stage2_dets": [d.__dict__ for d in dets2],
            "classes": names,
        },
    }