from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from datetime import datetime

class UploadResult(BaseModel):
    job_id: str
    path: str

class ReadingCreate(BaseModel):
    meter_id: str
    timestamp: datetime
    value: float
    unit: str = Field(pattern="^(kWh|m3|m³)$")
    confidence: float = Field(ge=0, le=1)
    type: str = Field(pattern="^(digital|analog)$")
    image_url: Optional[str] = None
    bbox: Optional[List[float]] = None
    model_versions: Optional[Dict[str, str]] = None
    qc: Optional[Dict[str, float]] = None

class Reading(ReadingCreate):
    id: str

class ReadingList(BaseModel):
    items: List[Reading]