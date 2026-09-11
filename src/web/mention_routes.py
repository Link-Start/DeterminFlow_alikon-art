"""Read-only, session-aware resource discovery for @ mentions."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from src.resources.mentions import list_mention_resources

router = APIRouter(prefix="/api", tags=["resource-mentions"])
ResourceType = Literal["prompt", "agent", "skill", "rule", "workflow", "session"]


@router.get("/sessions/{session_id}/mention-resources")
async def get_mention_resources(
    session_id: str,
    request: Request,
    resource_type: ResourceType,
    q: str = Query(default="", max_length=256),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    state = request.app.state
    session = state.session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="未找到当前会话")
    return list_mention_resources(
        resource_type, state, session, query=q, offset=offset, limit=limit,
    )
