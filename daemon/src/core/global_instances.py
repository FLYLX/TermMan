# 全局实例存储
_socket_service = None

def set_socket_service(service):
    """
    设置全局Socket服务实例
    """
    global _socket_service
    _socket_service = service

def get_socket_service():
    """
    获取全局Socket服务实例
    """
    global _socket_service
    return _socket_service
