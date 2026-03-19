_socket_service = None

def set_socket_service(service):
    global _socket_service
    _socket_service = service

def get_socket_service():
    global _socket_service
    return _socket_service
