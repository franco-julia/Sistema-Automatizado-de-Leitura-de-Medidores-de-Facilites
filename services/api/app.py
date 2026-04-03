import os
import re
import cv2
import json
import asyncio
import numpy as np
import pytesseract # type: ignore

from PIL import Image
from io import BytesIO
from pathlib import Path
from packaging import version
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Optional, List, Dict
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request

digital_model = None
analog_model = None
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except Exception:
    YOLO_AVAILABLE = False

app = FastAPI(title="Meter Reader API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ROOT = Path(__file__).resolve().parents[2] 

DIGITAL_WEIGHTS = Path(os.environ.get("METER_DIGITAL_WEIGHTS",
                                      PROJECT_ROOT / "models" / "digital" / "best.pt"))
ANALOG_WEIGHTS = Path(os.environ.get("METER_ANALOG_WEIGHTS",
                                     PROJECT_ROOT / "models" / "analog" / "best.pt"))

READINGS_FILE = Path("storage/readings.json")

TESS_MIN = "4.0.0"
TESS_OK = True
TESS_MSG = "ok"
try:
    tv = pytesseract.get_tesseract_version()
    if version.parse(str(tv)) < version.parse(TESS_MIN):
        TESS_OK = False
        TESS_MSG = f"Tesseract muito antigo: {tv}. Instale 5.x 64-bit."
except Exception as e:
    TESS_OK = False
    TESS_MSG = f"Falha ao checar Tesseract: {e}"

def load_models():
    global digital_model, analog_model
    if YOLO_AVAILABLE:
        # DIGITAL
        try:
            if DIGITAL_WEIGHTS.exists():
                digital_model = YOLO(str(DIGITAL_WEIGHTS))
                print(f"[MODEL] Digital carregado: {DIGITAL_WEIGHTS}")
            else:
                print(f"[WARN] Peso digital não encontrado: {DIGITAL_WEIGHTS} — fallback Tesseract.")
        except Exception as e:
            digital_model = None
            print(f"[ERROR] Falha ao carregar digital: {e} — fallback Tesseract.")

        # ANALOG
        try:
            if ANALOG_WEIGHTS.exists():
                analog_model = YOLO(str(ANALOG_WEIGHTS))
                print(f"[MODEL] Analog carregado: {ANALOG_WEIGHTS}")
            else:
                print(f"[WARN] Peso analog não encontrado: {ANALOG_WEIGHTS}")
        except Exception as e:
            analog_model = None
            print(f"[ERROR] Falha ao carregar analog: {e}")
    else:
        print("[WARN] Ultralytics/YOLO não está instalado — usarei só Tesseract.")

load_models()

#Tesseract 
def _to_value(text: str):
    s = re.sub(r"[^0-9.]", "", text.replace(",", "."))
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None

def _score_candidate(raw_text: str, conf: float):
    digits = len(re.findall(r"\d", raw_text))
    return (digits, conf)

def tesseract_digit_ocr(pil_img: Image.Image):
    """OCR robusto para dígitos mecânicos/LCD (fallback)."""
    bgr = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    pad = max(2, int(0.02 * min(h, w)))
    bgr = bgr[pad:h - pad, pad:w - pad]
    bgr = cv2.resize(bgr, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

    thr_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    thr_inv = cv2.bitwise_not(thr_otsu)
    thr_adp = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 31, 2)
    thr_adp_i = cv2.bitwise_not(thr_adp)

    kernel = np.ones((2, 2), np.uint8)
    m1 = cv2.morphologyEx(thr_otsu, cv2.MORPH_CLOSE, kernel, iterations=1)
    m2 = cv2.morphologyEx(thr_inv, cv2.MORPH_CLOSE, kernel, iterations=1)

    images = [thr_otsu, thr_inv, thr_adp, thr_adp_i, m1, m2]
    psms = [7, 6, 8, 13]

    best = {"raw_text": "", "value": None, "confidence": 0.0}
    for img in images:
        for psm in psms:
            cfg = f'-l eng --oem 1 --psm {psm} -c tessedit_char_whitelist=0123456789.,'
            data = pytesseract.image_to_data(img, config=cfg, output_type=pytesseract.Output.DICT)
            parts, confs = [], []
            for i, txt in enumerate(data["text"]):
                if not txt:
                    continue
                txt = re.sub(r"[^0-9.,]", "", txt.strip())
                if not txt:
                    continue
                try:
                    c = float(data["conf"][i])
                except Exception:
                    c = 0.0
                parts.append(txt)
                confs.append(c)

            raw = "".join(parts)
            val = _to_value(raw)
            conf = round((sum(confs) / len(confs) / 100.0), 2) if confs else 0.0
            if _score_candidate(raw, conf) > _score_candidate(best["raw_text"], best["confidence"]):
                best = {"raw_text": raw, "value": val, "confidence": conf}

    return best

# digital
def yolo_digit_read(pil_img: Image.Image):
    """Lê dígitos usando o seu modelo YOLO de detecção/classificação por dígito."""
    if digital_model is None:
        return {"raw_text": "", "value": None, "confidence": 0.0}

    img = np.array(pil_img.convert("RGB"))
    res = digital_model(img, verbose=False)[0]

    digits = []
    confs = []
    for box in res.boxes:
        x_min = float(box.xyxy[0][0])
        cls = int(box.cls[0])
        conf = float(box.conf[0]) if hasattr(box, "conf") else 0.0
        digits.append((x_min, str(cls)))
        confs.append(conf)

    digits.sort(key=lambda t: t[0])
    text = "".join(d[1] for d in digits)
    value = float(text) if text else None
    confidence = round((sum(confs) / len(confs)) if confs else 0.0, 2)
    return {"raw_text": text, "value": value, "confidence": confidence}

#analog 
def _class_name(res, idx: int) -> str:
    """Obtém o nome de classe de forma robusta (dict ou list)."""
    names = getattr(res, "names", None)
    if isinstance(names, dict):
        return str(names.get(int(idx), str(int(idx))))
    if isinstance(names, (list, tuple)):
        i = int(idx)
        return str(names[i]) if 0 <= i < len(names) else str(i)
    return str(int(idx))

def yolo_analog_read(pil_img: Image.Image):
    """
    Lê dígitos do modelo analógico (ex.: classes '0'..'9' ou nomes 'zero'..'nine').
    Ordena por X e concatena os dígitos.
    """
    if analog_model is None:
        return {"raw_text": "", "value": None, "confidence": 0.0}

    import numpy as np
    img = np.array(pil_img.convert("RGB"))
    res = analog_model(img, verbose=False)[0]

    name_map = {
        "zero":"0","one":"1","two":"2","three":"3","four":"4",
        "five":"5","six":"6","seven":"7","eight":"8","nine":"9"
    }

    digits, confs = [], []
    for b in res.boxes:
        x_min = float(b.xyxy[0][0])
        cls_idx = int(b.cls[0])
        conf = float(b.conf[0]) if hasattr(b, "conf") else 0.0

        cls_name = _class_name(res, cls_idx).strip()
        cls_lower = cls_name.lower()

        digit = name_map.get(cls_lower)
        if digit is None and cls_lower.isdigit():
            digit = cls_lower

        if digit is not None:
            digits.append((x_min, digit))
            confs.append(conf)

    digits.sort(key=lambda t: t[0])
    text = "".join(d for _, d in digits)
    value = float(text) if text else None
    confidence = round((sum(confs)/len(confs)) if confs else 0.0, 2)
    return {"raw_text": text, "value": value, "confidence": confidence}

READINGS_FILE = PROJECT_ROOT / "storage" / "readings.json"
router = APIRouter(prefix="/api", tags=["readings"])

class ReadingIn(BaseModel):
    job_id: str | None = None
    meter_id: str
    value: float | None
    confidence: float | None
    raw_text: str | None
    unit: str | None
    model_version: str | None
    timestamp: str | None

# Endpoints
@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}

