from __future__ import annotations

import os
import time
import json
import shutil
import logging
import traceback
from pathlib import Path
from typing import Iterator, Tuple, Optional

import requests

# Importa seu pipeline YOLO (display -> crop -> dígitos)
from infer_pipeline import run_inference  # <- usa best.pt


# ==========================
# Config
# ==========================
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000").rstrip("/")
DEFAULT_UTILITY = os.environ.get("DEFAULT_UTILITY", "water").lower()

POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1.0"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "2"))
BACKOFF_S = float(os.environ.get("BACKOFF_S", "1.5"))

CONF_MIN = float(os.environ.get("CONF_MIN", "0.0"))  # 0.0 desliga filtro
MIN_LEN = int(os.environ.get("MIN_LEN", "0"))        # 0 desliga filtro

# Se você quiser sobrescrever endpoints:
READINGS_PATH = os.environ.get("READINGS_PATH", "").strip()

# Layout de storage (compatível com seu MVP)
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # .../meter_reader
QUEUE_DIR = PROJECT_ROOT / "storage" / "uploads" / "queue"
DONE_DIR = PROJECT_ROOT / "storage" / "uploads" / "done"
FAILED_DIR = PROJECT_ROOT / "storage" / "uploads" / "failed"


# ==========================
# Logging
# ==========================
logging.basicConfig(
    level=logging.INFO,
    format="[WORKER] %(asctime)s %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("worker")


# ==========================
# Helpers
# ==========================
READINGS_CANDIDATES = ["/api/readings", "/readings"]

def resolve_endpoint(candidates: list[str], override: str = "") -> str:
    """
    Tenta descobrir endpoint certo olhando /openapi.json da API.
    Se falhar, usa o primeiro candidato.
    """
    if override:
        return override

    try:
        r = requests.get(f"{API_URL}/openapi.json", timeout=5)
        r.raise_for_status()
        spec = r.json()
        paths = set(spec.get("paths", {}).keys())
        for p in candidates:
            if p in paths:
                return p
    except Exception:
        pass

    return candidates[0]


READINGS_EP = resolve_endpoint(READINGS_CANDIDATES, READINGS_PATH)
log.info(f"Using endpoint: readings={READINGS_EP}")


def ensure_dirs() -> None:
    for d in (QUEUE_DIR, DONE_DIR, FAILED_DIR):
        d.mkdir(parents=True, exist_ok=True)


def healthcheck() -> None:
    # Não é obrigatório existir /health, mas ajuda.
    for p in ("/health", "/openapi.json"):
        try:
            r = requests.get(f"{API_URL}{p}", timeout=5)
            log.info(f"API {p} -> {r.status_code}")
        except Exception as e:
            log.warning(f"Falha {p}: {e}")


def find_jobs(queue_dir: Path) -> Iterator[Tuple[str, Path, Path]]:
    """
    Espera estrutura:
      queue/<meter_id>/<timestamp>/input.jpg
    """
    if not queue_dir.exists():
        return
    for meter_dir in sorted(queue_dir.iterdir()):
        if not meter_dir.is_dir():
            continue
        for stamp_dir in sorted(meter_dir.iterdir()):
            if not stamp_dir.is_dir():
                continue
            img = stamp_dir / "input.jpg"
            if img.exists():
                yield meter_dir.name, stamp_dir, img


def detect_utility(job_dir: Path) -> str:
    """
    Lê job_dir/meta.json se existir:
      {"utility": "water"|"gas"|"power"}
    """
    meta = job_dir / "meta.json"
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            u = str(data.get("utility", DEFAULT_UTILITY)).lower()
            if u in ("water", "gas", "power"):
                return u
        except Exception:
            pass
    return DEFAULT_UTILITY


def write_error(job_dir: Path, err: Exception) -> None:
    try:
        (job_dir / "error.txt").write_text(
            "".join(traceback.format_exception(err)),
            encoding="utf-8",
        )
    except Exception:
        pass


def aceita_pred(value: Optional[str], confidence: float) -> Tuple[bool, str]:
    """
    Regras mínimas de qualidade (configuráveis por env).
    """
    if confidence < CONF_MIN:
        return False, f"confidence_baixa({confidence}<{CONF_MIN})"
    if MIN_LEN > 0:
        s = (value or "").strip()
        if len(s) < MIN_LEN:
            return False, f"poucos_digitos({len(s)}<{MIN_LEN})"
    return True, "ok"


def post_reading(payload: dict) -> dict:
    url = f"{API_URL}{READINGS_EP}"
    r = requests.post(url, json=payload, timeout=30)
    if r.status_code >= 400:
        raise requests.HTTPError(f"{r.status_code} {r.reason} - {r.text[:800]}")
    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


def process_job(meter_id: str, job_dir: Path, image_path: Path) -> None:
    utility = detect_utility(job_dir)
    ts = job_dir.name
    job_id = f"{meter_id}:{ts}"

    # --- Inferência local (usa best.pt dentro do infer_pipeline.py) ---
    tries = 0
    pred = None
    while True:
        try:
            pred = run_inference(str(image_path))
            break
        except Exception as e:
            tries += 1
            if tries > MAX_RETRIES:
                raise
            log.warning(f"retry infer ({tries}/{MAX_RETRIES}) por erro: {e}")
            time.sleep(BACKOFF_S * tries)

    value = pred.get("value")
    confidence = float(pred.get("confidence") or 0.0)

    ok, motivo = aceita_pred(value, confidence)
    if not ok:
        raise RuntimeError(f"Reprovado: {motivo}")

    # Monta payload compatível com /api/readings do seu MVP
    payload = {
        "job_id": job_id,
        "meter_id": meter_id,
        "device_id": meter_id,
        "utility": utility,
        "value": value,
        "confidence": confidence,
        "raw_text": value,
        "unit": pred.get("unit"),
        "model_version": pred.get("model_version"),
        "timestamp": pred.get("timestamp"),
        # debug opcional (tira se quiser mais leve)
        "debug": pred.get("debug"),
        "display_bbox": pred.get("display_bbox"),
        "meter_type": pred.get("meter_type"),
    }

    # --- Post na API ---
    tries = 0
    while True:
        try:
            resp = post_reading(payload)
            log.info(f"Reading registrado: {resp}")
            break
        except Exception as e:
            tries += 1
            if tries > MAX_RETRIES:
                raise
            log.warning(f"retry POST readings ({tries}/{MAX_RETRIES}) por erro: {e}")
            time.sleep(BACKOFF_S * tries)

    # --- Move job para done ---
    rel = job_dir.relative_to(QUEUE_DIR)
    dest = DONE_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(job_dir), str(dest))
    log.info(f"Job concluído -> {dest}")


def main() -> None:
    ensure_dirs()
    log.info(f"API_URL........: {API_URL}")
    log.info(f"PROJECT_ROOT...: {PROJECT_ROOT}")
    log.info(f"QUEUE_DIR......: {QUEUE_DIR}")
    log.info(f"DONE_DIR.......: {DONE_DIR}")
    log.info(f"FAILED_DIR.....: {FAILED_DIR}")
    healthcheck()

    log.info(f"Aguardando jobs em {QUEUE_DIR}")

    while True:
        found_any = False

        for meter_id, job_dir, img in find_jobs(QUEUE_DIR):
            found_any = True
            try:
                process_job(meter_id, job_dir, img)
            except Exception as e:
                log.error(f"Falha no job {job_dir}: {e}")
                write_error(job_dir, e)

                rel = job_dir.relative_to(QUEUE_DIR)
                dest = FAILED_DIR / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(job_dir), str(dest))
                log.info(f"Job movido -> {dest}")

        if not found_any:
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()