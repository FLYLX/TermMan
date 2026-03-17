_socket_service = None
_backend_connections = {}

def set_socket_service(service):
    global _socket_service
    _socket_service = service

def get_socket_service():
    global _socket_service
    return _socket_service

def add_backend_connection(backend_id: str):
    """
    添加backend连接到连接池
    
    Args:
        backend_id: Backend标识 (IP:apikey)
    """
    global _backend_connections
    _backend_connections[backend_id] = True

def remove_backend_connection(backend_id: str):
    """
    从连接池移除backend连接
    
    Args:
        backend_id: Backend标识 (IP:apikey)
    """
    global _backend_connections
    if backend_id in _backend_connections:
        del _backend_connections[backend_id]

def get_backend_connections():
    """
    获取所有backend连接
    
    Returns:
        {backend_id: True}
    """
    global _backend_connections
    return _backend_connections.copy()

def is_backend_connected(backend_id: str) -> bool:
    """
    检查backend是否已连接
    
    Args:
        backend_id: Backend标识 (IP:apikey)
        
    Returns:
        是否已连接
    """
    global _backend_connections
    return backend_id in _backend_connections
