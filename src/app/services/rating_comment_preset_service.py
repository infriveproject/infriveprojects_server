"""Service for the fixed comment text attached to each rating value.

The reviewer cannot type the comment, so the text that gets stored is always
resolved here — never taken from the request body. That way a hand-crafted
API call cannot put wording on a record that was never agreed.
"""

import logging
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.models.rating_comment_preset import RatingCommentPreset

logger = logging.getLogger(__name__)


class RatingCommentPresetService:
    """Reads the agreed comment wording for a rating."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> Dict[int, str]:
        """Return {rating: text} for all five values, for rendering the UI."""
        result = await self.db.execute(
            select(RatingCommentPreset).order_by(RatingCommentPreset.rating)
        )
        return {row.rating: row.comment_text for row in result.scalars().all()}

    async def get_text(self, rating: int) -> Optional[str]:
        """Return the agreed comment for one rating, or None if unconfigured."""
        row = await self.db.get(RatingCommentPreset, rating)
        return row.comment_text if row else None
