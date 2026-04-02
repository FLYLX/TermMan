import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SubscriptionEventType(Enum):
    STREAM = "stream"
    TERMINAL_CONNECTED = "terminal_connected"
    TERMINAL_DISCONNECTED = "terminal_disconnected"
    AUTH_ERROR = "auth_error"


@dataclass
class SubscriptionEvent:
    event_type: SubscriptionEventType
    item_uuid: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Subscriber:
    subscriber_id: str
    item_uuid: str
    callback: Callable[[SubscriptionEvent], None]
    event_types: list[SubscriptionEventType] = field(
        default_factory=lambda: [SubscriptionEventType.STREAM]
    )
    subscriber_type: str = "generic"
    created_at: datetime = field(default_factory=datetime.now)


class ItemEventBus:
    def __init__(self):
        self._subscribers: dict[str, Subscriber] = {}
        self._item_subscribers: dict[str, list[str]] = {}
        self._global_lock = threading.RLock()

        logger.info("[ItemEventBus] Initialized")

    def subscribe(
        self,
        item_uuid: str,
        callback: Callable[[SubscriptionEvent], None],
        subscriber_type: str = "generic",
        event_types: list[SubscriptionEventType] | None = None,
        subscriber_id: str | None = None,
    ) -> str:
        if event_types is None:
            event_types = [SubscriptionEventType.STREAM]

        import uuid

        sub_id = subscriber_id or f"{subscriber_type}_{item_uuid}_{uuid.uuid4().hex[:8]}"
        subscriber = Subscriber(
            subscriber_id=sub_id,
            item_uuid=item_uuid,
            callback=callback,
            event_types=event_types,
            subscriber_type=subscriber_type,
        )

        with self._global_lock:
            self._subscribers[sub_id] = subscriber
            self._item_subscribers.setdefault(item_uuid, []).append(sub_id)

        logger.info(
            "[ItemEventBus] Subscriber registered: %s for item=%s, types=%s",
            sub_id,
            item_uuid,
            [event_type.value for event_type in event_types],
        )
        self._log_state()
        return sub_id

    def unsubscribe(self, subscriber_id: str) -> bool:
        with self._global_lock:
            if subscriber_id not in self._subscribers:
                return False

            subscriber = self._subscribers.pop(subscriber_id)
            item_uuid = subscriber.item_uuid
            item_subscribers = self._item_subscribers.get(item_uuid)
            if item_subscribers and subscriber_id in item_subscribers:
                item_subscribers.remove(subscriber_id)
                if not item_subscribers:
                    self._item_subscribers.pop(item_uuid, None)

        logger.info("[ItemEventBus] Subscriber unregistered: %s", subscriber_id)
        return True

    def unsubscribe_all_by_item(self, item_uuid: str) -> int:
        with self._global_lock:
            sub_ids = self._item_subscribers.pop(item_uuid, []).copy()
            for sub_id in sub_ids:
                self._subscribers.pop(sub_id, None)

        if sub_ids:
            logger.info(
                "[ItemEventBus] Unsubscribed %s subscribers for item=%s",
                len(sub_ids),
                item_uuid,
            )
        return len(sub_ids)

    def publish(self, event: SubscriptionEvent) -> int:
        with self._global_lock:
            sub_ids = self._item_subscribers.get(event.item_uuid, []).copy()

        delivered = 0
        for sub_id in sub_ids:
            with self._global_lock:
                subscriber = self._subscribers.get(sub_id)

            if subscriber is None or event.event_type not in subscriber.event_types:
                continue

            try:
                subscriber.callback(event)
                delivered += 1
            except Exception as exc:
                logger.error("[ItemEventBus] Error in callback for %s: %s", sub_id, exc)

        if delivered > 0:
            logger.debug(
                "[ItemEventBus] Event %s delivered to %s subscribers for item=%s",
                event.event_type.value,
                delivered,
                event.item_uuid,
            )

        return delivered

    def get_subscribers_by_item(self, item_uuid: str) -> list[Subscriber]:
        with self._global_lock:
            sub_ids = self._item_subscribers.get(item_uuid, [])
            return [
                self._subscribers[sub_id]
                for sub_id in sub_ids
                if sub_id in self._subscribers
            ]

    def get_subscriber_count(self, item_uuid: str | None = None) -> int:
        with self._global_lock:
            if item_uuid is not None:
                return len(self._item_subscribers.get(item_uuid, []))
            return len(self._subscribers)

    def _log_state(self):
        with self._global_lock:
            logger.info("\n%s", "=" * 60)
            logger.info("[ItemEventBus] Current State")
            logger.info("%s", "=" * 60)
            logger.info("Total subscribers: %s", len(self._subscribers))

            for item_uuid, sub_ids in self._item_subscribers.items():
                logger.info("  Item %s...: %s subscribers", item_uuid[:16], len(sub_ids))
                for sub_id in sub_ids:
                    subscriber = self._subscribers.get(sub_id)
                    if subscriber:
                        logger.info("    - %s (%s)", sub_id, subscriber.subscriber_type)

            logger.info("%s\n", "=" * 60)
