import logging
from collections.abc import Callable
from typing import Any

from .subscription_center import (
    ItemSubscriptionCenter,
    SubscriptionEvent,
    SubscriptionEventType,
    subscription_center,
)

logger = logging.getLogger(__name__)


class ItemSubscriberSDK:
    """
    Item 订阅 SDK - 简化订阅操作
    
    使用方式：
    ```python
    sdk = ItemSubscriberSDK()
    
    # 订阅日志
    sdk.subscribe_log(item_uuid, owner_uuid, log_manager)
    
    # 或自定义回调
    sdk.subscribe(item_uuid, my_callback)
    
    # 取消订阅
    sdk.unsubscribe(subscriber_id)
    ```
    """
    
    def __init__(self, center: ItemSubscriptionCenter | None = None):
        self._center = center or subscription_center
        self._subscriber_ids: list[str] = []
    
    def subscribe(
        self,
        item_uuid: str,
        callback: Callable[[SubscriptionEvent], None],
        subscriber_type: str = "sdk",
        event_types: list[SubscriptionEventType] | None = None
    ) -> str:
        sub_id = self._center.subscribe(
            item_uuid=item_uuid,
            callback=callback,
            subscriber_type=subscriber_type,
            event_types=event_types
        )
        self._subscriber_ids.append(sub_id)
        return sub_id
    
    def subscribe_stream(
        self,
        item_uuid: str,
        callback: Callable[[dict[str, Any]], None],
        subscriber_type: str = "stream_sdk"
    ) -> str:
        def wrapper(event: SubscriptionEvent):
            callback(event.data)
        
        return self.subscribe(
            item_uuid=item_uuid,
            callback=wrapper,
            subscriber_type=subscriber_type,
            event_types=[SubscriptionEventType.STREAM]
        )
    
    def subscribe_log(
        self,
        item_uuid: str,
        owner_uuid: str,
        log_manager: Any,
        subscriber_type: str = "log_sdk"
    ) -> str:
        def log_callback(event: SubscriptionEvent):
            data = event.data
            output = f"{data.get('stdout', '')}{data.get('stderr', '')}"

            if not output:
                return
            # The daemon tags background-job stream output with source="job";
            # it goes to the per-item jobs log, keeping the interactive PTY
            # log clean for the agent's read_terminal_log / command feedback.
            if data.get("source") == "job":
                log_manager.write_to_job_log(owner_uuid, item_uuid, output)
            else:
                log_manager.write_to_log(owner_uuid, item_uuid, output)

        return self.subscribe(
            item_uuid=item_uuid,
            callback=log_callback,
            subscriber_type=subscriber_type,
            event_types=[SubscriptionEventType.STREAM]
        )
    
    def subscribe_all_events(
        self,
        item_uuid: str,
        callback: Callable[[SubscriptionEvent], None],
        subscriber_type: str = "all_events_sdk"
    ) -> str:
        return self.subscribe(
            item_uuid=item_uuid,
            callback=callback,
            subscriber_type=subscriber_type,
            event_types=list(SubscriptionEventType)
        )
    
    def unsubscribe(self, subscriber_id: str) -> bool:
        if subscriber_id in self._subscriber_ids:
            self._subscriber_ids.remove(subscriber_id)
        return self._center.unsubscribe(subscriber_id)
    
    def unsubscribe_all(self) -> int:
        count = 0
        for sub_id in self._subscriber_ids.copy():
            if self._center.unsubscribe(sub_id):
                count += 1
        self._subscriber_ids.clear()
        return count
    
    def unsubscribe_item(self, item_uuid: str) -> int:
        return self._center.unsubscribe_all_by_item(item_uuid)
    
    def get_subscriber_count(self, item_uuid: str | None = None) -> int:
        return self._center.get_subscriber_count(item_uuid)


def create_log_subscriber(item_uuid: str, owner_uuid: str, log_manager: Any) -> str:
    sdk = ItemSubscriberSDK()
    return sdk.subscribe_log(item_uuid, owner_uuid, log_manager)


def create_stream_subscriber(item_uuid: str, callback: Callable[[dict[str, Any]], None]) -> str:
    sdk = ItemSubscriberSDK()
    return sdk.subscribe_stream(item_uuid, callback)
