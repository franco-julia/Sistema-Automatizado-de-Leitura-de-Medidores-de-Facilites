from sqlalchemy import Column, String, DateTime, Numeric, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base
import uuid
from datetime import datetime, timezone

class Meter(Base):
    __tablename__ = "meters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    utility = Column(String, nullable=False)
    type = Column(String, nullable=False)
    serial = Column(String, nullable=True)
    multiplier = Column(Numeric, default=1.0)
    installed_at = Column(DateTime, nullable=True)

    readings = relationship("Reading", back_populates="meter")

class Reading(Base):
    __tablename__ = "readings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meter_id = Column(UUID(as_uuid=True), ForeignKey("meters.id"), nullable=False)
    ts = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    value = Column(Numeric, nullable=False)
    unit = Column(String, nullable=False)
    confidence = Column(Numeric, nullable=True)
    image_url = Column(String, nullable=True)
    bbox = Column(JSON, nullable=True)
    model_versions = Column(JSON, nullable=True)
    qc_json = Column(JSON, nullable=True)
    status = Column(String, default="auto")

    meter = relationship("Meter", back_populates="readings")