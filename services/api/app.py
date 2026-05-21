import os
import re
import cv2
import json
import uuid
import asyncio
import numpy as np
import pytesseract  # type: ignore
from jose import jwt
from passlib.context import CryptContext

from io import BytesIO
from pathlib import Path
from PIL import Image
from packaging import version
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sqlalchemy import create_engine, Column, String, DateTime, Numeric, ForeignKey, Index, func
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session
from sqlalchemy.dialects.postgresql import UUID, JSONB

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUEUE_DIR = PROJECT_ROOT / "storage" / "uploads" / "queue"
QUEUE_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:teste123@127.0.0.1:5432/meter_reader",
)

DIGITAL_WEIGHTS = Path(
    os.getenv("METER_DIGITAL_WEIGHTS", str(PROJECT_ROOT / "models" / "digital" / "best.pt"))
)
ANALOG_WEIGHTS = Path(
    os.getenv("METER_ANALOG_WEIGHTS", str(PROJECT_ROOT / "models" / "analog" / "best.pt"))
)

TESS_MIN = "4.0.0"

engine = create_engine(DATABASE_URL, pool_pre_ping=True, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

SECRET_KEY = "UFG_METER_SECRET"
ALGORITHM = "HS256"

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class MeterDB(Base):
    __tablename__ = "meters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), nullable=True)
    utility = Column(String, nullable=False, default="water")
    type = Column(String, nullable=False, default="digital")
    serial = Column(String, nullable=True, unique=True, index=True)
    multiplier = Column(Numeric, default=1.0)
    installed_at = Column(DateTime(timezone=True), nullable=True)

    readings = relationship("ReadingDB", back_populates="meter", cascade="all, delete-orphan")

class ReadingDB(Base):
    __tablename__ = "readings"
    __table_args__ = (Index("idx_readings_meter_ts", "meter_id", "ts"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meter_id = Column(UUID(as_uuid=True), ForeignKey("meters.id"), nullable=False)
    ts = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    value = Column(Numeric, nullable=False)
    unit = Column(String, nullable=False, default="m3")
    confidence = Column(Numeric, nullable=True)
    image_url = Column(String, nullable=True)
    bbox = Column(JSONB, nullable=True)
    model_versions = Column(JSONB, nullable=True)
    qc_json = Column(JSONB, nullable=True)
    status = Column(String, default="auto", nullable=False)

    meter = relationship("MeterDB", back_populates="readings")

class UserDB(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name = Column(String, nullable=False)

    email = Column(String, unique=True, nullable=False, index=True)

    password_hash = Column(String, nullable=False)

    role = Column(String, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

class MeterCreateIn(BaseModel):
    serial: str
    utility: str = "water"
    type: str = "digital"
    multiplier: float = 1.0
    user_id: Optional[str] = None

class MeterOut(BaseModel):
    id: str
    serial: Optional[str]
    utility: str
    type: str
    multiplier: float
    installed_at: Optional[str] = None
    user_id: Optional[str] = None

class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Meter Reader API", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

digital_model = None
analog_model = None

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except Exception:
    YOLO_AVAILABLE = False

def load_models():
    global digital_model, analog_model

    if not YOLO_AVAILABLE:
        print("[WARN] Ultralytics/YOLO não está instalado — fallback Tesseract.")
        return

    try:
        if DIGITAL_WEIGHTS.exists():
            digital_model = YOLO(str(DIGITAL_WEIGHTS))
            print(f"[MODEL] Digital carregado: {DIGITAL_WEIGHTS}")
        else:
            print(f"[WARN] Peso digital não encontrado: {DIGITAL_WEIGHTS}")
    except Exception as exc:
        digital_model = None
        print(f"[ERROR] Falha ao carregar modelo digital: {exc}")

    try:
        if ANALOG_WEIGHTS.exists():
            analog_model = YOLO(str(ANALOG_WEIGHTS))
            print(f"[MODEL] Analógico carregado: {ANALOG_WEIGHTS}")
        else:
            print(f"[WARN] Peso analógico não encontrado: {ANALOG_WEIGHTS}")
    except Exception as exc:
        analog_model = None
        print(f"[ERROR] Falha ao carregar modelo analógico: {exc}")

load_models()

TESS_OK = True
TESS_MSG = "ok"
try:
    tv = pytesseract.get_tesseract_version()
    if version.parse(str(tv)) < version.parse(TESS_MIN):
        TESS_OK = False
        TESS_MSG = f"Tesseract muito antigo: {tv}. Instale 5.x 64-bit."
except Exception as exc:
    TESS_OK = False
    TESS_MSG = f"Falha ao checar Tesseract: {exc}"

class ReadingIn(BaseModel):
    job_id: Optional[str] = None
    meter_id: str
    utility: Optional[str] = "water"
    type: Optional[str] = "digital"
    value: Optional[float] = None
    confidence: Optional[float] = None
    raw_text: Optional[str] = None
    unit: Optional[str] = None
    model_version: Optional[str] = None
    timestamp: Optional[str] = None
    image_url: Optional[str] = None

class UploadResponse(BaseModel):
    job_id: str
    path: str
    raw_text: Optional[str] = None
    value: Optional[float] = None
    confidence: Optional[float] = None
    unit: Optional[str] = None
    model_version: Optional[str] = None
    timestamp: Optional[str] = None

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str):
    return pwd_context.verify(password, hashed)

def sanitize_folder(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())

def normalize_meter_id(meter_id: str) -> str:
    return meter_id.strip()

def parse_timestamp(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)

def unit_from_utility(utility: str) -> str:
    return "kWh" if utility.lower() == "power" else "m3"

def get_or_create_meter(db: Session, meter_id: str, utility: str = "water", meter_type: str = "digital") -> MeterDB:
    serial = normalize_meter_id(meter_id)
    meter = db.query(MeterDB).filter(MeterDB.serial == serial).first()
    if meter:
        return meter

    meter = MeterDB(serial=serial, utility=utility, type=meter_type)
    db.add(meter)
    db.commit()
    db.refresh(meter)
    return meter

def reading_to_dict(reading: ReadingDB) -> dict:
    qc = reading.qc_json or {}
    versions = reading.model_versions or {}
    meter_code = reading.meter.serial if reading.meter and reading.meter.serial else str(reading.meter_id)

    return {
        "id": str(reading.id),
        "job_id": qc.get("job_id"),
        "meter_id": meter_code,
        "timestamp": reading.ts.isoformat() if reading.ts else None,
        "value": float(reading.value) if reading.value is not None else None,
        "confidence": float(reading.confidence) if reading.confidence is not None else None,
        "raw_text": qc.get("raw_text"),
        "unit": reading.unit,
        "model_version": versions.get("version"),
        "image_url": reading.image_url,
        "status": reading.status,
    }

def meter_to_dict(meter: MeterDB):
    return {
        "id": str(meter.id),
        "serial": meter.serial,
        "utility": meter.utility,
        "type": meter.type,
        "multiplier": float(meter.multiplier or 1),
        "installed_at": meter.installed_at.isoformat() if meter.installed_at else None,
        "user_id": str(meter.account_id) if meter.account_id else None,
    }

def _to_value(text: str):
    cleaned = re.sub(r"[^0-9.]", "", text.replace(",", "."))
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except Exception:
        return None

def _score_candidate(raw_text: str, conf: float):
    return len(re.findall(r"\d", raw_text)), conf

def tesseract_digit_ocr(pil_img: Image.Image):
    bgr = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    pad = max(2, int(0.02 * min(h, w)))
    bgr = bgr[pad:h - pad, pad:w - pad]
    bgr = cv2.resize(bgr, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

    thr_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    thr_inv = cv2.bitwise_not(thr_otsu)
    thr_adp = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2)
    thr_adp_i = cv2.bitwise_not(thr_adp)

    kernel = np.ones((2, 2), np.uint8)
    images = [
        thr_otsu,
        thr_inv,
        thr_adp,
        thr_adp_i,
        cv2.morphologyEx(thr_otsu, cv2.MORPH_CLOSE, kernel, iterations=1),
        cv2.morphologyEx(thr_inv, cv2.MORPH_CLOSE, kernel, iterations=1),
    ]

    best = {"raw_text": "", "value": None, "confidence": 0.0}

    for img in images:
        for psm in [7, 6, 8, 13]:
            cfg = f"-l eng --oem 1 --psm {psm} -c tessedit_char_whitelist=0123456789.,"
            data = pytesseract.image_to_data(img, config=cfg, output_type=pytesseract.Output.DICT)
            parts, confs = [], []

            for i, txt in enumerate(data.get("text", [])):
                txt = re.sub(r"[^0-9.,]", "", (txt or "").strip())
                if not txt:
                    continue
                try:
                    conf = float(data["conf"][i])
                except Exception:
                    conf = 0.0
                parts.append(txt)
                confs.append(conf)

            raw = "".join(parts)
            confidence = round(sum(confs) / len(confs) / 100.0, 2) if confs else 0.0
            value = _to_value(raw)

            if _score_candidate(raw, confidence) > _score_candidate(best["raw_text"], best["confidence"]):
                best = {"raw_text": raw, "value": value, "confidence": confidence}

    return best

def yolo_digit_read(pil_img: Image.Image):
    if digital_model is None:
        return {"raw_text": "", "value": None, "confidence": 0.0}

    img = np.array(pil_img.convert("RGB"))
    result = digital_model(img, verbose=False)[0]
    digits, confs = [], []

    for box in result.boxes:
        x_min = float(box.xyxy[0][0])
        cls = int(box.cls[0])
        conf = float(box.conf[0]) if hasattr(box, "conf") else 0.0
        digits.append((x_min, str(cls)))
        confs.append(conf)

    digits.sort(key=lambda item: item[0])
    raw_text = "".join(digit for _, digit in digits)
    return {
        "raw_text": raw_text,
        "value": float(raw_text) if raw_text else None,
        "confidence": round(sum(confs) / len(confs), 2) if confs else 0.0,
    }

def _class_name(result, idx: int) -> str:
    names = getattr(result, "names", None)
    if isinstance(names, dict):
        return str(names.get(int(idx), str(int(idx))))
    if isinstance(names, (list, tuple)):
        i = int(idx)
        return str(names[i]) if 0 <= i < len(names) else str(i)
    return str(int(idx))

def yolo_analog_read(pil_img: Image.Image):
    if analog_model is None:
        return {"raw_text": "", "value": None, "confidence": 0.0}

    img = np.array(pil_img.convert("RGB"))
    result = analog_model(img, verbose=False)[0]
    name_map = {
        "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    }

    digits, confs = [], []
    for box in result.boxes:
        x_min = float(box.xyxy[0][0])
        cls_idx = int(box.cls[0])
        conf = float(box.conf[0]) if hasattr(box, "conf") else 0.0
        cls_name = _class_name(result, cls_idx).strip().lower()
        digit = name_map.get(cls_name, cls_name if cls_name.isdigit() else None)
        if digit is not None:
            digits.append((x_min, digit))
            confs.append(conf)

    digits.sort(key=lambda item: item[0])
    raw_text = "".join(digit for _, digit in digits)
    return {
        "raw_text": raw_text,
        "value": float(raw_text) if raw_text else None,
        "confidence": round(sum(confs) / len(confs), 2) if confs else 0.0,
    }

def infer_image(pil_img: Image.Image):
    candidates = []

    if digital_model is not None:
        try:
            pred = yolo_digit_read(pil_img)
            pred["model_version"] = "yolo-digital"
            candidates.append(pred)
        except Exception as exc:
            print(f"[WARN] erro yolo_digit_read: {exc}")

    if analog_model is not None:
        try:
            pred = yolo_analog_read(pil_img)
            pred["model_version"] = "yolo-analog"
            candidates.append(pred)
        except Exception as exc:
            print(f"[WARN] erro yolo_analog_read: {exc}")

    if not candidates:
        pred = tesseract_digit_ocr(pil_img)
        pred["model_version"] = "tesseract"
        candidates.append(pred)

    def score(candidate):
        has_value = candidate.get("value") is not None
        digits = len(candidate.get("raw_text") or "")
        conf = float(candidate.get("confidence") or 0.0)
        return has_value, digits, conf

    return max(candidates, key=score)

class RegisterIn(BaseModel):
    name: str
    email: str
    password: str
    role: str

class LoginIn(BaseModel):
    email: str
    password: str

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
        "version": str(pytesseract.get_tesseract_version()) if TESS_OK else None,
    }

@app.post("/auth/register")
def register(user: RegisterIn, db: Session = Depends(get_db)):

    existing = db.query(UserDB).filter(
        UserDB.email == user.email
    ).first()

    if existing:
        raise HTTPException(400, "Email já existe")

    if user.role not in ("user", "company", "admin"):
        raise HTTPException(400, "Cargo inválido")

    new_user = UserDB(
        name=user.name,
        email=user.email,
        password_hash=hash_password(user.password),
        role=user.role
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "status": "ok",
        "user": {
            "id": str(new_user.id),
            "nome": new_user.name,
            "email": new_user.email,
            "cargo": new_user.role
        }
    }

@app.post("/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):

    user = db.query(UserDB).filter(
        UserDB.email == data.email
    ).first()

    if not user:
        raise HTTPException(401, "Credenciais inválidas")

    if not verify_password(
        data.password,
        user.password_hash
    ):
        raise HTTPException(401, "Credenciais inválidas")

    token = jwt.encode(
        {
            "sub": str(user.id),
            "role": user.role
        },
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return {
        "access_token": token,
        "user": {
            "id": str(user.id),
            "nome": user.name,
            "email": user.email,
            "cargo": user.role
        }
    }

@app.post("/api/meters")
def create_meter(data: MeterCreateIn, db: Session = Depends(get_db)):
    utility = data.utility.lower()
    if utility not in ("water", "gas", "power"):
        raise HTTPException(422, "utility must be water, gas or power")

    meter_type = data.type.lower()
    if meter_type not in ("digital", "analog"):
        raise HTTPException(422, "type must be digital or analog")

    existing = db.query(MeterDB).filter(MeterDB.serial == data.serial).first()
    if existing:
        raise HTTPException(400, "meter already exists")

    owner_id = None
    if data.user_id:
        try:
            owner_id = uuid.UUID(data.user_id)
        except Exception:
            raise HTTPException(422, "invalid user_id")

        owner = db.query(UserDB).filter(UserDB.id == owner_id).first()
        if not owner:
            raise HTTPException(404, "user not found")

    meter = MeterDB(
        serial=data.serial,
        utility=utility,
        type=meter_type,
        multiplier=data.multiplier,
        account_id=owner_id,
    )

    db.add(meter)
    db.commit()
    db.refresh(meter)

    return {"status": "ok", "meter": meter_to_dict(meter)}

@app.get("/api/meters")
def list_meters(
    user_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(MeterDB)

    if user_id:
        try:
            uid = uuid.UUID(user_id)
        except Exception:
            raise HTTPException(422, "invalid user_id")
        query = query.filter(MeterDB.account_id == uid)

    meters = query.order_by(MeterDB.serial.asc()).all()
    return {"items": [meter_to_dict(meter) for meter in meters]}

@app.delete("/api/meters/{meter_id}")
def delete_meter(meter_id: str, db: Session = Depends(get_db)):
    try:
        mid = uuid.UUID(meter_id)
    except Exception:
        raise HTTPException(422, "invalid meter_id")

    meter = db.query(MeterDB).filter(MeterDB.id == mid).first()
    if not meter:
        raise HTTPException(404, "meter not found")

    db.delete(meter)
    db.commit()
    return {"status": "deleted", "id": meter_id}

@app.get("/api/users")
def list_users(
    role: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(UserDB)

    if role:
        query = query.filter(UserDB.role == role)

    users = query.order_by(UserDB.name.asc()).all()

    return {
        "items": [
            {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "role": user.role,
            }
            for user in users
        ]
    }

@app.get("/api/dashboard/summary")
def dashboard_summary(
    user_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    readings_query = db.query(ReadingDB).join(MeterDB)
    meters_query = db.query(MeterDB)

    if user_id:
        try:
            uid = uuid.UUID(user_id)
        except Exception:
            raise HTTPException(422, "invalid user_id")

        readings_query = readings_query.filter(MeterDB.account_id == uid)
        meters_query = meters_query.filter(MeterDB.account_id == uid)

    readings = readings_query.order_by(ReadingDB.ts.desc()).limit(5).all()

    total_readings = readings_query.count()
    total_meters = meters_query.count()

    total_consumption = (
        readings_query.with_entities(func.coalesce(func.sum(ReadingDB.value), 0)).scalar()
    )

    avg_confidence = (
        readings_query.with_entities(func.coalesce(func.avg(ReadingDB.confidence), 0)).scalar()
    )

    return {
        "total_meters": total_meters,
        "total_readings": total_readings,
        "total_consumption": float(total_consumption or 0),
        "avg_confidence": float(avg_confidence or 0),
        "mini_history": [reading_to_dict(reading) for reading in readings],
    }

@app.post("/predict")
@app.post("/api/predict")
@app.post("/api/uploads", response_model=UploadResponse)
async def predict(meter_id: str = Form(...), utility: str = Form(...), file: UploadFile = File(...)):
    if not meter_id:
        raise HTTPException(422, "ID do medidor obrigatório")

    utility = utility.lower()
    if utility not in ("water", "gas", "power"):
        raise HTTPException(422, "medidor dever ser water|gas|power")

    meter_id_clean = sanitize_folder(meter_id)
    timestamp_file = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    job_dir = QUEUE_DIR / meter_id_clean / timestamp_file
    job_dir.mkdir(parents=True, exist_ok=True)

    image_path = job_dir / "input.jpg"
    content = await file.read()
    if not content:
        raise HTTPException(400, "arquivo vazio")

    image_path.write_bytes(content)
    (job_dir / "meta.json").write_text(json.dumps({"medidor": utility}, ensure_ascii=False, indent=2), encoding="utf-8")

    pil_img = Image.open(BytesIO(content)).convert("RGB")
    pred = infer_image(pil_img)
    now = datetime.now(timezone.utc).isoformat()

    return UploadResponse(
        job_id=f"{meter_id_clean}:{timestamp_file}",
        path=str(image_path),
        raw_text=pred.get("raw_text"),
        value=pred.get("value"),
        confidence=pred.get("confidence"),
        unit=unit_from_utility(utility),
        model_version=pred.get("model_version"),
        timestamp=now,
    )

@app.post("/api/infer")
async def infer(meter_id: str = Form(...), utility: str = Form(...), file: UploadFile = File(...)):
    utility = utility.lower()
    if utility not in ("water", "gas", "power"):
        raise HTTPException(422, "utility must be water|gas|power")

    content = await file.read()
    if not content:
        raise HTTPException(400, "empty file")

    pil_img = Image.open(BytesIO(content)).convert("RGB")
    pred = infer_image(pil_img)

    return {
        "meter_id": meter_id,
        "utility": utility,
        "value": pred.get("value"),
        "confidence": pred.get("confidence"),
        "raw_text": pred.get("raw_text"),
        "unit": unit_from_utility(utility),
        "model_version": pred.get("model_version"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.post("/api/readings")
def create_reading(reading: ReadingIn, db: Session = Depends(get_db)):
    if reading.value is None:
        raise HTTPException(422, "value is required to save reading in PostgreSQL")

    utility = (reading.utility or "water").lower()
    if utility not in ("water", "gas", "power"):
        utility = "water"

    meter_type = reading.type or "digital"
    if meter_type not in ("digital", "analog"):
        meter_type = "digital"

    meter = get_or_create_meter(db, reading.meter_id, utility=utility, meter_type=meter_type)

    new_reading = ReadingDB(
        meter_id=meter.id,
        ts=parse_timestamp(reading.timestamp),
        value=reading.value,
        unit=reading.unit or unit_from_utility(utility),
        confidence=reading.confidence,
        image_url=reading.image_url,
        model_versions={"version": reading.model_version} if reading.model_version else None,
        qc_json={"job_id": reading.job_id, "raw_text": reading.raw_text},
        status="auto",
    )

    db.add(new_reading)
    db.commit()
    db.refresh(new_reading)

    return {"status": "ok", "id": str(new_reading.id), "reading": reading_to_dict(new_reading)}

@app.get("/api/readings")
def list_readings(
    meter_id: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(ReadingDB).join(MeterDB)

    if meter_id:
        query = query.filter(MeterDB.serial == normalize_meter_id(meter_id))

    if job_id:
        query = query.filter(ReadingDB.qc_json.op("->>")("job_id") == job_id)

    readings = query.order_by(ReadingDB.ts.desc()).limit(limit).all()
    return {"items": [reading_to_dict(reading) for reading in readings]}

@app.get("/api/readings/{reading_id}")
def get_reading(reading_id: str, db: Session = Depends(get_db)):
    try:
        rid = uuid.UUID(reading_id)
    except Exception:
        raise HTTPException(422, "invalid reading_id")

    reading = db.query(ReadingDB).filter(ReadingDB.id == rid).first()
    if not reading:
        raise HTTPException(404, "reading not found")

    return reading_to_dict(reading)

@app.delete("/api/readings/{reading_id}")
def delete_reading(reading_id: str, db: Session = Depends(get_db)):
    try:
        rid = uuid.UUID(reading_id)
    except Exception:
        raise HTTPException(422, "invalid reading_id")

    reading = db.query(ReadingDB).filter(ReadingDB.id == rid).first()
    if not reading:
        raise HTTPException(404, "reading not found")

    db.delete(reading)
    db.commit()
    return {"status": "deleted", "id": reading_id}

@app.websocket("/ws/jobs/{job_id}")
async def ws_job(websocket: WebSocket, job_id: str):
    await websocket.accept()
    db = SessionLocal()
    try:
        for _ in range(120):
            reading = (
                db.query(ReadingDB)
                .filter(ReadingDB.qc_json.op("->>")("job_id") == job_id)
                .order_by(ReadingDB.ts.desc())
                .first()
            )
            if reading:
                await websocket.send_json({"status": "done", "reading": reading_to_dict(reading)})
                await websocket.close()
                return
            await asyncio.sleep(1)

        await websocket.send_json({"status": "timeout", "job_id": job_id})
        await websocket.close()

    except WebSocketDisconnect:
        return
    finally:
        db.close()