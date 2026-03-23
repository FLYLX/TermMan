import logging
from typing import Any

from .input_center import InputCenter, InputCommand, input_center

logger = logging.getLogger(__name__)


class InputSDK:
    """
    Item 输入 SDK - 简化命令发送操作
    
    使用方式：
    ```python
    sdk = InputSDK()
    
    # 发送命令到指定 item
    sdk.send("item-uuid", "ls -la\n")
    
    # 批量发送到所有已注册的 item
    results = sdk.send_to_all("echo 'hello'\n")
    ```
    """
    
    def __init__(self, center: InputCenter | None = None):
        self._center = center or input_center
        self._handler_ids: list[str] = []
    
    def register_handler(
        self,
        item_uuid: str,
        write_callback: callable,
        handler_type: str = "sdk"
    ) -> str:
        def handler_callback(cmd: InputCommand) -> bool:
            return write_callback(cmd.command)
        
        h_id = self._center.register(
            item_uuid=item_uuid,
            callback=handler_callback,
            handler_type=handler_type
        )
        self._handler_ids.append(h_id)
        return h_id
    
    def register_socket_handler(
        self,
        item_uuid: str,
        socket_manager: Any,
        handler_type: str = "socket_sdk"
    ) -> str:
        def socket_callback(cmd: InputCommand) -> bool:
            socket = socket_manager.get_backend_socket(cmd.item_uuid)
            if socket and socket.is_connected():
                return socket.write(cmd.command)
            return False
        
        return self.register_handler(item_uuid, socket_callback, handler_type)
    
    def send(self, item_uuid: str, command: str, source: str = "sdk") -> bool:
        return self._center.send(item_uuid, command, source)
    
    def send_to_all(self, command: str, source: str = "sdk") -> dict[str, bool]:
        return self._center.send_to_all(command, source)
    
    def unregister(self, handler_id: str) -> bool:
        if handler_id in self._handler_ids:
            self._handler_ids.remove(handler_id)
        return self._center.unregister(handler_id)
    
    def unregister_all(self) -> int:
        count = 0
        for h_id in self._handler_ids.copy():
            if self._center.unregister(h_id):
                count += 1
        self._handler_ids.clear()
        return count
    
    def unregister_item(self, item_uuid: str) -> int:
        return self._center.unregister_all_by_item(item_uuid)
    
    def has_handler(self, item_uuid: str) -> bool:
        return self._center.has_handler(item_uuid)
    
    def get_handler_count(self, item_uuid: str | None = None) -> int:
        return self._center.get_handler_count(item_uuid)


def create_input_handler(item_uuid: str, write_callback: callable) -> str:
    sdk = InputSDK()
    return sdk.register_handler(item_uuid, write_callback)


def send_command(item_uuid: str, command: str, source: str = "sdk") -> bool:
    return input_center.send(item_uuid, command, source)


def send_command_to_all(command: str, source: str = "sdk") -> dict[str, bool]:
    return input_center.send_to_all(command, source)
