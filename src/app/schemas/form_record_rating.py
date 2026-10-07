"""Pydantic schemas for inspection (form record) ratings."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class FormRecordRatingUpsert(BaseModel):
    """Payload for rating an inspection. Re-sending replaces the rating.

    Only the score is given. The comment is the configured text for that
    score and is resolved server-side, never taken from this payload.
    """

    rating: int = Field(..., ge=1, le=5, description="Score from 1 (worst) to 5 (best)")
    remark: Optional[str] = Field(None, description="Free note about the rating (optional)")
    # Accepted but ignored: the stored comment is always the configured text
    # for the chosen rating, resolved server-side. Kept so an older client
    # that still sends it is not rejected outright.
    comment: Optional[str] = Field(
        None, deprecated=True, description="Ignored — derived from the rating"
    )

    class Config:
        extra = "forbid"


class FormRecordRatingResponse(BaseModel):
    """An inspection's stored rating."""

    record_id: str
    rating: int
    comment: str
    remark: Optional[str] = None
    rated_by: Optional[str] = None
    rated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FormRecordRatingListItem(FormRecordRatingResponse):
    """A stored rating plus the inspection context needed to label it in a list."""

    docname: Optional[str] = None
    form_type_id: Optional[str] = None
    stage_id: Optional[str] = None
    project_stage_id: Optional[str] = None
    status: Optional[str] = None


class FormRecordRatingList(BaseModel):
    items: List[FormRecordRatingListItem]
    total: int
    # Mean score across every rating matching the filter — not just the page
    # being returned, so paging through results never changes it.
    average_rating: Optional[float] = None
