-- CreateEnum
CREATE TYPE "Utility" AS ENUM ('water', 'gas', 'power');

-- CreateEnum
CREATE TYPE "MeterType" AS ENUM ('digital', 'analog');

-- CreateEnum
CREATE TYPE "Unit" AS ENUM ('kWh', 'm3');

-- CreateEnum
CREATE TYPE "ReadingStatus" AS ENUM ('auto', 'user_fixed', 'rejected');

-- CreateTable
CREATE TABLE "meters" (
    "id" UUID NOT NULL,
    "accountId" UUID,
    "utility" "Utility" NOT NULL,
    "type" "MeterType" NOT NULL,
    "serial" TEXT,
    "multiplier" DECIMAL(65,30) NOT NULL DEFAULT 1.0,
    "installedAt" TIMESTAMP(3),

    CONSTRAINT "meters_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "readings" (
    "id" UUID NOT NULL,
    "meterId" UUID NOT NULL,
    "ts" TIMESTAMP(3) NOT NULL,
    "value" DECIMAL(65,30) NOT NULL,
    "unit" "Unit" NOT NULL,
    "confidence" DECIMAL(65,30),
    "imageUrl" TEXT,
    "bbox" JSONB,
    "modelVersions" JSONB,
    "qcJson" JSONB,
    "status" "ReadingStatus" NOT NULL DEFAULT 'auto',

    CONSTRAINT "readings_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "readings_meterId_ts_idx" ON "readings"("meterId", "ts");

-- AddForeignKey
ALTER TABLE "readings" ADD CONSTRAINT "readings_meterId_fkey" FOREIGN KEY ("meterId") REFERENCES "meters"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
