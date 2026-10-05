from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MyDocumentFolderCreate(BaseModel):
    """Schema for creating a folder. Folders always live at the root of My Documents — nesting is not supported.

    `extra = "forbid"` is deliberate: it's what turns an attempt to nest a folder
    (e.g. passing a `parent_folder_id`) into a hard 422 instead of a silently
    ignored field.
    """

    name: str

    class Config:
        extra = "forbid"


class MyDocumentFolderResponse(BaseModel):
    """Schema for a folder response."""

    folder_id: str
    name: str
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class MyDocumentResponse(BaseModel):
    """Schema for a 'My Document' response."""

    document_id: str
    file_name: str
    file_path: str
    content_type: str
    file_size: int
    folder_id: str
    uploaded_by: str
    created_at: datetime
    remark: Optional[str] = None

    class Config:
        from_attributes = True


class MyDocumentRemarkUpdate(BaseModel):
    """Schema for setting/clearing a document's remark."""

    remark: Optional[str] = None

    class Config:
        extra = "forbid"
