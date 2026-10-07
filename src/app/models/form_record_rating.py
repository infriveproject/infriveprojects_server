"""SQLAlchemy model for the rating given to an inspection (form record).

One rating per record — record_id is the primary key, so re-rating the same
inspection replaces the previous score rather than adding a second row.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.sql import func

from src.app.database import Base


class FormRecordRating(Base):
    """How an inspection was rated, and why."""

    __tablename__ = "form_record_ratings"

    record_id = Column(
        String(50),
        ForeignKey("form_records.record_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    # 1 (worst) .. 5 (best), matching the 5-star picker in the UI. NOT NULL:
    # the presence of a row means "rated", so an unrated record has no row.
    rating = Column(SmallInteger, nullable=False)

    # Why that score was given. Required: a rating row may never exist
    # without its justification.
    comment = Column(Text, nullable=False)

    # Free note about the transition itself, as typed in the popup's Remarks
    # box. Optional, unlike the comment above.
    remark = Column(Text, nullable=True)

    rated_by = Column(String(100), nullable=True)
    rated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="chk_frr_rating"),
        # btrim so a comment of only spaces is rejected like an empty one.
        CheckConstraint("btrim(comment) <> ''", name="chk_frr_comment"),
        # Keeps "everything rated 2 or below" and the per-form-type averages
        # off a full table scan.
        Index("idx_form_record_ratings_rating", "rating"),
        Index("idx_form_record_ratings_rated_at", "rated_at"),
    )

    def __repr__(self):
        return f"<FormRecordRating(record_id={self.record_id}, rating={self.rating})>"
