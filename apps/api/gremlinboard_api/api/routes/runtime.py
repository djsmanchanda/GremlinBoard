from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from gremlinboard_api.db import get_session
from gremlinboard_api.repositories.board import BoardRepository, serialize_runtime_log
from gremlinboard_api.schemas.contracts import RuntimeLogRead


router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/logs", response_model=list[RuntimeLogRead])
async def list_runtime_logs(
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> list[RuntimeLogRead]:
    repository = BoardRepository(session)
    return [serialize_runtime_log(record) for record in await repository.list_runtime_logs(limit=limit)]
