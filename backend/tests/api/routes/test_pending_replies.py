from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.services.agent.history.chat import get_chat_messages
from app.services.agent.reply_ticket import reply_ticket_manager
from tests.utils.item import create_random_item


def _agent() -> SimpleNamespace:
    return SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="",
            robot_context_token="",
            reply_ticket_id="",
        )
    )


def test_pending_reply_api_lists_sends_and_removes_after_delivery(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    item = create_random_item(db)
    item_id = str(item.id)
    reply_ticket_manager.reset()
    try:
        ticket = reply_ticket_manager.create_for_agent(
            _agent(),
            item_id=item_id,
            handler_id="handler-1",
            message="Report this result to the same web chat.",
            source_type="web",
        )
        reply_ticket_manager.upsert_pending_reply(
            ticket.ticket_id,
            requester="web user",
            task_plan=["Run task", "Verify", "Report"],
            status="ready",
        )

        list_response = client.get(
            f"{settings.API_V1_STR}/pending-replies/{item.id}",
            headers=superuser_token_headers,
        )
        assert list_response.status_code == 200
        assert list_response.json()["count"] == 1
        assert list_response.json()["items"][0]["destination_type"] == "web"

        send_response = client.post(
            f"{settings.API_V1_STR}/pending-replies/{item.id}/{ticket.ticket_id}/send",
            headers=superuser_token_headers,
            json={"content": "The task completed successfully."},
        )
        assert send_response.status_code == 200
        assert reply_ticket_manager.get(ticket.ticket_id) is None
        assert get_chat_messages(item_id)[-1]["content"] == (
            "The task completed successfully."
        )

        empty_response = client.get(
            f"{settings.API_V1_STR}/pending-replies/{item.id}",
            headers=superuser_token_headers,
        )
        assert empty_response.status_code == 200
        assert empty_response.json() == {"items": [], "count": 0}
    finally:
        reply_ticket_manager.reset()


def test_pending_reply_api_manual_delete(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    item = create_random_item(db)
    reply_ticket_manager.reset()
    try:
        ticket = reply_ticket_manager.create_for_agent(
            _agent(),
            item_id=str(item.id),
            handler_id="handler-1",
            message="Cancelled work",
            source_type="web",
        )
        reply_ticket_manager.upsert_pending_reply(ticket.ticket_id)

        response = client.delete(
            f"{settings.API_V1_STR}/pending-replies/{item.id}/{ticket.ticket_id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == 200
        assert reply_ticket_manager.get(ticket.ticket_id) is None
    finally:
        reply_ticket_manager.reset()
