"""SQLAlchemy models for the superadmin 'My Document' library.

Hierarchy: MyDocumentFolder -> MyDocument. Folders cannot be nested.
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from src.app.database import Base


class MyDocumentFolder(Base):
    """A top-level folder in a superadmin's 'My Document' library. Folders cannot be nested."""

    __tablename__ = "my_document_folders"

    folder_id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))

    name = Column(String(255), nullable=False)

    created_by = Column(String(36), ForeignKey("users.user_id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MyDocument(Base):
    """A PDF uploaded into a folder."""

    __tablename__ = "my_documents"

    document_id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))

    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    content_type = Column(String(100), nullable=False, default="application/pdf")
    file_size = Column(Integer, nullable=False)

    folder_id = Column(String(36), ForeignKey("my_document_folders.folder_id"), nullable=False, index=True)

    uploaded_by = Column(String(36), ForeignKey("users.user_id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    remark = Column(Text, nullable=True)
