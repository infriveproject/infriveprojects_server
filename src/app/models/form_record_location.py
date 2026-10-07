"""SQLAlchemy model for the GPS location of an inspection (form record).

One location per record — record_id is the primary key, so capturing a
location again for the same inspection replaces the previous one.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.sql import func

from src.app.database import Base


class FormRecordLocation(Base):
    """Where on site an inspection was carried out."""

    __tablename__ = "form_record_locations"

    record_id = Column(
        String(50),
        ForeignKey("form_records.record_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    # WGS84 degrees; 6 decimals is finer than any phone GPS can resolve.
    latitude = Column(Numeric(9, 6), nullable=False)
    longitude = Column(Numeric(9, 6), nullable=False)

    # Radius in metres the device claims the true position lies within —
    # this is what tells you later whether a reading can be trusted.
    accuracy_m = Column(Numeric(8, 2), nullable=True)
    altitude_m = Column(Numeric(8, 2), nullable=True)

    address = Column(Text, nullable=True)

    source = Column(String(20), nullable=False, default="device_gps")

    captured_by = Column(String(100), nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="chk_frl_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="chk_frl_longitude"),
        CheckConstraint("accuracy_m IS NULL OR accuracy_m >= 0", name="chk_frl_accuracy"),
        CheckConstraint(
            "source IN ('device_gps', 'manual', 'map_pick', 'import')", name="chk_frl_source"
        ),
        # Bounding-box prefilter for a future "inspections near me" lookup.
        Index("idx_form_record_locations_latlng", "latitude", "longitude"),
        Index("idx_form_record_locations_captured_at", "captured_at"),
    )

    def __repr__(self):
        return (
            f"<FormRecordLocation(record_id={self.record_id}, "
            f"lat={self.latitude}, lng={self.longitude})>"
        )
