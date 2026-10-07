"""Service for inspection (form record) ratings.

Stores the 1-5 score and remark a reviewer gives an inspection, and hands
them back for a single record or as a filtered list for reporting.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.models.form_record import FormRecord
from src.app.models.form_record_rating import FormRecordRating
from src.app.services.rating_comment_preset_service import RatingCommentPresetService
from src.app.schemas.form_record_rating import (
    FormRecordRatingListItem,
    FormRecordRatingResponse,
    FormRecordRatingUpsert,
)

logger = logging.getLogger(__name__)


class RecordNotFoundError(Exception):
    """Raised when the inspection being rated does not exist."""


class PresetNotConfiguredError(Exception):
    """Raised when no comment text is configured for the chosen rating."""


class FormRecordRatingService:
    """Service for FormRecordRating operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, record_id: str) -> Optional[FormRecordRatingResponse]:
        """Return an inspection's rating, or None if it was never rated."""
        result = await self.db.execute(
            select(FormRecordRating).where(FormRecordRating.record_id == record_id)
        )
        row = result.scalar_one_or_none()
        return FormRecordRatingResponse.model_validate(row) if row else None

    async def get_many(self, record_ids: List[str]) -> dict:
        """Return {record_id: rating} for the given records, in one query.

        Used by list views, which would otherwise issue a query per row.
        Records with no rating are simply absent from the result.
        """
        if not record_ids:
            return {}

        result = await self.db.execute(
            select(FormRecordRating).where(FormRecordRating.record_id.in_(record_ids))
        )
        return {
            row.record_id: FormRecordRatingResponse.model_validate(row)
            for row in result.scalars().all()
        }

    async def upsert(
        self,
        record_id: str,
        payload: FormRecordRatingUpsert,
        rated_by: Optional[str] = None,
    ) -> FormRecordRatingResponse:
        """Rate an inspection, replacing any previous rating.

        An inspection carries exactly one rating, so a reviewer who changes
        their mind overwrites the earlier score instead of adding a row.
        """
        exists = await self.db.execute(
            select(FormRecord.record_id).where(FormRecord.record_id == record_id)
        )
        if exists.scalar_one_or_none() is None:
            raise RecordNotFoundError(f"Form record {record_id} not found")

        comment_text = await RatingCommentPresetService(self.db).get_text(payload.rating)
        if not comment_text:
            raise PresetNotConfiguredError(
                f"No comment text is configured for a rating of {payload.rating}"
            )

        result = await self.db.execute(
            select(FormRecordRating).where(FormRecordRating.record_id == record_id)
        )
        row = result.scalar_one_or_none()

        if row is None:
            row = FormRecordRating(record_id=record_id)
            self.db.add(row)

        row.rating = payload.rating
        # Always the configured wording for this score — never payload.comment.
        row.comment = comment_text
        row.remark = payload.remark
        row.rated_at = datetime.now(timezone.utc)
        if rated_by is not None:
            row.rated_by = rated_by

        await self.db.commit()
        await self.db.refresh(row)

        logger.info("Rated inspection %s as %s/5", record_id, payload.rating)
        return FormRecordRatingResponse.model_validate(row)

    async def delete(self, record_id: str) -> bool:
        """Remove an inspection's rating. Returns False if it had none."""
        result = await self.db.execute(
            delete(FormRecordRating).where(FormRecordRating.record_id == record_id)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def list_ratings(
        self,
        project_stage_id: Optional[str] = None,
        stage_id: Optional[str] = None,
        form_type_id: Optional[str] = None,
        max_rating: Optional[int] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> Tuple[List[FormRecordRatingListItem], int, Optional[float]]:
        """List stored ratings, lowest score first so problems surface on top.

        Returns the page, the total matching the filter, and the mean score
        across all matches (not just this page, so paging never shifts it).
        """
        filters = []
        if project_stage_id:
            filters.append(FormRecord.project_stage_id == project_stage_id)
        if stage_id:
            filters.append(FormRecord.stage_id == stage_id)
        if form_type_id:
            filters.append(FormRecord.form_type_id == form_type_id)
        if max_rating is not None:
            filters.append(FormRecordRating.rating <= max_rating)

        base = select(FormRecordRating, FormRecord).join(
            FormRecord, FormRecord.record_id == FormRecordRating.record_id
        )
        if filters:
            base = base.where(*filters)

        # Count and average in one pass — both are aggregates over the same
        # filtered set, so there is no reason to hit the table twice.
        agg_stmt = (
            select(func.count(), func.avg(FormRecordRating.rating))
            .select_from(FormRecordRating)
            .join(FormRecord, FormRecord.record_id == FormRecordRating.record_id)
        )
        if filters:
            agg_stmt = agg_stmt.where(*filters)
        total, average = (await self.db.execute(agg_stmt)).one()

        result = await self.db.execute(
            base.order_by(
                FormRecordRating.rating.asc(), FormRecordRating.rated_at.desc().nullslast()
            )
            .offset(skip)
            .limit(limit)
        )

        items: List[FormRecordRatingListItem] = []
        for rating_row, record in result.all():
            item = FormRecordRatingListItem.model_validate(rating_row)
            item.docname = record.docname
            item.form_type_id = record.form_type_id
            item.stage_id = record.stage_id
            item.project_stage_id = record.project_stage_id
            item.status = record.status
            items.append(item)

        return items, total, round(float(average), 2) if average is not None else None
