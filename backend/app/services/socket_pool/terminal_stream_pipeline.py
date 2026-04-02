import logging
from typing import Any

from .event_bus import ItemEventBus, SubscriptionEvent, SubscriptionEventType

logger = logging.getLogger(__name__)


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
        event = SubscriptionEvent(
            event_type=SubscriptionEventType.STREAM,
            item_uuid=item_uuid,
            data=data,
        )
        return self._event_bus.publish(event)
