"""SQLAlchemy model for the GPS location of a project / folder (stage).

One location per stage — stage_id is the primary key. In practice only the
project heads ("AAI Imphal Airport", "University of Delhi") carry a row; every
folder beneath them inherits it by walking lineage_path upwards. Adding a pin
to a deeper folder later (e.g. "Earthwork") needs no schema change.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.sql import func

from src.app.database import Base


class StageLocation(Base):
    """Where on the ground a project/folder is."""

    __tablename__ = "stage_locations"

    stage_id = Column(
        String(50),
        ForeignKey("stages.stage_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    # WGS84 degrees; 6 decimals is finer than any phone GPS can resolve.
    latitude = Column(Numeric(9, 6), nullable=False)
    longitude = Column(Numeric(9, 6), nullable=False)

    # Site extent in metres — the boundary the mobile app can draw, and what a
    # later "was this inspection on site?" check would measure against.
    radius_m = Column(Integer, nullable=True)
    altitude_m = Column(Numeric(8, 2), nullable=True)

    address = Column(Text, nullable=True)

    # Optional link to the admin `locations` lookup used for permission
    # scoping: that row says which region, these coordinates say where.
    location_id = Column(
        String(36), ForeignKey("locations.location_id", ondelete="SET NULL"), nullable=True
    )

    source = Column(String(20), nullable=False, default="manual")

    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="chk_sl_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="chk_sl_longitude"),
        CheckConstraint("radius_m IS NULL OR radius_m > 0", name="chk_sl_radius"),
        CheckConstraint(
            "source IN ('device_gps', 'manual', 'map_pick', 'import')", name="chk_sl_source"
        ),
        Index("idx_stage_locations_latlng", "latitude", "longitude"),
        Index("idx_stage_locations_location", "location_id"),
    )

    def __repr__(self):
        return (
            f"<StageLocation(stage_id={self.stage_id}, "
            f"lat={self.latitude}, lng={self.longitude})>"
        )
