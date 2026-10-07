from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, SmallInteger, String, Text, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.app.database import Base


class FormAction(Base):
    __tablename__ = "form_actions"

    action_id = Column(Integer, primary_key=True, autoincrement=True)
    record_id = Column(String(50), ForeignKey("form_records.record_id", ondelete="CASCADE"), nullable=False, index=True)
    from_state = Column(String(100), nullable=False)
    to_state = Column(String(100), nullable=False)
    action_type = Column(String(50), nullable=False)
    performed_by = Column(String(50), ForeignKey("users.user_id"), nullable=False)
    remarks = Column(Text, nullable=True)
    # Score given at this step, 1-5. Nullable because most actions carry
    # none (a cancel, or a submit where the reviewer skipped rating).
    rating = Column(SmallInteger, nullable=True)
    # Justification for that score. Nullable for the same reason rating is:
    # most actions (a cancel) carry neither.
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "rating IS NULL OR rating BETWEEN 1 AND 5", name="chk_form_actions_rating"
        ),
        CheckConstraint(
            "comment IS NULL OR (rating IS NOT NULL AND btrim(comment) <> '')",
            name="chk_form_actions_comment",
        ),
    )

    record = relationship("FormRecord", back_populates="actions")