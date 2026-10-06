"""My Document API endpoints — superadmin-only document library.

Hierarchy: Folder -> Document. Folders cannot be nested.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth import require_superadmin
from src.app.database import get_db
from src.app.models.user import User
from src.app.schemas.my_document import (
    MyDocumentFolderCreate,
    MyDocumentFolderResponse,
    MyDocumentRemarkUpdate,
    MyDocumentResponse,
)
from src.app.services.my_document_service import DuplicateFolderNameError, MyDocumentService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["My Documents"])

MAX_SIZE = 20 * 1024 * 1024  # 20MB


# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------

@router.get("/folders", response_model=List[MyDocumentFolderResponse])
async def list_folders(
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """List the current superadmin's folders. Folders cannot be nested."""
    service = MyDocumentService(db)
    return await service.list_folders(created_by=current_user.user_id)


@router.post("/folders", response_model=MyDocumentFolderResponse, status_code=201)
async def create_folder(
    payload: MyDocumentFolderCreate,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new folder at the root of My Documents. Nesting is not supported."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name cannot be empty")

    service = MyDocumentService(db)
    try:
        return await service.create_folder(name=name, created_by=current_user.user_id)
    except DuplicateFolderNameError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/folders/{folder_id}", response_model=MyDocumentFolderResponse)
async def get_folder(
    folder_id: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single folder by ID. 404 if it doesn't exist or isn't yours."""
    service = MyDocumentService(db)
    folder = await service.get_folder(folder_id, created_by=current_user.user_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a folder and its documents."""
    service = MyDocumentService(db)
    deleted = await service.delete_folder(folder_id, created_by=current_user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Folder not found")


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@router.get("", response_model=List[MyDocumentResponse])
async def list_documents(
    folder_id: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """List PDFs inside a folder. Documents never live outside a folder."""
    service = MyDocumentService(db)
    try:
        return await service.list_documents(uploaded_by=current_user.user_id, folder_id=folder_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("", response_model=MyDocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    folder_id: str = Form(...),
    remark: Optional[str] = Form(None),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF into a folder, with an optional remark. A document can never be
    uploaded outside a folder — omitting folder_id is rejected at the request level
    (missing required form field)."""
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    file_data = await file.read()
    if len(file_data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds the maximum limit of 20MB")

    service = MyDocumentService(db)
    try:
        return await service.upload_document(
            file_data=file_data,
            file_name=file.filename,
            content_type=file.content_type,
            uploaded_by=current_user.user_id,
            folder_id=folder_id,
            remark=(remark.strip() if remark and remark.strip() else None),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{document_id}/remark", response_model=MyDocumentResponse)
async def update_document_remark(
    document_id: str,
    payload: MyDocumentRemarkUpdate,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Set or clear the remark on a document."""
    service = MyDocumentService(db)
    remark = payload.remark.strip() if payload.remark and payload.remark.strip() else None
    doc = await service.update_remark(document_id, uploaded_by=current_user.user_id, remark=remark)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{document_id}/url")
async def get_document_url(
    document_id: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Get a presigned URL to view/download a PDF from the library."""
    from datetime import timedelta

    from src.app.storage import storage_service

    service = MyDocumentService(db)
    doc = await service.get_document(document_id, uploaded_by=current_user.user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    url = storage_service.generate_presigned_url(
        object_name=doc.file_path,
        expires=timedelta(hours=1),
        response_headers={"response-content-disposition": f'inline; filename="{doc.file_name}"'},
    )
    if not url:
        raise HTTPException(status_code=500, detail="Failed to generate presigned URL")
    return {"url": url}


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a PDF from the current superadmin's document library."""
    service = MyDocumentService(db)
    deleted = await service.delete_document(document_id, uploaded_by=current_user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
