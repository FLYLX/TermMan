import logging
import threading
from typing import Any

from .agent_bridge import AgentInputBridge
from .event_bus import (
    ItemEventBus,
    Subscriber,
    SubscriptionEvent,
    SubscriptionEventType,
)
from .terminal_stream_pipeline import TerminalStreamPipeline

logger = logging.getLogger(__name__)


class ItemSubscriptionCenter:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._event_bus = ItemEventBus()
        self._agent_bridge = AgentInputBridge()
        self._stream_pipeline = TerminalStreamPipeline(self._event_bus)

        logger.info("[SubscriptionCenter] Initialized")

    def subscribe(
        self,
        item_uuid: str,
        callback,
        subscriber_type: str = "generic",
        event_types: list[SubscriptionEventType] | None = None,
        subscriber_id: str | None = None,
    ) -> str:
        return self._event_bus.subscribe(
            item_uuid=item_uuid,
            callback=callback,
            subscriber_type=subscriber_type,
            event_types=event_types,
            subscriber_id=subscriber_id,
        )

    def unsubscribe(self, subscriber_id: str) -> bool:
        return self._event_bus.unsubscribe(subscriber_id)

    def unsubscribe_all_by_item(self, item_uuid: str) -> int:
        return self._event_bus.unsubscribe_all_by_item(item_uuid)

    def publish(self, event: SubscriptionEvent) -> int:
        return self._event_bus.publish(event)

    def publish_stream(self, item_uuid: str, data: dict[str, Any]) -> int:
        delivered = self._stream_pipeline.publish_stream(item_uuid, data)
        self._trigger_agent_handler(item_uuid, data)
        return delivered

    def _trigger_agent_handler(self, item_uuid: str, data: dict[str, Any]):
        self._agent_bridge.handle_stream(item_uuid, data)

    def publish_connected(self, item_uuid: str, data: dict[str, Any]) -> int:
        return self.publish(
            SubscriptionEvent(
                event_type=SubscriptionEventType.TERMINAL_CONNECTED,
                item_uuid=item_uuid,
                data=data,
            )
        )

    def publish_disconnected(self, item_uuid: str, data: dict[str, Any]) -> int:
        return self.publish(
            SubscriptionEvent(
                event_type=SubscriptionEventType.TERMINAL_DISCONNECTED,
                item_uuid=item_uuid,
                data=data,
            )
        )

    def publish_auth_error(self, item_uuid: str, data: dict[str, Any]) -> int:
        return self.publish(
            SubscriptionEvent(
                event_type=SubscriptionEventType.AUTH_ERROR,
                item_uuid=item_uuid,
                data=data,
            )
        )

    def get_subscribers_by_item(self, item_uuid: str) -> list[Subscriber]:
        return self._event_bus.get_subscribers_by_item(item_uuid)

    def get_subscriber_count(self, item_uuid: str | None = None) -> int:
        return self._event_bus.get_subscriber_count(item_uuid)


subscription_center = ItemSubscriptionCenter()
