现在我有连接池表了
daemon和backend都有
backend外部一张表：daemon连接池表，用于记录每个daemon端的连接websocket的长连接，有连接的放进去，没有连接的就拿出来，里面没有的daemon ip:port:apikey组合。
            [daemon ip:port:apikey] 
backend两张表代表item在线状态和socket连接情况
             [daemon ip:port:apikey]对多个-> {item uuid : token }
            item_uuid 对多个→ {sid : user_uuid: ip_address}
广播是对所有{sid : user_uuid: ip_address}
单播根据ip_address来查找对应的socket连接。

daemon外部一张表，表示daemon和backend的websocket连接，有连接的放进去，没有连接的就拿出来。
    [backend IP：APIKEY]
daemon里面两张表代表item在线状态和socket连接情况
            
             [backend IP:apikey]对多个→ {item uuid : token }
            item_uuid 对多个→ {sid : user_uuid: ip_address}
参考：一、核心结论：api_key 仅用于「连接建立后的一次性认证」，无 token 返回
Panel 与 Daemon 的认证逻辑完全围绕 api_key 展开，不存在 Daemon 返回 token 供后续使用的环节：

    Panel 与 Daemon 建立 WebSocket 连接后，立即发送 auth 指令 + api_key；
    Daemon 校验 api_key 正确性：
        校验通过 → 标记该 WebSocket 会话为「可信」，返回 true（无 token）；
        校验失败 → 返回 false，Panel 标记该 Daemon 不可用；
    后续所有指令（如启动实例、查询状态），Daemon 仅校验「该 WebSocket 会话是否已认证」，不再重复校验 api_key。

我需要每次对某个item发送stop/start命令时，发送完get之后，就能从daemon更新后端对应item的socket连接池表，如果没有这个daemon连接，那么就尝试连接该item的ip:port:apikey到这个daeamon，如果连接不上就报错，说无此daemon。
stop和start都是get请求。
stop成功之后，daemon端要能够从连接池表里删除该item的所有socket连接，然后把该item的空连接池表返回给后端，进行更新。
如果终端本来就是关闭状态，那么stop命令就不需要做任何处理，直接返回空连接池表，并且get返回一个item未启动的消息。
start成功之后，后端获得了这个item的连接池表拿到token，后端连接一个user_uuid为backend连接，然后重新发送获取item的连接池表请求，进行更新，是至少要有的一个backend socket连接到后端，不能被断开。
如果终端本来就是启动状态，那么start命令就不需要做任何处理，直接返回当前连接池表，并且get返回一个item已启动的消息。

启动的item至少有一个名为backend的socket连接，这个连接是后端和daemon端通信的通道，用于收发log的，不能被断开，除非item被stop。

restart命令是stop和start的组合，先stop，再start。

/api/connections/disconnect 也是get请求
让某个ip和item_uuid组合起来，能够唯一确定一个socket连接，通过这个关联，disconnect能够正确地断开该连接，但是不能断开backend连接。
断开某个连接之后，daemon端返回连接池，后端根据这个连接池，就能知道哪个item的哪些socket连接已断开，并且更新后端的连接池表。

HTTP服务器认证完backend，再弄个上传下载文件的就行
参考https://github.com/MCSManager/MCSManager，用websocket保持daemon和后端的连接。
daemo里面的子item，单独开以上的连接池，用于管理子item的socket连接。