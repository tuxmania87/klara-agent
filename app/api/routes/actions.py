"""REST endpoints for managing pending actions (optional HTTP interface)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.pending_action import ActionStatus, PendingAction
from app.schemas.action import PendingActionOut, ActionApprovalResponse
from app.services.action_service import ActionService

router = APIRouter()


@router.get("", response_model=list[PendingActionOut])
async def list_actions(
    status: str = Query("pending", description="pending | approved | rejected | executed | failed"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[PendingActionOut]:
    try:
        status_enum = ActionStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status '{status}'. Choose from: {[s.value for s in ActionStatus]}")

    result = await db.execute(
        select(PendingAction)
        .where(PendingAction.status == status_enum)
        .order_by(PendingAction.created_at.desc())
        .limit(limit)
    )
    return [PendingActionOut.model_validate(a) for a in result.scalars().all()]


@router.get("/{action_id}", response_model=PendingActionOut)
async def get_action(action_id: int, db: AsyncSession = Depends(get_db)) -> PendingActionOut:
    result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404, detail=f"Action #{action_id} not found.")
    return PendingActionOut.model_validate(action)


@router.post("/{action_id}/approve", response_model=ActionApprovalResponse)
async def approve_action(action_id: int, db: AsyncSession = Depends(get_db)) -> ActionApprovalResponse:
    svc = ActionService(db)
    message = await svc.approve_and_execute(action_id)
    result = await db.execute(select(PendingAction).where(PendingAction.id == action_id))
    action = result.scalar_one_or_none()
    return ActionApprovalResponse(
        action_id=action_id,
        status=action.status if action else ActionStatus.EXECUTED,
        message=message,
    )


@router.post("/{action_id}/reject", response_model=ActionApprovalResponse)
async def reject_action(action_id: int, db: AsyncSession = Depends(get_db)) -> ActionApprovalResponse:
    svc = ActionService(db)
    await svc.reject(action_id)
    return ActionApprovalResponse(
        action_id=action_id,
        status=ActionStatus.REJECTED,
        message=f"Action #{action_id} rejected.",
    )
