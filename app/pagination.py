"""Shared pagination, sorting and CSV export for admin lists.

Replaces the hard `LIMIT 200` that silently truncated every admin table.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Any

from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200


@dataclass
class Page:
    items: list[Any]
    total: int
    page: int
    per_page: int

    @property
    def pages(self) -> int:
        return max(1, (self.total + self.per_page - 1) // self.per_page)

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def start(self) -> int:
        return 0 if not self.total else (self.page - 1) * self.per_page + 1

    @property
    def end(self) -> int:
        return min(self.page * self.per_page, self.total)


async def paginate(
    db: AsyncSession, stmt, page: int = 1, per_page: int = DEFAULT_PER_PAGE
) -> Page:
    page = max(1, page)
    per_page = min(max(1, per_page), MAX_PER_PAGE)
    total = (
        await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    ).scalar_one()
    rows = await db.execute(stmt.limit(per_page).offset((page - 1) * per_page))
    return Page(items=list(rows.scalars().all()), total=total, page=page, per_page=per_page)


def sort_stmt(stmt, model, sort: str, allowed: set[str], default: str):
    """Apply `?sort=field` / `?sort=-field` (descending) from an allowlist."""
    field = sort.lstrip("-") or default
    if field not in allowed:
        field = default
    column = getattr(model, field, None)
    if column is None:
        return stmt
    return stmt.order_by(column.desc() if sort.startswith("-") else column.asc())


def csv_response(filename: str, headers: list[str], rows) -> StreamingResponse:
    """Stream rows as a CSV download."""
    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        yield buf.getvalue()
        buf.seek(0), buf.truncate(0)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])
            yield buf.getvalue()
            buf.seek(0), buf.truncate(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
