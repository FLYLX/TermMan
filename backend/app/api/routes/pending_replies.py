import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, SessionDep
from app.models import Item
from app.services.agent.reply_ticket import reply_ticket_manager

router = APIRouter(prefix="/pending-replies", tags=["pending-replies"])


class PendingReplySendRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


def _get_accessible_item(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Item:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return item


@router.get("/{item_id}")
def list_pending_replies(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)
    items = reply_ticket_manager.list_pending_replies(str(item_id))
    return {"items": items, "count": len(items)}


@router.delete("/{item_id}/{entry_id}")
def delete_pending_reply(
    item_id: uuid.UUID,
    entry_id: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)
    ticket = reply_ticket_manager.get(entry_id)
    if not ticket or ticket.item_id != str(item_id):
        raise HTTPException(status_code=404, detail="Pending reply not found")
    if not reply_ticket_manager.delete_pending_reply(
        entry_id,
        reason="Manually deleted from TermMan",
    ):
        raise HTTPException(status_code=404, detail="Pending reply not found")
    return {"message": "Pending reply deleted"}


@router.post("/{item_id}/{entry_id}/send")
def send_pending_reply(
    item_id: uuid.UUID,
    entry_id: str,
    request: PendingReplySendRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)
    ticket = reply_ticket_manager.get(entry_id)
    if not ticket or ticket.item_id != str(item_id):
        raise HTTPException(status_code=404, detail="Pending reply not found")
    delivered, detail = reply_ticket_manager.send_pending_reply(
        entry_id,
        request.content,
    )
    if not delivered:
        raise HTTPException(status_code=409, detail=detail)
    return {"message": "Pending reply sent", "destination": detail}
