import logging
from typing import Any

from .item_socket import ItemSocket
from .socket_manager import SocketManager
from .subscriber_sdk import ItemSubscriberSDK

logger = logging.getLogger(__name__)


class SocketPoolFacade:
    _shared_log_subscribers: dict[str, str] = {}

    def __init__(
        self,
        socket_manager: SocketManager | None = None,
        subscriber_sdk: ItemSubscriberSDK | None = None,
    ):
        self._socket_manager = socket_manager or SocketManager()
        self._subscriber_sdk = subscriber_sdk or ItemSubscriberSDK()
        self._log_subscribers = self._shared_log_subscribers

    def register_item_token(self, daemon_id: str, item_uuid: str, token: str) -> None:
        self._socket_manager.add_token(daemon_id, item_uuid, token)

    def get_item_token(self, item_uuid: str) -> tuple[str | None, str | None]:
        return self._socket_manager.get_token_by_item(item_uuid)

    def validate_item_token(self, daemon_id: str, item_uuid: str, token: str) -> bool:
        return self._socket_manager.validate_token(daemon_id, item_uuid, token)

    def get_backend_socket(self, item_uuid: str) -> ItemSocket | None:
        return self._socket_manager.get_backend_socket(item_uuid)

    def ensure_backend_socket(
        self,
        *,
        item_uuid: str,
        token: str,
        daemon_url: str,
        api_key: str,
    ) -> ItemSocket:
        return self._socket_manager.create_backend_socket(
            item_uuid=item_uuid,
            token=token,
            daemon_url=daemon_url,
            api_key=api_key,
        )

    def ensure_browser_socket(
        self,
        *,
        item_uuid: str,
        token: str,
        daemon_url: str,
        user_uuid: str,
        api_key: str | None = None,
    ) -> ItemSocket:
        return self._socket_manager.get_or_create_socket(
            item_uuid=item_uuid,
            token=token,
            daemon_url=daemon_url,
            user_uuid=user_uuid,
            api_key=api_key,
            subscriber_type="browser",
        )

    def get_item_sockets(self, item_uuid: str) -> list[ItemSocket]:
        return self._socket_manager.get_sockets_by_item(item_uuid)

    def get_running_sockets(self) -> list[ItemSocket]:
        return self._socket_manager.get_running_sockets()

    def write_to_item(self, item_uuid: str, command: str) -> bool:
        for socket in self.get_item_sockets(item_uuid):
            if socket.is_connected():
                return socket.write(command)
        return False

    def ensure_log_subscription(
        self,
        *,
        item_uuid: str,
        owner_uuid: str,
        log_manager: Any,
        subscriber_type: str = "backend_log",
    ) -> str:
        existing = self._log_subscribers.get(item_uuid)
        if existing:
            return existing

        sub_id = self._subscriber_sdk.subscribe_log(
            item_uuid=item_uuid,
            owner_uuid=owner_uuid,
            log_manager=log_manager,
            subscriber_type=subscriber_type,
        )
        self._log_subscribers[item_uuid] = sub_id
        logger.info(
            "[SocketPoolFacade] Log subscriber registered: %s for item=%s",
            sub_id,
            item_uuid,
        )
        return sub_id

    def remove_log_subscription(self, item_uuid: str) -> bool:
        sub_id = self._log_subscribers.pop(item_uuid, None)
        if not sub_id:
            return False
        return self._subscriber_sdk.unsubscribe(sub_id)

    def cleanup_item_runtime(
        self,
        item_uuid: str,
        *,
        unsubscribe_subscribers: bool = True,
    ) -> None:
        self._socket_manager.remove_all_tokens_by_item(item_uuid)
        self._socket_manager.clear_sockets_by_item(item_uuid)
        self.remove_log_subscription(item_uuid)
        if unsubscribe_subscribers:
            self._subscriber_sdk.unsubscribe_item(item_uuid)
