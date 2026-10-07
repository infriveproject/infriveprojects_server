"""SQLAlchemy model for the fixed comment text attached to each rating value.

Five rows, one per star value. The reviewer picks a rating and this supplies
the comment, so the wording is identical on every record.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, SmallInteger, Text
from sqlalchemy.sql import func

from src.app.database import Base


class RatingCommentPreset(Base):
    """The agreed wording for one rating value."""

    __tablename__ = "rating_comment_presets"

    # The rating itself is the key — there can never be two competing texts
    # for the same score.
    rating = Column(SmallInteger, primary_key=True)
    comment_text = Column(Text, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="chk_rcp_rating"),
        CheckConstraint("btrim(comment_text) <> ''", name="chk_rcp_text"),
    )

    def __repr__(self):
        return f"<RatingCommentPreset(rating={self.rating})>"
