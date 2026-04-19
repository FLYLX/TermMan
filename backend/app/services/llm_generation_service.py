import json
import logging
from typing import Any
from uuid import UUID

from litellm import completion
from sqlmodel import Session, select

from app.api.deps import CurrentUser
from app.models import Item, ItemHandler, ItemHandlerItem

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 120


class LlmGenerationError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _check_item_permission(item: Item, current_user: CurrentUser) -> None:
    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise LlmGenerationError("Not enough permissions", status_code=403)


def _check_item_handler_permission(
    item_handler: ItemHandler, current_user: CurrentUser
) -> None:
    if not current_user.is_superuser and item_handler.owner_id != current_user.id:
        raise LlmGenerationError("Not enough permissions", status_code=403)


def _ensure_handler_ready(item_handler: ItemHandler) -> None:
    if not item_handler.model:
        raise LlmGenerationError(
            f"ItemHandler '{item_handler.name}' has no model configured.",
            status_code=400,
        )


def get_item_handler_for_item(
    session: Session,
    item_id: UUID | str,
    current_user: CurrentUser,
) -> tuple[ItemHandler, Item]:
    item = session.get(Item, item_id)
    if not item:
        raise LlmGenerationError("Item not found", status_code=404)

    _check_item_permission(item, current_user)

    handler_item = session.exec(
        select(ItemHandlerItem).where(ItemHandlerItem.item_id == item.id)
    ).first()
    if not handler_item:
        raise LlmGenerationError(
            "No ItemHandler associated with this item. Please associate an ItemHandler first.",
            status_code=404,
        )

    item_handler = session.get(ItemHandler, handler_item.item_handler_id)
    if not item_handler:
        raise LlmGenerationError("Associated ItemHandler not found", status_code=404)

    _check_item_handler_permission(item_handler, current_user)
    _ensure_handler_ready(item_handler)
    return item_handler, item


def get_item_handler_by_id(
    session: Session,
    item_handler_id: UUID | str,
    current_user: CurrentUser,
) -> ItemHandler:
    item_handler = session.get(ItemHandler, item_handler_id)
    if not item_handler:
        raise LlmGenerationError("Item handler not found", status_code=404)

    _check_item_handler_permission(item_handler, current_user)
    _ensure_handler_ready(item_handler)
    return item_handler


def _build_completion_kwargs(
    item_handler: ItemHandler,
    *,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": item_handler.model,
        "messages": messages,
        "stream": False,
        "timeout": REQUEST_TIMEOUT,
        "temperature": 0.2,
    }
    if item_handler.api_key:
        kwargs["api_key"] = item_handler.api_key
    if item_handler.api_url:
        kwargs["api_base"] = item_handler.api_url
    return kwargs


def _extract_json_payload(text: str) -> dict[str, Any]:
    candidates: list[str] = []
    stripped = (text or "").strip()
    if stripped:
        candidates.append(stripped)

    if "```" in stripped:
        fence_parts = stripped.split("```")
        for part in fence_parts:
            part = part.strip()
            if not part:
                continue
            if part.lower().startswith("json"):
                part = part[4:].strip()
            candidates.append(part)

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload

    raise LlmGenerationError(
        "LLM returned invalid JSON. Please refine the instruction and try again.",
        status_code=502,
    )


def generate_json_payload(
    item_handler: ItemHandler,
    *,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    try:
        response = completion(
            **_build_completion_kwargs(
                item_handler,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        )
    except Exception as exc:
        logger.exception("[LLMGeneration] Failed to call completion API")
        raise LlmGenerationError(
            f"Failed to call LLM provider: {exc}",
            status_code=502,
        ) from exc

    content = ""
    choices = getattr(response, "choices", None) or []
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", "") or ""

    if not content.strip():
        raise LlmGenerationError(
            "LLM returned an empty response. Please try again.",
            status_code=502,
        )

    return _extract_json_payload(content)
