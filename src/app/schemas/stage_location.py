"""Pydantic schemas for project / folder (stage) GPS locations.

Storage and retrieval only — the mobile app reads the device GPS and renders
the map, so nothing here is tied to a map provider.
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

LocationSource = Literal["device_gps", "manual", "map_pick", "import"]


class StageLocationUpsert(BaseModel):
    """Payload for setting a folder's location. Re-sending replaces it."""

    latitude: float = Field(..., ge=-90, le=90, description="WGS84 latitude in degrees")
    longitude: float = Field(..., ge=-180, le=180, description="WGS84 longitude in degrees")
    radius_m: Optional[int] = Field(
        None, gt=0, description="How far the site extends from this point, in metres"
    )
    altitude_m: Optional[float] = Field(None, description="Altitude in metres, if known")
    address: Optional[str] = Field(None, description="Site address, for display and search")
    location_id: Optional[str] = Field(
        None, description="Optional link to the admin locations lookup (region/office)"
    )
    source: LocationSource = Field("manual", description="How the coordinates were obtained")

    class Config:
        extra = "forbid"


class StageLocationResponse(BaseModel):
    """A folder's own stored location."""

    stage_id: str
    latitude: float
    longitude: float
    radius_m: Optional[int] = None
    altitude_m: Optional[float] = None
    address: Optional[str] = None
    location_id: Optional[str] = None
    source: str
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResolvedStageLocation(StageLocationResponse):
    """The location that applies to a folder — its own, or the nearest ancestor's.

    `is_own` is False when the coordinates were inherited; `inherited_from` then
    names the folder they actually came from (normally the project head).
    """

    is_own: bool
    inherited_from: str
    inherited_from_name: Optional[str] = None


class StageLocationListItem(StageLocationResponse):
    """A stored folder location plus the folder's name/depth, to label a pin."""

    stage_name: Optional[str] = None
    stage_path: Optional[str] = None
    depth_level: Optional[int] = None


class StageLocationList(BaseModel):
    items: List[StageLocationListItem]
    total: int


class RecordLocationResolved(BaseModel):
    """Where an inspection took place.

    `origin` says where the answer came from: `record` (that inspection carried
    its own GPS reading) or `stage` (taken from the folder it belongs to).
    """

    record_id: str
    latitude: float
    longitude: float
    accuracy_m: Optional[float] = None
    radius_m: Optional[int] = None
    address: Optional[str] = None
    source: Optional[str] = None
    origin: Literal["record", "stage"]
    stage_id: Optional[str] = None
    stage_name: Optional[str] = None
