import logging
import re
from typing import Any

from .event_bus import ItemEventBus, SubscriptionEvent, SubscriptionEventType

logger = logging.getLogger(__name__)

ANSI_ESCAPE_RE = re.compile(
    r"\x1b(?:"
    r"\[[0-?]*[ -/]*[@-~]"
    r"|\][^\x07]*(?:\x07|\x1b\\)"
    r"|[PX^_].*?\x1b\\"
    r"|[@-Z\\-_=>]"
    r")"
)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_terminal_text(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = ANSI_ESCAPE_RE.sub("", text)
    text = CONTROL_CHAR_RE.sub("", text)
    return text


def sanitize_terminal_stream_data(data: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(data)
    for key in ("stdout", "stderr"):
        if key in sanitized:
            sanitized[key] = sanitize_terminal_text(sanitized.get(key))
    return sanitized


class TerminalStreamPipeline:
    """
    Dispatch terminal stream payloads through the shared event timeline.

    The pipeline itself is intentionally narrow:
    - create a structured stream event
    - publish it to the event bus

    Log persistence remains a normal subscriber on the bus, and agent handling is
    invoked separately by the subscription center after subscribers have run.
    """

    def __init__(self, event_bus: ItemEventBus):
        self._event_bus = event_bus

    def publish_stream(self, item_uuid: str, data: dict[str, Any]) -> int:
        logger.info("[TerminalStreamPipeline] publish_stream called for item %s", item_uuid)
        data = sanitize_terminal_stream_data(data)
        event = SubscriptionEvent(
            event_type=SubscriptionEventType.STREAM,
            item_uuid=item_uuid,
            data=data,
        )
        return self._event_bus.publish(event)
