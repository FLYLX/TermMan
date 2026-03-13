我需要service用函数能用一个函数获取damon端的连接表 
user_item_map	user_uuid → Set[item_uuid]	权限校验专用：直接判定 user_uuid 是否有权限操作某个 item_uuid（必须独立存储）
item_user_conn_map	item_uuid → {user_uuid: socket连接实例}	断开连接专用：定位具体的 socket 连接句柄
item_token_map	item_uuid → token	保留你原有的映射
缓存到内存中
daemon得有方法，可以断开某个item和某个user_uuid的socket连接，具体实现是，先根据item_uuid找到所有连接，然后遍历这些连接，找到user_uuid匹配的连接，断开该连接。
后端回传给前端token的权限检查是。前端请求item时，后端检查item的所有itemhanlder，然后再查itemhanlderuser映射表，是否有该用户的对应关系。如果有，就返回该item的token。
帮我后端和daemon实现上述功能
实现后运行daemon端，然后写一个测试工具，通过调用service的方法，多个user多个item测试daemon端的权限检查和获取所有表，断开连接和上面说的功能。