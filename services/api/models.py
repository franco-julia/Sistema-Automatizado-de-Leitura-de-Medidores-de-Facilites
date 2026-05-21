from sqlalchemy import Column, String, DateTime, Numeric, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from database import Base
import uuid

class Meter(Base):
    __tablename__ = "meters"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String, nullable=True)
    utility = Column(String, nullable=False)
    type = Column(String, nullable=False)
    serial = Column(String, nullable=True)
    multiplier = Column(Numeric, default=1.0)
    installed_at = Column(DateTime, nullable=True)


class Reading(Base):
    __tablename__ = "readings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    meter_id = Column(String, ForeignKey("meters.id"), nullable=False)
    ts = Column(DateTime(timezone=True), server_default=func.now())
    value = Column(Numeric, nullable=False)
    unit = Column(String, nullable=False)
    confidence = Column(Numeric, nullable=True)
    image_url = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)
    bbox = Column(JSON, nullable=True)
    model_versions = Column(JSON, nullable=True)
    qc_json = Column(JSON, nullable=True)
    status = Column(String, default="auto")