@app.get("/diag/models")
def diag_models():
    return {
        "project_root": str(PROJECT_ROOT),
        "digital_weights": str(DIGITAL_WEIGHTS),
        "digital_exists": DIGITAL_WEIGHTS.exists(),
        "digital_loaded": digital_model is not None,
        "analog_weights": str(ANALOG_WEIGHTS),
        "analog_exists": ANALOG_WEIGHTS.exists(),
        "analog_loaded": analog_model is not None,
        "yolo_available": YOLO_AVAILABLE,
    }

@app.get("/diag/tesseract")
def diag_tesseract():
    return {
        "tesseract_cmd": pytesseract.pytesseract.tesseract_cmd,
        "ok": TESS_OK,
        "detail": TESS_MSG,
        "version": str(pytesseract.get_tesseract_version()) if TESS_OK else None
    }

PROJECT_ROOT = Path(__file__).resolve().parents[2] 
QUEUE_DIR = PROJECT_ROOT / "storage" / "uploads" / "queue"

class UploadResponse(BaseModel):
    job_id: str
    path: str
    raw_text: Optional[str] = None
    value: Optional[float] = None
    confidence: Optional[float] = None
    unit: Optional[str] = None
    model_version: Optional[str] = None
    timestamp: Optional[str] = None

def sanitize_folder(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name)
    return name

