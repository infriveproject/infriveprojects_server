"""Project / folder location API — where a site actually is on the ground.

Data only. The mobile app reads the device GPS and renders the map, so no
endpoint here builds a map link or assumes a map provider.

You pin the project heads ("AAI Imphal Airpot", "University of Delhi"); every
folder beneath inherits those coordinates through /location/resolved, so a
sub-folder is already covered without a pin of its own.

Writing is currently limited to those heads — see PINNABLE_DEPTH_LEVEL in the
service. Opening it up to a specific sub-folder later (e.g. "Earthwork") is a
one-line change there; this layer and the schema already allow any stage_id.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth import get_current_user
from src.app.database import get_db
from src.app.models.user import User
from src.app.schemas.stage_location import (
    RecordLocationResolved,
    ResolvedStageLocation,
    StageLocationList,
    StageLocationResponse,
    StageLocationUpsert,
)
from src.app.services.stage_location_service import (
    StageLocationService,
    StageNotFoundError,
    StageNotPinnableError,
)

logger = logging.getLogger(__name__)

# Every path here is /stages/{stage_id}/location[...], so it never collides
# with the /stages/{stage_id} routes registered ahead of it.
router = APIRouter(prefix="/stages", tags=["Project Locations"])

# Bulk listing on its own prefix, so it is not swallowed by /stages/{stage_id}.
locations_router = APIRouter(prefix="/stage-locations", tags=["Project Locations"])

# Resolved location of a single inspection, answered from its folder.
records_router = APIRouter(prefix="/form-records", tags=["Project Locations"])


async def _require_edit_permission(db: AsyncSession, user: User, stage_id: str) -> None:
    """Setting a site location is editing the folder, so reuse can_edit."""
    from src.app.services.permission_service import PermissionService

    has_perm = await PermissionService(db).check_stage_permission(
        user.user_id, stage_id, "can_edit"
    )
    if not has_perm:
        raise HTTPException(
            status_code=403, detail="You do not have permission to edit this stage"
        )


@router.put("/{stage_id}/location", response_model=StageLocationResponse)
async def set_stage_location(
    stage_id: str,
    payload: StageLocationUpsert,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pin a project folder to a point on the ground.

    Idempotent — re-sending replaces the stored point. Only project heads
    (depth 1) accept a pin for now; a deeper folder is rejected with 400
    because it already inherits its project's location.
    """
    await _require_edit_permission(db, current_user, stage_id)

    service = StageLocationService(db)
    try:
        return await service.upsert(stage_id, payload, created_by=current_user.user_id)
    except StageNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StageNotPinnableError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{stage_id}/location", response_model=StageLocationResponse)
async def get_stage_location(
    stage_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a folder's OWN location. 404 if it has none of its own.

    Use /location/resolved to include what it inherits from its project.
    """
    location = await StageLocationService(db).get(stage_id)
    if not location:
        raise HTTPException(status_code=404, detail="No location stored for this stage")
    return location


@router.get("/{stage_id}/location/resolved", response_model=ResolvedStageLocation)
async def get_resolved_stage_location(
    stage_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The location that applies to this folder — its own, else its project's.

    This is the endpoint the mobile app should call: it works for any folder at
    any depth, and `is_own` / `inherited_from` say where the answer came from.
    """
    try:
        location = await StageLocationService(db).resolve(stage_id)
    except StageNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not location:
        raise HTTPException(
            status_code=404, detail="No location stored for this stage or any of its parents"
        )
    return location


@router.delete("/{stage_id}/location", status_code=204)
async def delete_stage_location(
    stage_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a folder's own pin. Folders below it fall back to inheriting."""
    await _require_edit_permission(db, current_user, stage_id)

    deleted = await StageLocationService(db).delete(stage_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No location stored for this stage")


@locations_router.get("", response_model=StageLocationList)
async def list_stage_locations(
    heads_only: bool = Query(
        False, description="Only the project heads (depth 1), skipping any deeper pins"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List every pinned folder, with its name and path for labelling a pin."""
    items, total = await StageLocationService(db).list_locations(
        heads_only=heads_only, skip=skip, limit=limit
    )
    return StageLocationList(items=items, total=total)


@records_router.get("/{record_id}/location/resolved", response_model=RecordLocationResolved)
async def get_resolved_record_location(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Where an inspection took place.

    Prefers a GPS reading captured against that record; otherwise answers from
    the folder it belongs to. `origin` says which of the two it used.
    """
    location = await StageLocationService(db).resolve_for_record(record_id)
    if not location:
        raise HTTPException(
            status_code=404, detail="No location available for this record or its folder"
        )
    return location
