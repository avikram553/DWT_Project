from __future__ import annotations
from datetime import date, datetime
from typing import Optional
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime,
    Enum, ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from geoalchemy2 import Geometry
from api.db import Base

import enum


class RegionLevel(str, enum.Enum):
    state = "state"
    district = "district"
    municipality = "municipality"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    last_checked: Mapped[Optional[date]] = mapped_column(Date)

    import_runs: Mapped[list[ImportRun]] = relationship(back_populates="source")
    indicators: Mapped[list[Indicator]] = relationship(back_populates="source")


class ImportRun(Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sources.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    file_url: Mapped[Optional[str]] = mapped_column(Text)
    file_hash_sha256: Mapped[Optional[str]] = mapped_column(Text)
    rows_inserted: Mapped[Optional[int]] = mapped_column(Integer)
    rows_updated: Mapped[Optional[int]] = mapped_column(Integer)
    rows_skipped: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    source_timestamp: Mapped[Optional[date]] = mapped_column(Date)

    source: Mapped[Optional[Source]] = relationship(back_populates="import_runs")


class Region(Base):
    __tablename__ = "regions"

    # AGS is always TEXT — never cast to integer (leading-zero bug)
    ags: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[RegionLevel] = mapped_column(
        Enum(RegionLevel, name="region_level"), nullable=False
    )
    parent_ags: Mapped[Optional[str]] = mapped_column(ForeignKey("regions.ags"))
    # Denormalised from indicator_values for Q7 ≥50k filter — avoids joining 300k rows per request
    population_latest: Mapped[Optional[int]] = mapped_column(BigInteger)
    geom: Mapped[Optional[object]] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    import_run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("import_runs.id"))

    children: Mapped[list[Region]] = relationship(back_populates="parent")
    parent: Mapped[Optional[Region]] = relationship(back_populates="children", remote_side=[ags])
    accidents: Mapped[list[Accident]] = relationship(back_populates="region")
    indicator_values: Mapped[list[IndicatorValue]] = relationship(back_populates="region")
    accident_zones: Mapped[list[AccidentZone]] = relationship(back_populates="region")
    history_entries: Mapped[list[RegionHistory]] = relationship(
        back_populates="new_region", foreign_keys="RegionHistory.new_ags"
    )


class LookupCode(Base):
    __tablename__ = "lookup_codes"
    __table_args__ = (UniqueConstraint("category", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    label_de: Mapped[Optional[str]] = mapped_column(Text)
    label_en: Mapped[Optional[str]] = mapped_column(Text)


class Accident(Base):
    __tablename__ = "accidents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # UIDENTSTLAE for 2018+; 'sha1:...' deterministic surrogate for 2016-2017
    accident_uid: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month: Mapped[Optional[int]] = mapped_column(SmallInteger)
    hour: Mapped[Optional[int]] = mapped_column(SmallInteger)
    day_of_week: Mapped[Optional[int]] = mapped_column(SmallInteger)  # 1=Sunday…7=Saturday
    category: Mapped[Optional[int]] = mapped_column(SmallInteger)     # 1=fatal, 2=serious, 3=light
    kind: Mapped[Optional[int]] = mapped_column(SmallInteger)
    type: Mapped[Optional[int]] = mapped_column(SmallInteger)
    light: Mapped[Optional[int]] = mapped_column(SmallInteger)
    road_condition: Mapped[Optional[int]] = mapped_column(SmallInteger)
    participant_car: Mapped[Optional[bool]] = mapped_column(Boolean)
    participant_bike: Mapped[Optional[bool]] = mapped_column(Boolean)
    participant_moped: Mapped[Optional[bool]] = mapped_column(Boolean)
    participant_truck: Mapped[Optional[bool]] = mapped_column(Boolean)
    participant_pedestrian: Mapped[Optional[bool]] = mapped_column(Boolean)
    participant_other: Mapped[Optional[bool]] = mapped_column(Boolean)
    lat: Mapped[Optional[float]] = mapped_column()
    lon: Mapped[Optional[float]] = mapped_column()
    geom: Mapped[Optional[object]] = mapped_column(Geometry("POINT", srid=4326))
    region_id: Mapped[Optional[str]] = mapped_column(ForeignKey("regions.ags"))
    import_run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("import_runs.id"))

    region: Mapped[Optional[Region]] = relationship(back_populates="accidents")


class Indicator(Base):
    __tablename__ = "indicators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sources.id"))

    source: Mapped[Optional[Source]] = relationship(back_populates="indicators")
    values: Mapped[list[IndicatorValue]] = relationship(back_populates="indicator")


class IndicatorValue(Base):
    __tablename__ = "indicator_values"

    indicator_id: Mapped[int] = mapped_column(ForeignKey("indicators.id"), primary_key=True)
    region_id: Mapped[str] = mapped_column(ForeignKey("regions.ags"), primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False, primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    import_run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("import_runs.id"))

    indicator: Mapped[Indicator] = relationship(back_populates="values")
    region: Mapped[Region] = relationship(back_populates="indicator_values")


class AccidentZone(Base):
    __tablename__ = "accident_zones"
    __table_args__ = (CheckConstraint("kind IN ('hotspot', 'safe')", name="ck_zone_kind"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    accident_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    year_from: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    year_to: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    region_id: Mapped[Optional[str]] = mapped_column(ForeignKey("regions.ags"))
    # EPSG:25832 metric SRID — KNN distance only meaningful in metric coordinate system
    cell_geom_proj: Mapped[object] = mapped_column(Geometry("POLYGON", srid=25832), nullable=False)
    # WGS84 for API/frontend output
    cell_geom: Mapped[object] = mapped_column(Geometry("POLYGON", srid=4326), nullable=False)
    import_run_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("import_runs.id"))

    region: Mapped[Optional[Region]] = relationship(back_populates="accident_zones")


class RegionHistory(Base):
    __tablename__ = "regions_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    old_ags: Mapped[str] = mapped_column(Text, nullable=False)
    new_ags: Mapped[str] = mapped_column(ForeignKey("regions.ags"), nullable=False)
    change_date: Mapped[Optional[date]] = mapped_column(Date)
    change_type: Mapped[Optional[str]] = mapped_column(Text)
    source_note: Mapped[Optional[str]] = mapped_column(Text)

    new_region: Mapped[Region] = relationship(
        back_populates="history_entries", foreign_keys=[new_ags]
    )
