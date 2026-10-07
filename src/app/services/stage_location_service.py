"""Service for project / folder (stage) GPS locations.

Pure persistence plus inheritance. The mobile app reads the device GPS and
draws the map; nothing here builds a map link or assumes a map provider.

Inheritance is the point of this table: you pin only the project heads, and
every folder underneath resolves to its project's coordinates. Pin a deeper
folder later (e.g. "Earthwork") and it transparently takes over for its own
subtree, because resolution always prefers the most specific pin.
"""

import logging
from typing import List, Optional, Tuple

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.models.form_record import FormRecord
from src.app.models.form_record_location import FormRecordLocation
from src.app.models.stage import Stage
from src.app.models.stage_location import StageLocation
from src.app.schemas.stage_location import (
    RecordLocationResolved,
    ResolvedStageLocation,
    StageLocationListItem,
    StageLocationResponse,
    StageLocationUpsert,
)

logger = logging.getLogger(__name__)

# The hidden depth-0 root. It is never a real site, so it is never a candidate
# for inheritance — a stage with no pinned ancestor below it has no location.
SYSTEM_STAGE_ID = "stage_system"

# Which depth may be pinned. Depth 1 is a project head — "University of Delhi",
# "AAI Imphal Airpot", "IT Tirupur" — and for now that is the only level that
# takes coordinates: one site, one point, which is the whole idea being shown.
#
# Reading is NOT restricted: every folder below a head already resolves to the
# head's coordinates through resolve(), so sub-folders are covered today.
#
# To allow pinning a specific sub-folder later (e.g. "Earthwork" under a
# project), set this to None. Nothing else needs to change — the schema takes
# any stage_id, and resolve() already prefers the deepest pin it finds.
PINNABLE_DEPTH_LEVEL: Optional[int] = 1


class StageNotFoundError(Exception):
    """Raised when the folder a location is being attached to does not exist."""


class StageNotPinnableError(Exception):
    """Raised when pinning a folder that is not a project head.

    Lifted by setting PINNABLE_DEPTH_LEVEL to None.
    """


