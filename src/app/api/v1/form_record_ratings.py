"""Inspection rating API — a 1-5 score and a remark per form record.

One rating per record: PUT replaces whatever was there, so a reviewer who
changes their mind re-sends rather than creating a second rating.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth import get_current_user
from src.app.database import get_db
from src.app.models.user import User
from src.app.schemas.form_record_rating import (
    FormRecordRatingList,
    FormRecordRatingResponse,
    FormRecordRatingUpsert,
)
from src.app.services.form_record_rating_service import (
    FormRecordRatingService,
    PresetNotConfiguredError,
    RecordNotFoundError,
)
from src.app.services.form_record_service import FormRecordService

logger = logging.getLogger(__name__)

# Per-record endpoints. Every path here is /form-records/{record_id}/rating,
# which never collides with the /form-records/{record_id} routes.
router = APIRouter(prefix="/form-records", tags=["Record Ratings"])

# Bulk listing lives on its own prefix so it is never swallowed by the
# /form-records/{record_id} route registered ahead of it.
ratings_router = APIRouter(prefix="/record-ratings", tags=["Record Ratings"])


async def _require_rating_permission(db: AsyncSession, user: User, record_id: str) -> None:
    """Gate rating behind the record's own edit permission.

    Same gate the location module uses, which keeps "who may annotate a
    record" answered in one place. If rating should instead be a reviewer-only
    act, change permission_type to "can_verify" here — nothing else depends
    on this choice.
    """
    from src.app.services.permission_service import PermissionService

    record = await FormRecordService(db).get(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    has_permission = await PermissionService(db).check_form_type_permission(
        user_id=user.user_id,
        form_type_id=record.form_type_id,
        permission_type="can_edit_records",
    )
    if not has_permission:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to rate records of this form type",
        )


@router.put("/{record_id}/rating", response_model=FormRecordRatingResponse)
async def set_record_rating(
    record_id: str,
    payload: FormRecordRatingUpsert,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rate an inspection 1-5.

    The comment is not supplied here — it is the configured text for the
    chosen rating, looked up server-side. Idempotent: rating the same record
    again replaces the previous score.
    """
    await _require_rating_permission(db, current_user, record_id)

    service = FormRecordRatingService(db)
    try:
        return await service.upsert(record_id, payload, rated_by=current_user.user_id)
    except RecordNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PresetNotConfiguredError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{record_id}/rating", response_model=FormRecordRatingResponse)
async def get_record_rating(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return an inspection's rating, or 404 if it was never rated."""
    rating = await FormRecordRatingService(db).get(record_id)
    if not rating:
        raise HTTPException(status_code=404, detail="No rating stored for this record")
    return rating


@router.delete("/{record_id}/rating", status_code=204)
async def delete_record_rating(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an inspection's rating."""
    await _require_rating_permission(db, current_user, record_id)

    deleted = await FormRecordRatingService(db).delete(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No rating stored for this record")


@ratings_router.get("", response_model=FormRecordRatingList)
async def list_record_ratings(
    project_stage_id: Optional[str] = Query(None, description="Restrict to one project"),
    stage_id: Optional[str] = Query(None, description="Restrict to one stage/folder"),
    form_type_id: Optional[str] = Query(None, description="Restrict to one form type"),
    max_rating: Optional[int] = Query(
        None, ge=1, le=5, description="Only ratings at or below this score"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List stored ratings, lowest score first, with the average for the filter.

    Each item carries the record's docname and status alongside the score, so
    a report can be built from this one call.
    """
    items, total, average = await FormRecordRatingService(db).list_ratings(
        project_stage_id=project_stage_id,
        stage_id=stage_id,
        form_type_id=form_type_id,
        max_rating=max_rating,
        skip=skip,
        limit=limit,
    )
    return FormRecordRatingList(items=items, total=total, average_rating=average)
