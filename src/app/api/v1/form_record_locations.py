"""Inspection location API — stores where on site an inspection was carried out.

Data only. The mobile app reads the device GPS and renders the map; this layer
just persists the coordinates and serves them back, so no endpoint here builds
a map link or assumes a map provider.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth import get_current_user
from src.app.database import get_db
from src.app.models.user import User
from src.app.schemas.form_record_location import (
    FormRecordLocationList,
    FormRecordLocationResponse,
    FormRecordLocationUpsert,
)
from src.app.services.form_record_location_service import (
    FormRecordLocationService,
    RecordNotFoundError,
)
from src.app.services.form_record_service import FormRecordService

logger = logging.getLogger(__name__)

# Per-inspection endpoints. Every path here is /form-records/{record_id}/location,
# which never collides with the /form-records/{record_id} routes.
router = APIRouter(prefix="/form-records", tags=["Inspection Locations"])

# Bulk listing lives on its own prefix so it is never swallowed by the
# /form-records/{record_id} route registered ahead of it.
locations_router = APIRouter(prefix="/inspection-locations", tags=["Inspection Locations"])


async def _require_edit_permission(db: AsyncSession, user: User, record_id: str) -> None:
    """Reuse the record's own edit permission — attaching a location is editing it."""
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
            detail="You do not have permission to edit records of this form type",
        )


@router.put("/{record_id}/location", response_model=FormRecordLocationResponse)
async def set_record_location(
    record_id: str,
    payload: FormRecordLocationUpsert,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store the GPS location an inspection was carried out at.

    Idempotent: sending a location again for the same inspection replaces the
    previous one, so a device that gets a better fix can simply re-send.
    """
    await _require_edit_permission(db, current_user, record_id)

    service = FormRecordLocationService(db)
    try:
        return await service.upsert(record_id, payload, captured_by=current_user.user_id)
    except RecordNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{record_id}/location", response_model=FormRecordLocationResponse)
async def get_record_location(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return an inspection's stored location, or 404 if none was ever captured."""
    location = await FormRecordLocationService(db).get(record_id)
    if not location:
        raise HTTPException(status_code=404, detail="No location stored for this record")
    return location


@router.delete("/{record_id}/location", status_code=204)
async def delete_record_location(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an inspection's stored location."""
    await _require_edit_permission(db, current_user, record_id)

    deleted = await FormRecordLocationService(db).delete(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No location stored for this record")


@locations_router.get("", response_model=FormRecordLocationList)
async def list_inspection_locations(
    project_stage_id: Optional[str] = Query(None, description="Restrict to one project"),
    stage_id: Optional[str] = Query(None, description="Restrict to one stage/folder"),
    form_type_id: Optional[str] = Query(None, description="Restrict to one inspection form type"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List stored inspection locations, newest capture first.

    Each item carries the inspection's docname and status alongside the
    coordinates, so the mobile app can label every pin from this one call.
    """
    items, total = await FormRecordLocationService(db).list_locations(
        project_stage_id=project_stage_id,
        stage_id=stage_id,
        form_type_id=form_type_id,
        skip=skip,
        limit=limit,
    )
    return FormRecordLocationList(items=items, total=total)