class StageLocationService:
    """Service for StageLocation operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, stage_id: str) -> Optional[StageLocationResponse]:
        """Return a folder's OWN location, ignoring anything it would inherit."""
        result = await self.db.execute(
            select(StageLocation).where(StageLocation.stage_id == stage_id)
        )
        row = result.scalar_one_or_none()
        return StageLocationResponse.model_validate(row) if row else None

    async def upsert(
        self,
        stage_id: str,
        payload: StageLocationUpsert,
        created_by: Optional[str] = None,
    ) -> StageLocationResponse:
        """Set a folder's location, replacing any previously stored one.

        Only project heads are pinnable while PINNABLE_DEPTH_LEVEL is set —
        see the note on that constant.
        """
        found = await self.db.execute(
            select(Stage.stage_id, Stage.stage_name, Stage.depth_level).where(
                Stage.stage_id == stage_id
            )
        )
        stage = found.one_or_none()
        if stage is None:
            raise StageNotFoundError(f"Stage {stage_id} not found")

        if PINNABLE_DEPTH_LEVEL is not None and stage.depth_level != PINNABLE_DEPTH_LEVEL:
            raise StageNotPinnableError(
                f"'{stage.stage_name}' is at depth {stage.depth_level}. Only project "
                f"folders (depth {PINNABLE_DEPTH_LEVEL}) can be given a location; "
                "folders below one inherit it automatically."
            )

        result = await self.db.execute(
            select(StageLocation).where(StageLocation.stage_id == stage_id)
        )
        row = result.scalar_one_or_none()

        if row is None:
            row = StageLocation(stage_id=stage_id, created_by=created_by)
            self.db.add(row)

        row.latitude = payload.latitude
        row.longitude = payload.longitude
        row.radius_m = payload.radius_m
        row.altitude_m = payload.altitude_m
        row.address = payload.address
        row.location_id = payload.location_id
        row.source = payload.source

        await self.db.commit()
        await self.db.refresh(row)

        logger.info("Stored location for stage %s (source=%s)", stage_id, payload.source)
        return StageLocationResponse.model_validate(row)

    async def delete(self, stage_id: str) -> bool:
        """Remove a folder's own location. Returns False if it had none.

        Folders below it fall back to inheriting from further up.
        """
        result = await self.db.execute(
            delete(StageLocation).where(StageLocation.stage_id == stage_id)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def resolve(self, stage_id: str) -> Optional[ResolvedStageLocation]:
        """Return the location that applies to a folder — its own, else the
        nearest ancestor's. None when no folder in the chain has been pinned.

        `lineage_path` holds ancestors ONLY, root first and self excluded, so
        the candidate chain is the stage itself followed by that array
        reversed: the deepest (most specific) pin wins.
        """
        result = await self.db.execute(select(Stage).where(Stage.stage_id == stage_id))
        stage = result.scalar_one_or_none()
        if stage is None:
            raise StageNotFoundError(f"Stage {stage_id} not found")

        candidates = [stage.stage_id] + list(reversed(stage.lineage_path or []))
        candidates = [c for c in candidates if c != SYSTEM_STAGE_ID]
        if not candidates:
            return None

        rows = await self.db.execute(
            select(StageLocation, Stage.stage_name)
            .join(Stage, Stage.stage_id == StageLocation.stage_id)
            .where(StageLocation.stage_id.in_(candidates))
        )
        found = {loc.stage_id: (loc, name) for loc, name in rows.all()}

        for candidate in candidates:  # already ordered most-specific first
            if candidate in found:
                loc, name = found[candidate]
                base = StageLocationResponse.model_validate(loc)
                return ResolvedStageLocation(
                    **base.model_dump(),
                    is_own=(candidate == stage_id),
                    inherited_from=candidate,
                    inherited_from_name=name,
                )

        return None

    async def resolve_for_record(self, record_id: str) -> Optional[RecordLocationResolved]:
        """Where an inspection took place.

        Prefers a GPS reading captured against that specific record; otherwise
        falls back to the location of the folder the record belongs to.
        """
        result = await self.db.execute(
            select(FormRecord).where(FormRecord.record_id == record_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None

        own = await self.db.execute(
            select(FormRecordLocation).where(FormRecordLocation.record_id == record_id)
        )
        own_loc = own.scalar_one_or_none()
        if own_loc is not None:
            return RecordLocationResolved(
                record_id=record_id,
                latitude=float(own_loc.latitude),
                longitude=float(own_loc.longitude),
                accuracy_m=float(own_loc.accuracy_m) if own_loc.accuracy_m is not None else None,
                address=own_loc.address,
                source=own_loc.source,
                origin="record",
                stage_id=record.stage_id,
            )

        stage_id = record.stage_id or record.project_stage_id
        if not stage_id:
            return None

        try:
            inherited = await self.resolve(stage_id)
        except StageNotFoundError:
            return None
        if inherited is None:
            return None

        return RecordLocationResolved(
            record_id=record_id,
            latitude=inherited.latitude,
            longitude=inherited.longitude,
            radius_m=inherited.radius_m,
            address=inherited.address,
            source=inherited.source,
            origin="stage",
            stage_id=inherited.inherited_from,
            stage_name=inherited.inherited_from_name,
        )

    async def list_locations(
        self,
        heads_only: bool = False,
        skip: int = 0,
        limit: int = 200,
    ) -> Tuple[List[StageLocationListItem], int]:
        """List pinned folders. `heads_only` keeps just the project heads (depth 1)."""
        filters = [Stage.depth_level == 1] if heads_only else []

        base = select(StageLocation, Stage).join(Stage, Stage.stage_id == StageLocation.stage_id)
        count_stmt = (
            select(func.count())
            .select_from(StageLocation)
            .join(Stage, Stage.stage_id == StageLocation.stage_id)
        )
        if filters:
            base = base.where(*filters)
            count_stmt = count_stmt.where(*filters)

        total = (await self.db.execute(count_stmt)).scalar_one()
        result = await self.db.execute(
            base.order_by(Stage.stage_path.asc()).offset(skip).limit(limit)
        )

        items: List[StageLocationListItem] = []
        for loc, stage in result.all():
            item = StageLocationListItem.model_validate(loc)
            item.stage_name = stage.stage_name
            item.stage_path = stage.stage_path
            item.depth_level = stage.depth_level
            items.append(item)

        return items, total
