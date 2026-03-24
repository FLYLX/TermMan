import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import UUID

from .engine import AgentEngine, AgentConfig, AgentState, PendingCommand
from ..socket_pool import (
    ItemSubscriberSDK,
    InputSDK,
    SubscriptionEvent,
    SubscriptionEventType,
)

logger = logging.getLogger(__name__)


@dataclass
class HandlerBinding:
    handler_id: str
    item_uuid: str
    engine: AgentEngine
    subscription_id: str | None = None
    input_handler_id: str | None = None
    active: bool = True


class HandlerManager:
    """
    Handler 管理器 - 管理 Agent 实例与 Item 的绑定

    职责:
    1. 创建/销毁 Agent 实例
    2. 绑定 Agent 到 Item
    3. 管理订阅和输入处理器
    4. 协调多个 Agent 实例
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
        self._bindings: dict[str, HandlerBinding] = {}
        self._item_handlers: dict[str, list[str]] = {}
        self._subscriber_sdk = ItemSubscriberSDK()
        self._input_sdk = InputSDK()
        self._socket_manager: Any = None
        self._global_lock = threading.RLock()

    def set_socket_manager(self, socket_manager: Any):
        self._socket_manager = socket_manager

    def create_engine(
        self,
        handler: Any,
        item: Any,
        auto_start: bool = True,
    ) -> AgentEngine:
        config = AgentConfig.from_handler_and_items(handler, item)
        engine = AgentEngine(config)

        if auto_start:
            self._bind_to_item(engine, str(handler.id), str(item.id), item)

        return engine

    def _bind_to_item(
        self,
        engine: AgentEngine,
        handler_id: str,
        item_uuid: str,
        item: Any,
    ):
        def on_stream_event(event: SubscriptionEvent):
            if event.event_type == SubscriptionEventType.STREAM:
                command = engine.process_stream(item_uuid, event.data)
                if command:
                    logger.info(f"[HandlerManager] Engine generated command: {command[:50]}...")

        def on_command_execute(uuid: str, command: str) -> bool:
            if self._socket_manager:
                socket = self._socket_manager.get_backend_socket(uuid)
                if socket and socket.is_connected():
                    return socket.write(command)
            return False

        engine.set_command_callback(on_command_execute)

        sub_id = self._subscriber_sdk.subscribe(
            item_uuid=item_uuid,
            callback=on_stream_event,
            event_types=[
                SubscriptionEventType.STREAM,
                SubscriptionEventType.TERMINAL_DISCONNECTED,
            ],
        )

        input_h_id = None
        if self._socket_manager:
            input_h_id = self._input_sdk.register_socket_handler(
                item_uuid=item_uuid,
                socket_manager=self._socket_manager,
            )

        binding = HandlerBinding(
            handler_id=handler_id,
            item_uuid=item_uuid,
            engine=engine,
            subscription_id=sub_id,
            input_handler_id=input_h_id,
        )

        binding_key = f"{handler_id}:{item_uuid}"
        with self._global_lock:
            self._bindings[binding_key] = binding

            if item_uuid not in self._item_handlers:
                self._item_handlers[item_uuid] = []
            if handler_id not in self._item_handlers[item_uuid]:
                self._item_handlers[item_uuid].append(handler_id)

        logger.info(f"[HandlerManager] Bound handler {handler_id} to item {item_uuid}")

    def unbind_handler(self, handler_id: str, item_uuid: str) -> bool:
        binding_key = f"{handler_id}:{item_uuid}"

        with self._global_lock:
            if binding_key not in self._bindings:
                return False

            binding = self._bindings.pop(binding_key)

            if binding.subscription_id:
                self._subscriber_sdk.unsubscribe(binding.subscription_id)

            if binding.input_handler_id:
                self._input_sdk.unregister(binding.input_handler_id)

            if item_uuid in self._item_handlers:
                if handler_id in self._item_handlers[item_uuid]:
                    self._item_handlers[item_uuid].remove(handler_id)
                if not self._item_handlers[item_uuid]:
                    del self._item_handlers[item_uuid]

        logger.info(f"[HandlerManager] Unbound handler {handler_id} from item {item_uuid}")
        return True

    def get_engine(self, handler_id: str, item_uuid: str) -> AgentEngine | None:
        binding_key = f"{handler_id}:{item_uuid}"
        binding = self._bindings.get(binding_key)
        return binding.engine if binding else None

    def get_engines_for_item(self, item_uuid: str) -> list[AgentEngine]:
        engines = []
        with self._global_lock:
            handler_ids = self._item_handlers.get(item_uuid, [])
            for handler_id in handler_ids:
                binding_key = f"{handler_id}:{item_uuid}"
                if binding_key in self._bindings:
                    engines.append(self._bindings[binding_key].engine)
        return engines

    def get_all_engines(self) -> list[AgentEngine]:
        return [b.engine for b in self._bindings.values()]

    def execute_command(self, handler_id: str, item_uuid: str, command: str) -> bool:
        engine = self.get_engine(handler_id, item_uuid)
        if not engine:
            return False
        return engine.execute_command(item_uuid, command)

    def chat(self, handler_id: str, item_uuid: str, message: str) -> str | None:
        engine = self.get_engine(handler_id, item_uuid)
        if not engine:
            return None
        return engine.chat(item_uuid, message)

    def approve_command(self, handler_id: str, item_uuid: str) -> str | None:
        engine = self.get_engine(handler_id, item_uuid)
        if not engine:
            return None
        return engine.approve_command(item_uuid)

    def reject_command(self, handler_id: str, item_uuid: str) -> bool:
        engine = self.get_engine(handler_id, item_uuid)
        if not engine:
            return False
        return engine.reject_command(item_uuid)

    def get_pending_command(self, handler_id: str, item_uuid: str) -> PendingCommand | None:
        engine = self.get_engine(handler_id, item_uuid)
        if not engine:
            return None
        return engine.get_pending_command(item_uuid)

    def get_stats(self, handler_id: str, item_uuid: str) -> dict[str, Any] | None:
        engine = self.get_engine(handler_id, item_uuid)
        if not engine:
            return None
        return engine.get_stats(item_uuid)

    def reset_engine(self, handler_id: str, item_uuid: str | None = None):
        engine = self.get_engine(handler_id, item_uuid or "")
        if engine:
            engine.reset(item_uuid)

    def cleanup_item(self, item_uuid: str):
        with self._global_lock:
            handler_ids = list(self._item_handlers.get(item_uuid, []))

        for handler_id in handler_ids:
            self.unbind_handler(handler_id, item_uuid)

        logger.info(f"[HandlerManager] Cleaned up all handlers for item {item_uuid}")

    def cleanup_handler(self, handler_id: str):
        with self._global_lock:
            binding_keys = [k for k in self._bindings if k.startswith(f"{handler_id}:")]

        for key in binding_keys:
            _, item_uuid = key.split(":")
            self.unbind_handler(handler_id, item_uuid)

        logger.info(f"[HandlerManager] Cleaned up handler {handler_id}")

    def get_binding_count(self) -> int:
        return len(self._bindings)

    def get_item_count(self) -> int:
        return len(self._item_handlers)


handler_manager = HandlerManager()
