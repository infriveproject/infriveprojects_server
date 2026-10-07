"""Pydantic schemas for inspection (form record) GPS locations.

Storage and retrieval only — the mobile app reads the device GPS and renders
the map, so nothing here is tied to a map provider.
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

LocationSource = Literal["device_gps", "manual", "map_pick", "import"]


class FormRecordLocationUpsert(BaseModel):
    """Payload for setting an inspection's location. Re-sending replaces it."""

    latitude: float = Field(..., ge=-90, le=90, description="WGS84 latitude in degrees")
    longitude: float = Field(..., ge=-180, le=180, description="WGS84 longitude in degrees")
    accuracy_m: Optional[float] = Field(
        None, ge=0, description="Radius in metres the device reports the position as accurate to"
    )
    altitude_m: Optional[float] = Field(None, description="Altitude in metres, if the device reports it")
    address: Optional[str] = Field(None, description="Reverse-geocoded or typed address, for display only")
    source: LocationSource = Field("device_gps", description="How the coordinates were obtained")
    captured_at: Optional[datetime] = Field(
        None, description="When the device took the reading; defaults to the server time on save"
    )

    class Config:
        extra = "forbid"


class FormRecordLocationResponse(BaseModel):
    """An inspection's stored location."""

    record_id: str
    latitude: float
    longitude: float
    accuracy_m: Optional[float] = None
    altitude_m: Optional[float] = None
    address: Optional[str] = None
    source: str
    captured_by: Optional[str] = None
    captured_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FormRecordLocationListItem(FormRecordLocationResponse):
    """A stored location plus the inspection context the mobile app needs to label a pin."""

    docname: Optional[str] = None
    form_type_id: Optional[str] = None
    stage_id: Optional[str] = None
    project_stage_id: Optional[str] = None
    status: Optional[str] = None


class FormRecordLocationList(BaseModel):
    items: List[FormRecordLocationListItem]
    total: int
