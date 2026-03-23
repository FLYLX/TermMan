import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from datetime import datetime

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
    event_types: list[SubscriptionEventType] = field(default_factory=lambda: [SubscriptionEventType.STREAM])
    subscriber_type: str = "generic"
    created_at: datetime = field(default_factory=datetime.now)


class ItemSubscriptionCenter:
    """
    Item 订阅中心 - 发布/订阅模式
    
    核心设计：
    1. ItemSocket 接收到事件后发布到订阅中心
    2. 订阅者通过 SDK 订阅特定 item 的事件
    3. 支持多种事件类型：stream、connected、disconnected、auth_error
    4. 线程安全
    """
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
        
        self._subscribers: dict[str, Subscriber] = {}
        self._item_subscribers: dict[str, list[str]] = {}
        self._global_lock = threading.RLock()
        
        logger.info("[SubscriptionCenter] Initialized")
    
    def subscribe(
        self,
        item_uuid: str,
        callback: Callable[[SubscriptionEvent], None],
        subscriber_type: str = "generic",
        event_types: list[SubscriptionEventType] | None = None,
        subscriber_id: str | None = None
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
            subscriber_type=subscriber_type
        )
        
        with self._global_lock:
            self._subscribers[sub_id] = subscriber
            
            if item_uuid not in self._item_subscribers:
                self._item_subscribers[item_uuid] = []
            self._item_subscribers[item_uuid].append(sub_id)
        
        logger.info(f"[SubscriptionCenter] Subscriber registered: {sub_id} for item={item_uuid}, types={[e.value for e in event_types]}")
        self._log_state()
        
        return sub_id
    
    def unsubscribe(self, subscriber_id: str) -> bool:
        with self._global_lock:
            if subscriber_id not in self._subscribers:
                return False
            
            subscriber = self._subscribers.pop(subscriber_id)
            item_uuid = subscriber.item_uuid
            
            if item_uuid in self._item_subscribers:
                if subscriber_id in self._item_subscribers[item_uuid]:
                    self._item_subscribers[item_uuid].remove(subscriber_id)
                if not self._item_subscribers[item_uuid]:
                    del self._item_subscribers[item_uuid]
        
        logger.info(f"[SubscriptionCenter] Subscriber unregistered: {subscriber_id}")
        return True
    
    def unsubscribe_all_by_item(self, item_uuid: str) -> int:
        count = 0
        with self._global_lock:
            if item_uuid not in self._item_subscribers:
                return 0
            
            sub_ids = self._item_subscribers[item_uuid].copy()
            for sub_id in sub_ids:
                if sub_id in self._subscribers:
                    del self._subscribers[sub_id]
                    count += 1
            
            del self._item_subscribers[item_uuid]
        
        logger.info(f"[SubscriptionCenter] Unsubscribed {count} subscribers for item={item_uuid}")
        return count
    
    def publish(self, event: SubscriptionEvent) -> int:
        delivered = 0
        
        with self._global_lock:
            if event.item_uuid not in self._item_subscribers:
                return 0
            
            sub_ids = self._item_subscribers[event.item_uuid].copy()
        
        for sub_id in sub_ids:
            with self._global_lock:
                subscriber = self._subscribers.get(sub_id)
            
            if subscriber is None:
                continue
            
            if event.event_type not in subscriber.event_types:
                continue
            
            try:
                subscriber.callback(event)
                delivered += 1
            except Exception as e:
                logger.error(f"[SubscriptionCenter] Error in callback for {sub_id}: {e}")
        
        if delivered > 0:
            logger.debug(f"[SubscriptionCenter] Event {event.event_type.value} delivered to {delivered} subscribers for item={event.item_uuid}")
        
        return delivered
    
    def publish_stream(self, item_uuid: str, data: dict[str, Any]) -> int:
        event = SubscriptionEvent(
            event_type=SubscriptionEventType.STREAM,
            item_uuid=item_uuid,
            data=data
        )
        return self.publish(event)
    
    def publish_connected(self, item_uuid: str, data: dict[str, Any]) -> int:
        event = SubscriptionEvent(
            event_type=SubscriptionEventType.TERMINAL_CONNECTED,
            item_uuid=item_uuid,
            data=data
        )
        return self.publish(event)
    
    def publish_disconnected(self, item_uuid: str, data: dict[str, Any]) -> int:
        event = SubscriptionEvent(
            event_type=SubscriptionEventType.TERMINAL_DISCONNECTED,
            item_uuid=item_uuid,
            data=data
        )
        return self.publish(event)
    
    def publish_auth_error(self, item_uuid: str, data: dict[str, Any]) -> int:
        event = SubscriptionEvent(
            event_type=SubscriptionEventType.AUTH_ERROR,
            item_uuid=item_uuid,
            data=data
        )
        return self.publish(event)
    
    def get_subscribers_by_item(self, item_uuid: str) -> list[Subscriber]:
        with self._global_lock:
            if item_uuid not in self._item_subscribers:
                return []
            return [self._subscribers[sid] for sid in self._item_subscribers[item_uuid] if sid in self._subscribers]
    
    def get_subscriber_count(self, item_uuid: str | None = None) -> int:
        with self._global_lock:
            if item_uuid:
                return len(self._item_subscribers.get(item_uuid, []))
            return len(self._subscribers)
    
    def _log_state(self):
        with self._global_lock:
            logger.info(f"\n{'='*60}")
            logger.info("[SubscriptionCenter] Current State")
            logger.info(f"{'='*60}")
            logger.info(f"Total subscribers: {len(self._subscribers)}")
            
            for item_uuid, sub_ids in self._item_subscribers.items():
                logger.info(f"  Item {item_uuid[:16]}...: {len(sub_ids)} subscribers")
                for sid in sub_ids:
                    sub = self._subscribers.get(sid)
                    if sub:
                        logger.info(f"    - {sid} ({sub.subscriber_type})")
            
            logger.info(f"{'='*60}\n")


subscription_center = ItemSubscriptionCenter()
