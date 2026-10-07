"""Service for inspection (form record) GPS locations.

Pure persistence: store the coordinates an inspection was carried out at and
hand them back on request. Reading the device GPS and plotting the point on a
map belongs to the mobile app, so no map provider or link building lives here.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.models.form_record import FormRecord
from src.app.models.form_record_location import FormRecordLocation
from src.app.schemas.form_record_location import (
    FormRecordLocationListItem,
    FormRecordLocationResponse,
    FormRecordLocationUpsert,
)

logger = logging.getLogger(__name__)


class RecordNotFoundError(Exception):
    """Raised when the inspection a location is being attached to does not exist."""


class FormRecordLocationService:
    """Service for FormRecordLocation operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, record_id: str) -> Optional[FormRecordLocationResponse]:
        """Return the stored location for an inspection, or None if never captured."""
        result = await self.db.execute(
            select(FormRecordLocation).where(FormRecordLocation.record_id == record_id)
        )
        row = result.scalar_one_or_none()
        return FormRecordLocationResponse.model_validate(row) if row else None

    async def upsert(
        self,
        record_id: str,
        payload: FormRecordLocationUpsert,
        captured_by: Optional[str] = None,
    ) -> FormRecordLocationResponse:
        """Set an inspection's location, replacing any previously stored one.

        An inspection carries exactly one location, so a device that re-sends a
        better fix overwrites the earlier reading instead of adding a second row.
        """
        exists = await self.db.execute(
            select(FormRecord.record_id).where(FormRecord.record_id == record_id)
        )
        if exists.scalar_one_or_none() is None:
            raise RecordNotFoundError(f"Form record {record_id} not found")

        result = await self.db.execute(
            select(FormRecordLocation).where(FormRecordLocation.record_id == record_id)
        )
        row = result.scalar_one_or_none()

        captured_at = payload.captured_at or datetime.now(timezone.utc)

        if row is None:
            row = FormRecordLocation(record_id=record_id)
            self.db.add(row)

        row.latitude = payload.latitude
        row.longitude = payload.longitude
        row.accuracy_m = payload.accuracy_m
        row.altitude_m = payload.altitude_m
        row.address = payload.address
        row.source = payload.source
        row.captured_at = captured_at
        if captured_by is not None:
            row.captured_by = captured_by

        await self.db.commit()
        await self.db.refresh(row)

        logger.info("Stored location for inspection %s (source=%s)", record_id, payload.source)
        return FormRecordLocationResponse.model_validate(row)

    async def delete(self, record_id: str) -> bool:
        """Remove an inspection's stored location. Returns False if there was none."""
        result = await self.db.execute(
            delete(FormRecordLocation).where(FormRecordLocation.record_id == record_id)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def list_locations(
        self,
        project_stage_id: Optional[str] = None,
        stage_id: Optional[str] = None,
        form_type_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> Tuple[List[FormRecordLocationListItem], int]:
        """List stored inspection locations, newest capture first.

        Each item carries the inspection's docname/status alongside the
        coordinates so the mobile app can label a pin without a second call.
        """
        filters = []
        if project_stage_id:
            filters.append(FormRecord.project_stage_id == project_stage_id)
        if stage_id:
            filters.append(FormRecord.stage_id == stage_id)
        if form_type_id:
            filters.append(FormRecord.form_type_id == form_type_id)

        base = select(FormRecordLocation, FormRecord).join(
            FormRecord, FormRecord.record_id == FormRecordLocation.record_id
        )
        if filters:
            base = base.where(*filters)

        count_stmt = (
            select(func.count())
            .select_from(FormRecordLocation)
            .join(FormRecord, FormRecord.record_id == FormRecordLocation.record_id)
        )
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = (await self.db.execute(count_stmt)).scalar_one()

        result = await self.db.execute(
            base.order_by(FormRecordLocation.captured_at.desc().nullslast())
            .offset(skip)
            .limit(limit)
        )

        items: List[FormRecordLocationListItem] = []
        for loc, record in result.all():
            item = FormRecordLocationListItem.model_validate(loc)
            item.docname = record.docname
            item.form_type_id = record.form_type_id
            item.stage_id = record.stage_id
            item.project_stage_id = record.project_stage_id
            item.status = record.status
            items.append(item)

        return items, total