@app.post("/predict")
@app.post("/api/predict")
@app.post("/api/uploads", response_model=UploadResponse)
async def predict(
    meter_id: str = Form(...),
    utility: str = Form(...),
    file: UploadFile = File(...)
):
    if not meter_id:
        raise HTTPException(422, "meter_id is required")

    meter_id_clean = sanitize_folder(meter_id)
    util = utility.lower()
    if util not in ("water", "gas", "power"):
        raise HTTPException(422, "utility must be WATER|GAS|POWER")

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

    # diretório do job na fila 
    job_dir = QUEUE_DIR / meter_id_clean / ts
    job_dir.mkdir(parents=True, exist_ok=True)

    img_path = job_dir / "input.jpg"

    # salva a imagem no disco
    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")
    img_path.write_bytes(content)

    # meta para o worker
    (job_dir / "meta.json").write_text(
        json.dumps({"utility": util}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    pil_img = Image.open(BytesIO(content)).convert("RGB")

    candidates = []

    # YOLO digital
    if digital_model is not None:
        try:
            dres = yolo_digit_read(pil_img)
            dres["model_version"] = "yolo-digital"
            candidates.append(dres)
        except Exception as e:
            print(f"[WARN] erro yolo_digit_read: {e}")

    # YOLO analógico
    if analog_model is not None:
        try:
            ares = yolo_analog_read(pil_img)
            ares["model_version"] = "yolo-analog"
            candidates.append(ares)
        except Exception as e:
            print(f"[WARN] erro yolo_analog_read: {e}")

    raw_text = None
    value = None
    confidence = None
    model_version = None

    if candidates:
        def score(c):
            has_val = c.get("value") is not None
            conf = float(c.get("confidence") or 0.0)
            return (has_val, conf)

        best = max(candidates, key=score)
        raw_text = best.get("raw_text")
        value = best.get("value")
        confidence = best.get("confidence")
        model_version = best.get("model_version")

    unit = None
    if util == "water":
        unit = "m3"
    elif util == "power":
        unit = "kWh"
    elif util == "gas":
        unit = "m3"

    timestamp_iso = datetime.now(timezone.utc).isoformat()

    return UploadResponse(
        job_id=f"{meter_id_clean}:{ts}",
        path=str(img_path),
        raw_text=raw_text,
        value=value,
        confidence=confidence,
        unit=unit,
        model_version=model_version,
        timestamp=timestamp_iso,
    )

@app.get("/api/readings")
async def get_readings(meter_id: str = Query(None)):
    if not READINGS_FILE.exists():
        return {"items": []}

    with open(READINGS_FILE, "r") as f:
        data = json.load(f)

    items = data if isinstance(data, list) else []

    if meter_id:
        items = [r for r in items if r.get("meter_id") == meter_id]

    items = sorted(items, key=lambda x: x.get("timestamp", ""), reverse=True)

    return {"items": items}

@router.post("/readings")
def create_reading(reading: ReadingIn):
    READINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(READINGS_FILE.read_text(encoding="utf-8"))
        assert isinstance(data, list)
    except Exception:
        data = []
    data.append(reading.model_dump())
    READINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "count": len(data)}

@router.get("/readings")
def list_readings(job_id: str | None = None, meter_id: str | None = None):
    if not READINGS_FILE.exists():
        return {"items": []}
    try:
        data = json.loads(READINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            data = []
    except Exception:
        data = []

    items = data
    if job_id:
        items = [r for r in items if r.get("job_id") == job_id]
    if meter_id:
        items = [r for r in items if r.get("meter_id") == meter_id]

    items = sorted(items, key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"items": items}

@app.post("/api/infer")
async def infer(meter_id: str = Form(...), utility: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")

    pil = Image.open(BytesIO(content)).convert("RGB")
    util = utility.lower()

    if util in ("water", "gas", "power"):
        pass
    else:
        raise HTTPException(422, "utility must be water|gas|power")

    if util == "power":
        pred = yolo_digit_read(pil) if digital_model is not None else tesseract_digit_ocr(pil)
        unit = "kWh"
    else:
        pred = yolo_digit_read(pil) if digital_model is not None else tesseract_digit_ocr(pil)
        unit = None

    return {
        "meter_id": meter_id,
        "utility": util,
        "value": pred.get("value"),
        "confidence": pred.get("confidence"),
        "raw_text": pred.get("raw_text"),
        "unit": unit,
        "model_version": app.version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.websocket("/ws/jobs/{job_id}")
async def ws_job(websocket: WebSocket, job_id: str):
    await websocket.accept()
    try:
        for _ in range(120):
            if READINGS_FILE.exists():
                try:
                    data = json.loads(READINGS_FILE.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        found = next((r for r in reversed(data) if r.get("job_id") == job_id), None)
                        if found:
                            await websocket.send_json({"status": "done", "reading": found})
                            await websocket.close()
                            return
                except Exception:
                    pass

            await asyncio.sleep(1)

        await websocket.send_json({"status": "timeout", "job_id": job_id})
        await websocket.close()

    except WebSocketDisconnect:
        return

app.include_router(router)