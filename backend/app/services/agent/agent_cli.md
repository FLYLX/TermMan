┌─────────────────────────────────────────────────────────────────────────────┐
│                           终端输出处理流程                                    │
└─────────────────────────────────────────────────────────────────────────────┘

1. 终端输出 (daemon → backend)
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  daemon (item) ──socket──► subscription_center.publish_stream()         │
   │                              │                                          │
   │                              ├── data: {stdout, stderr}                 │
   │                              │                                          │
   │                              └──► _trigger_agent_handler()              │
   │                                    │                                    │
   │                                    ├── 查询 handler_id                   │
   │                                    ├── 应用输入过滤器 (可选)             │
   │                                    └──► stream_manager.process_stream() │
   └─────────────────────────────────────────────────────────────────────────┘

2. 流管理器处理 (stream_manager.py)
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  process_stream(item_id, filtered_output, handler_id)                   │
   │  │                                                                      │
   │  ├── 检查是否正在处理 (_is_processing)                                   │
   │  │   ├── 是 → 放入队列 (_output_queues)                                 │
   │  │   └── 否 → 设置处理标志                                              │
   │  │                                                                      │
   │  └──► _handle_agent_stream()                                           │
   │       │                                                                 │
   │       ├── 获取/创建 agent 实例                                          │
   │       │   └── agent_manager.get_or_create(handler)                     │
   │       │                                                                 │
   │       ├── 发送终端输出到前端                                            │
   │       │   └── _emit_to_chat(item_id, output, "terminal_output")        │
   │       │                                                                 │
   │       └──► _process_agent_output_sync() ──────────────────────────────┐ │
   └───────────────────────────────────────────────────────────────────────│─┘
                                                                           │
3. Agent 同步处理                                              │
   ┌───────────────────────────────────────────────────────────────────────│─┐
   │  _process_agent_output_sync(item_id, filtered_output, query, agent)   │ │
   │  │                                                                    │ │
   │  ├── 创建 asyncio 事件循环                                              │ │
   │  ├── 启动 MCP 服务器                                                    │ │
   │  │                                                                    │ │
   │  ├──► _build_initial_messages() ─────────────────────────────────────┐│ │
   │  │   │                                                               ││ │
   │  │   ├── system prompt (来自 skill)                                   ││ │
   │  │   ├── 相关记忆 (可选，跳过终端操作)                                   ││ │
   │  │   └── user: "终端输出:\n{output}"                                  ││ │
   │  │                                                                   ││ │
   │  └──► LLM 循环 (MAX_ITERATIONS=10)                                    ││ │
   │       │                                                              ││ │
   │       ├──► _call_llm() ──► litellm.completion()                      ││ │
   │       │                                                              ││ │
   │       ├── 无 tool_calls?                                             ││ │
   │       │   ├── 有 content → _emit_to_chat("agent_response")           ││ │
   │       │   └── break                                                  ││ │
   │       │                                                              ││ │
   │       └── 有 tool_calls?                                             ││ │
   │           └──► _handle_tool_calls() ────────────────────────────────┐││ │
   └─────────────────────────────────────────────────────────────────────│││─┘
                                                                         │││
4. 工具调用处理 (_handle_tool_calls)                                       │││
   ┌─────────────────────────────────────────────────────────────────────│││─┐
   │  for tool_call in message.tool_calls:                               │││ │
   │  │                                                                  │││ │
   │  ├── 循环检测 (LoopDetector)                                         │││ │
   │  │   └── 重复调用同一工具 → 终止                                       │││ │
   │  │                                                                  │││ │
   │  ├── 解析工具参数                                                     │││ │
   │  │   └── tool_args["item_id"] = item_id                             │││ │
   │  │                                                                  │││ │
   │  ├── 特殊工具处理:                                                    │││ │
   │  │   └── mcp_local_execute_command:                                 │││ │
   │  │       ├── 检查会话限制 (MAX_COMMANDS_PER_SESSION=5)                │││ │
   │  │       ├── _emit_to_chat("agent_action")                          │││ │
   │  │       └── open_agent_window()                                    │││ │
   │  │                                                                  │││ │
   │  ├──► agent.execute_tool(tool_name, tool_args)                     │││ │
   │  │   └── MCP 工具执行                                              │││ │
   │  │                                                                  │││ │
   │  └── 添加结果到 messages                                            │││ │
   │      └── {role: "tool", tool_call_id, content: result}             │││ │
   │                                                                     │││ │
   │  return messages, used_skip_memory                                  │││ │
   └─────────────────────────────────────────────────────────────────────│││─┘
                                                                         │││
5. 消息发送到前端                                                       │││
   ┌─────────────────────────────────────────────────────────────────────│││─┐
   │  _emit_to_chat(item_id, message, msg_type)                          │││ │
   │  │                                                                  │││ │
   │  ├── msg_data = {                                                   │││ │
   │  │     type: "terminal_output" | "agent_response" |                 │││ │
   │  │           "agent_action" | "agent_error" | "agent_warning",      │││ │
   │  │     content: message,                                            │││ │
   │  │     timestamp: datetime.now().isoformat()                        │││ │
   │  │   }                                                              │││ │
   │  │                                                                  │││ │
   │  ├── callback?(msg_data)  # 直接回调                                │││ │
   │  │                                                                  │││ │
   │  └── AgentMessageQueue.put_message(item_id, msg_data)               │││ │
   │       │                                                             │││ │
   │       └──► SSE 端点 /chat/{item_id}/agent-events                    │││ │
   │              │                                                      │││ │
   │              └──► 前端 ChatPanel.tsx 实时渲染                        │││ │
   └─────────────────────────────────────────────────────────────────────│││─┘
                                                                         │││
6. 前端渲染                                                 │││
   ┌─────────────────────────────────────────────────────────────────────│││─┐
   │  SSE 连接: /api/v1/chat/{itemId}/agent-events                       │││ │
   │  │                                                                  │││ │
   │  ├── terminal_output → 绿色终端样式                                 │││ │
   │  ├── agent_response → 助手消息                                      │││ │
   │  ├── agent_action → 助手消息 (执行命令)                             │││ │
   │  └── agent_error → 红色错误消息                                     │││ │
   └─────────────────────────────────────────────────────────────────────│││─┘
                                                                         │││
┌─────────────────────────────────────────────────────────────────────────│││─┐
│  关键数据结构                                                           │││ │
├─────────────────────────────────────────────────────────────────────────│││─┤
│                                                                         │││ │
│  messages = [                                                           │││ │
│    {role: "system", content: "你是服务器运维助手..."},                  │││ │
│    {role: "system", content: "相关记忆:\n- ..."},  # 可选              │││ │
│    {role: "user", content: "终端输出:\n{output}"},                     │││ │
│    {role: "assistant", content: "", tool_calls: [...]},  # 工具调用   │││ │
│    {role: "tool", tool_call_id: "...", content: "执行结果"},           │││ │
│    {role: "assistant", content: "最终回复"},  # 最终响应               │││ │
│  ]                                                                      │││ │
│                                                                         │││ │
└─────────────────────────────────────────────────────────────────────────│││─┘