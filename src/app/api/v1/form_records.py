from typing import List

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, File, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth import get_current_user
from src.app.database import get_db
from src.app.models.user import User
from src.app.schemas.form_record import (
    FormRecordCreate,
    FormRecordList,
    FormRecordResponse,
    FormRecordUpdate,
)
from src.app.services.form_record_service import FormRecordService
from src.app.services.user_service import UserService
from pydantic import BaseModel, Field
from typing import Optional, List

class TransitionPayload(BaseModel):
    trigger: str
    remarks: Optional[str] = None
    # 1-5 score and its justification, captured in the same popup as the
    # remark. Optional here because cancel/reject carry neither; whether
    # they are actually required depends on the trigger and is enforced
    # in process_transition against RATEABLE_TRIGGERS.
    rating: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = None

router = APIRouter(prefix="/form-records", tags=["Form Records"])


@router.post("", response_model=FormRecordResponse, status_code=201)
async def create_record(
    payload: FormRecordCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new form record. The created_by field is automatically set from the authenticated user."""
    from src.app.services.permission_service import PermissionService
    permission_service = PermissionService(db)

    has_permission = await permission_service.check_form_type_permission(
        user_id=current_user.user_id,
        form_type_id=payload.form_type_id,
        permission_type="can_create_records"
    )

    if not has_permission:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to create records of this form type"
        )
        
    svc = FormRecordService(db)
    try:
        return await svc.create(payload, created_by=current_user.user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=FormRecordList)
async def list_records(
    form_type_id: str = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    q: Optional[str] = Query(None, description="Filter by docname substring (for Link pickers)"),
    project_stage_id: Optional[str] = Query(None, description="Restrict to records belonging to this project"),
    db: AsyncSession = Depends(get_db),
):
    svc = FormRecordService(db)
    items, total = await svc.list_by_form_type(
        form_type_id, skip=skip, limit=limit, q_docname=q, project_stage_id=project_stage_id
    )
    return FormRecordList(items=items, total=total)


@router.get("/{record_id}", response_model=FormRecordResponse)
async def get_record(record_id: str, db: AsyncSession = Depends(get_db)):
    svc = FormRecordService(db)
    rec = await svc.get(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")
    return rec


@router.put("/{record_id}", response_model=FormRecordResponse)
async def update_record(
    record_id: str, payload: FormRecordUpdate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    from src.app.services.permission_service import PermissionService
    permission_service = PermissionService(db)

    # Fetch existing record to get its form_type_id
    svc = FormRecordService(db)
    existing_record = await svc.get(record_id)
    if not existing_record:
        raise HTTPException(status_code=404, detail="Record not found")

    has_permission = await permission_service.check_form_type_permission(
        user_id=current_user.user_id,
        form_type_id=existing_record.form_type_id,
        permission_type="can_edit_records"
    )

    if not has_permission:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to edit records of this form type"
        )
    svc = FormRecordService(db)
    try:
        return await svc.update(record_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{record_id}/available-actions", response_model=List[str])
async def get_available_actions(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of valid transition triggers for the current record and user."""
    user_service = UserService(db)
    result = await user_service.get_user_with_roles(current_user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    user_obj, roles = result
    
    user_data = {
        "user_id": user_obj.user_id,
        "department": user_obj.department,
        "roles": roles
    }
    
    svc = FormRecordService(db)
    return await svc.get_available_actions(record_id, user_data)


@router.post("/{record_id}/transition", response_model=FormRecordResponse)
async def transition_record(
    record_id: str,
    payload: TransitionPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Execute a state machine transition on a form record."""
    user_service = UserService(db)
    result = await user_service.get_user_with_roles(current_user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    user_obj, roles = result
    
    user_data = {
        "user_id": user_obj.user_id,
        "department": user_obj.department,
        "roles": roles
    }

    svc = FormRecordService(db)
    try:
        return await svc.process_transition(
            record_id=record_id,
            trigger=payload.trigger,
            user_data=user_data,
            remarks=payload.remarks,
            rating=payload.rating,
            comment=payload.comment,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{record_id}/upload-attachment",
    response_model=FormRecordResponse,
    summary="Upload a file for an Attach/Attach Image field",
    description=(
        "Accepts a multipart/form-data request with the file and the target field name. "
        "The file is stored in MinIO at `stage_id/form_name/field_label/filename` and "
        "the resulting path is saved into `record.data[field_name]`."
    ),
)
async def upload_attachment(
    record_id: str,
    field_name: str | None = Form(None, description="Name of the Attach field in the form schema"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    svc = FormRecordService(db)
    try:
        if not field_name:
            raise HTTPException(status_code=400, detail="Field name is required")
        file_bytes = await file.read()
        return await svc.upload_attachment(
            record_id=record_id,
            field_name=field_name,
            file_bytes=file_bytes,
            filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{record_id}", status_code=204)
async def delete_record(
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    svc = FormRecordService(db)
    rec = await svc.get(record_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")

    from src.app.services.permission_service import PermissionService
    permission_service = PermissionService(db)
    has_permission = await permission_service.check_form_type_permission(
        user_id=current_user.user_id,
        form_type_id=rec.form_type_id,
        permission_type="can_delete_records"
    )
    if not has_permission:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to delete records of this form type"
        )

    try:
        await svc.delete(record_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
