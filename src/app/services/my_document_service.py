"""Service for the superadmin 'My Document' library.

Hierarchy: MyDocumentFolder -> MyDocument. Folders cannot be nested.
"""

import logging
import uuid
from typing import List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.models.my_document import MyDocument, MyDocumentFolder
from src.app.schemas.my_document import MyDocumentFolderResponse, MyDocumentResponse
from src.app.storage import storage_service

logger = logging.getLogger(__name__)


class DuplicateFolderNameError(Exception):
    """Raised when a superadmin already has a folder with this name (case-insensitive)."""


class MyDocumentService:
    """Service for MyDocument operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------

    async def list_folders(self, created_by: str) -> List[MyDocumentFolderResponse]:
        """List the folders owned by a given user. Folders cannot be nested."""
        result = await self.db.execute(
            select(MyDocumentFolder)
            .where(MyDocumentFolder.created_by == created_by)
            .order_by(MyDocumentFolder.name.asc())
        )
        return [MyDocumentFolderResponse.model_validate(f) for f in result.scalars().all()]

    async def create_folder(self, name: str, created_by: str) -> MyDocumentFolderResponse:
        """Create a new folder at the root of My Documents. Nested folders are not supported.

        Folder names must be unique (case-insensitive) within the creator's own
        library — two different superadmins may still each have their own
        "Site Reports" folder.
        """
        existing = await self.db.execute(
            select(MyDocumentFolder).where(
                MyDocumentFolder.created_by == created_by,
                func.lower(MyDocumentFolder.name) == name.lower(),
            )
        )
        if existing.scalar_one_or_none():
            raise DuplicateFolderNameError(f'A folder named "{name}" already exists')

        new_folder = MyDocumentFolder(
            folder_id=str(uuid.uuid4()),
            name=name,
            created_by=created_by,
        )
        self.db.add(new_folder)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise DuplicateFolderNameError(f'A folder named "{name}" already exists')
        await self.db.refresh(new_folder)
        return MyDocumentFolderResponse.model_validate(new_folder)

    async def _get_owned_folder(self, folder_id: str, created_by: str) -> Optional[MyDocumentFolder]:
        result = await self.db.execute(
            select(MyDocumentFolder).where(
                MyDocumentFolder.folder_id == folder_id,
                MyDocumentFolder.created_by == created_by,
            )
        )
        return result.scalar_one_or_none()

    async def get_folder(self, folder_id: str, created_by: str) -> Optional[MyDocumentFolderResponse]:
        """Fetch a single folder owned by created_by. Returns None if not found."""
        folder = await self._get_owned_folder(folder_id, created_by)
        return MyDocumentFolderResponse.model_validate(folder) if folder else None

    async def delete_folder(self, folder_id: str, created_by: str) -> bool:
        """Delete a folder and its documents. Returns False if not found."""
        folder = await self._get_owned_folder(folder_id, created_by)
        if not folder:
            return False

        docs_result = await self.db.execute(
            select(MyDocument).where(MyDocument.folder_id == folder_id)
        )
        for doc in docs_result.scalars().all():
            storage_service.delete_file(doc.file_path)

        await self.db.execute(delete(MyDocumentFolder).where(MyDocumentFolder.folder_id == folder_id))
        await self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    async def list_documents(self, uploaded_by: str, folder_id: str) -> List[MyDocumentResponse]:
        """List documents inside a folder. Documents never live outside a folder."""
        folder = await self._get_owned_folder(folder_id, uploaded_by)
        if not folder:
            raise ValueError("Folder not found")

        result = await self.db.execute(
            select(MyDocument)
            .where(
                MyDocument.uploaded_by == uploaded_by,
                MyDocument.folder_id == folder_id,
            )
            .order_by(MyDocument.created_at.desc())
        )
        return [MyDocumentResponse.model_validate(doc) for doc in result.scalars().all()]

    async def upload_document(
        self,
        file_data: bytes,
        file_name: str,
        content_type: str,
        uploaded_by: str,
        folder_id: str,
        remark: Optional[str] = None,
    ) -> MyDocumentResponse:
        """Store a PDF in MinIO and record it inside a folder. A document can never be uploaded outside a folder."""
        folder = await self._get_owned_folder(folder_id, uploaded_by)
        if not folder:
            raise ValueError("Folder not found")

        document_id = str(uuid.uuid4())
        object_name = f"documents/{uploaded_by}/{document_id}_{file_name}"

        if not storage_service.upload_file(
            file_data=file_data, object_name=object_name, content_type=content_type
        ):
            raise RuntimeError("Failed to upload file to storage")

        new_doc = MyDocument(
            document_id=document_id,
            file_name=file_name,
            file_path=object_name,
            content_type=content_type,
            file_size=len(file_data),
            folder_id=folder_id,
            uploaded_by=uploaded_by,
            remark=remark,
        )
        self.db.add(new_doc)
        await self.db.commit()
        await self.db.refresh(new_doc)
        return MyDocumentResponse.model_validate(new_doc)

    async def update_remark(
        self, document_id: str, uploaded_by: str, remark: Optional[str]
    ) -> Optional[MyDocumentResponse]:
        """Set or clear a document's remark. Returns None if not found."""
        result = await self.db.execute(
            select(MyDocument).where(
                MyDocument.document_id == document_id,
                MyDocument.uploaded_by == uploaded_by,
            )
        )
        doc = result.scalar_one_or_none()
        if not doc:
            return None

        doc.remark = remark
        await self.db.commit()
        await self.db.refresh(doc)
        return MyDocumentResponse.model_validate(doc)

    async def get_document(self, document_id: str, uploaded_by: str) -> Optional[MyDocumentResponse]:
        """Fetch a single document owned by uploaded_by, regardless of folder."""
        result = await self.db.execute(
            select(MyDocument).where(
                MyDocument.document_id == document_id,
                MyDocument.uploaded_by == uploaded_by,
            )
        )
        doc = result.scalar_one_or_none()
        return MyDocumentResponse.model_validate(doc) if doc else None

    async def delete_document(self, document_id: str, uploaded_by: str) -> bool:
        """Delete a document owned by uploaded_by. Returns False if not found."""
        result = await self.db.execute(
            select(MyDocument).where(
                MyDocument.document_id == document_id,
                MyDocument.uploaded_by == uploaded_by,
            )
        )
        doc = result.scalar_one_or_none()
        if not doc:
            return False

        storage_service.delete_file(doc.file_path)
        await self.db.execute(delete(MyDocument).where(MyDocument.document_id == document_id))
        await self.db.commit()
        return True
