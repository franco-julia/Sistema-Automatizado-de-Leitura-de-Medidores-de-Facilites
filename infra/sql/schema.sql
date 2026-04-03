-- Esquema mínimo (PostgreSQL compatível)
CREATE TABLE IF NOT EXISTS meters (
  id UUID PRIMARY KEY,
  account_id UUID,
  utility TEXT CHECK (utility IN ('water','gas','power')),
  type TEXT CHECK (type IN ('digital','analog')),
  serial TEXT,
  multiplier NUMERIC DEFAULT 1.0,
  installed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS readings (
  id UUID PRIMARY KEY,
  meter_id UUID REFERENCES meters(id),
  ts TIMESTAMP NOT NULL,
  value NUMERIC NOT NULL,
  unit TEXT CHECK (unit IN ('kWh','m3','m³')),
  confidence NUMERIC CHECK (confidence >= 0 AND confidence <= 1),
  image_url TEXT,
  bbox JSONB,
  model_versions JSONB,
  qc_json JSONB,
  status TEXT DEFAULT 'auto' CHECK (status IN ('auto','user_fixed','rejected'))
);

CREATE INDEX IF NOT EXISTS idx_readings_meter_ts ON readings (meter_id, ts);