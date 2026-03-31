import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from litellm import completion

from app.services.agent.agent import agent_manager

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60
COMMAND_WAIT_TIMEOUT = 20
MAX_COMMANDS_PER_SESSION = 5
SESSION_TIMEOUT = 120
MAX_ITERATIONS = 10
LOOP_DETECTION_WINDOW = 6
LOOP_THRESHOLD = 3


@dataclass
class AgentWaitWindow:
    send_time: datetime
    query: str = ""
    waiting: bool = True
    command_count: int = 0
    session_start: datetime = field(default_factory=datetime.now)


@dataclass
class ToolCallResult:
    success: bool
    content: str


class LoopDetector:
    def __init__(self, window_size: int = LOOP_DETECTION_WINDOW, threshold: int = LOOP_THRESHOLD):
        self._window_size = window_size
        self._threshold = threshold
        self._history: list[tuple[str, str]] = []
    
    def add_call(self, tool_name: str, args: str) -> bool:
        self._history.append((tool_name, args))
        if len(self._history) > self._window_size:
            self._history.pop(0)
        return self._detect_loop()
    
    def _detect_loop(self) -> bool:
        if len(self._history) < 4:
            return False
        call_counts: dict[tuple[str, str], int] = {}
        for call in self._history:
            call_counts[call] = call_counts.get(call, 0) + 1
        return any(count >= self._threshold for count in call_counts.values())
    
    def get_loop_info(self) -> tuple[str, int] | None:
        call_counts: dict[tuple[str, str], int] = {}
        for call in self._history:
            call_counts[call] = call_counts.get(call, 0) + 1
        for (name, _), count in call_counts.items():
            if count >= self._threshold:
                return name, count
        return None


class TerminalStreamManager:
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
        self._agent_windows: dict[str, AgentWaitWindow] = {}
        self._chat_callbacks: dict[str, Callable] = {}
        logger.info("[TerminalStreamManager] Initialized")
    
    def register_chat(self, item_id: str, callback: Callable):
        self._chat_callbacks[item_id] = callback
    
    def unregister_chat(self, item_id: str):
        self._chat_callbacks.pop(item_id, None)
    
    def _emit_to_chat(self, item_id: str, message: str, msg_type: str = "agent_response"):
        if callback := self._chat_callbacks.get(item_id):
            try:
                callback({
                    "type": msg_type,
                    "content": message,
                    "timestamp": datetime.now().isoformat(),
                })
            except Exception as e:
                logger.error(f"[StreamManager] Error emitting to chat: {e}")
    
    def open_agent_window(self, item_id: str, query: str = ""):
        existing = self._agent_windows.get(item_id)
        self._agent_windows[item_id] = AgentWaitWindow(
            send_time=datetime.now(),
            query=query,
            command_count=existing.command_count if existing else 0,
            session_start=existing.session_start if existing else datetime.now(),
        )
    
    def close_agent_window(self, item_id: str):
        if window := self._agent_windows.get(item_id):
            window.waiting = False
    
    def increment_command_count(self, item_id: str) -> int:
        if window := self._agent_windows.get(item_id):
            window.command_count += 1
            return window.command_count
        return 0
    
    def should_stop_session(self, item_id: str) -> tuple[bool, str]:
        window = self._agent_windows.get(item_id)
        if not window:
            return False, ""
        if window.command_count >= MAX_COMMANDS_PER_SESSION:
            return True, f"已达到最大命令次数限制 ({MAX_COMMANDS_PER_SESSION})"
        if (datetime.now() - window.session_start).total_seconds() > SESSION_TIMEOUT:
            return True, f"会话超时 ({SESSION_TIMEOUT}s)"
        return False, ""
    
    def reset_session(self, item_id: str):
        self._agent_windows.pop(item_id, None)
    
    def is_in_agent_window(self, item_id: str) -> bool:
        window = self._agent_windows.get(item_id)
        if not window or not window.waiting:
            return False
        if (datetime.now() - window.send_time).total_seconds() > COMMAND_WAIT_TIMEOUT:
            window.waiting = False
            self._emit_to_chat(item_id, "命令执行超时", "agent_warning")
            return False
        return True
    
    def process_stream(self, item_id: str, filtered_output: str, handler_id: str = None):
        if self.is_in_agent_window(item_id):
            self._handle_agent_stream(item_id, filtered_output, handler_id)
    
    def _handle_agent_stream(self, item_id: str, filtered_output: str, handler_id: str = None):
        window = self._agent_windows.get(item_id)
        query = window.query if window else ""
        self.close_agent_window(item_id)
        
        if not filtered_output or not filtered_output.strip():
            return
        if not handler_id or not (agent := agent_manager._agents.get(handler_id)):
            return
        
        threading.Thread(
            target=self._process_agent_output_async,
            args=(item_id, filtered_output, query, agent),
            daemon=True
        ).start()
    
    def _process_agent_output_async(self, item_id: str, filtered_output: str, query: str, agent: "Agent"):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            messages = self._build_initial_messages(agent, query, filtered_output)
            loop_detector = LoopDetector()
            
            for _ in range(MAX_ITERATIONS):
                response = self._call_llm(agent, messages)
                message = response.choices[0].message
                
                if not (hasattr(message, 'tool_calls') and message.tool_calls):
                    if message.content:
                        self._emit_to_chat(item_id, message.content, "agent_response")
                    break
                
                messages = self._handle_tool_calls(
                    item_id, query, agent, loop, messages, message, loop_detector
                )
                if messages is None:
                    break
            
            loop.close()
        except Exception as e:
            logger.error(f"[StreamManager] Error: {e}")
            self._emit_to_chat(item_id, f"处理失败: {str(e)}", "agent_error")
    
    def _build_initial_messages(self, agent: "Agent", query: str, output: str) -> list[dict]:
        system_prompt = self._get_skill_prompt(agent, query)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"终端输出:\n{output}"}
        ]
    
    def _call_llm(self, agent: "Agent", messages: list[dict]):
        kwargs: dict[str, Any] = {
            "model": agent._context.model,
            "messages": messages,
            "timeout": REQUEST_TIMEOUT,
            "temperature": 0.1,
        }
        if agent._context.api_key:
            kwargs["api_key"] = agent._context.api_key
        if agent._context.api_url:
            kwargs["api_base"] = agent._context.api_url
        if tools := agent.get_tools_for_litellm():
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return completion(**kwargs)
    
    def _handle_tool_calls(
        self,
        item_id: str,
        query: str,
        agent: "Agent",
        loop: asyncio.AbstractEventLoop,
        messages: list[dict],
        message: Any,
        loop_detector: LoopDetector,
    ) -> list[dict] | None:
        assistant_message = {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": []
        }
        
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            tool_args_str = tool_call.function.arguments
            
            if loop_detector.add_call(tool_name, tool_args_str):
                loop_info = loop_detector.get_loop_info()
                if loop_info:
                    tool, count = loop_info
                    logger.warning(f"[StreamManager] Detected loop: {tool} called {count} times")
                    self._emit_to_chat(item_id, f"检测到循环调用，已终止。工具 {tool} 重复调用 {count} 次。", "agent_warning")
                return None
            
            tool_args = json.loads(tool_args_str)
            tool_args["item_id"] = item_id
            
            if tool_name == "mcp_local_execute_command":
                should_stop, reason = self.should_stop_session(item_id)
                if should_stop:
                    self._emit_to_chat(item_id, f"会话终止: {reason}", "agent_warning")
                    self.reset_session(item_id)
                    return None
                self.increment_command_count(item_id)
                self._emit_to_chat(item_id, f"执行命令: {tool_args.get('command', '')}", "agent_action")
                self.open_agent_window(item_id, query)
            
            result = loop.run_until_complete(agent.execute_tool(tool_name, tool_args))
            logger.info(f"[StreamManager] Tool {tool_name} result: {result}")
            
            result_text = self._format_tool_result(result)
            
            assistant_message["tool_calls"].append({
                "id": tool_call.id,
                "type": "function",
                "function": {"name": tool_name, "arguments": tool_call.function.arguments}
            })
            
            messages.append(assistant_message)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result_text
            })
        
        return messages
    
    def _format_tool_result(self, result: dict) -> str:
        if not isinstance(result, dict):
            return str(result)
        if result.get("success"):
            result_data = result.get("result", [])
            if isinstance(result_data, list):
                texts = [
                    item.get("text", "")
                    for item in result_data
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                return "\n".join(texts)
            return str(result_data)
        return f"Error: {result.get('error', 'Unknown error')}"
    
    def _get_skill_prompt(self, agent: "Agent", query: str = "") -> str:
        skills = agent.get_skills()
        for skill in skills:
            if skill.action and skill.action.prompt:
                prompt = skill.action.prompt
                if query:
                    prompt = f"{prompt}\n\n用户问题: {query}"
                return prompt
        return "你是服务器运维助手。分析终端输出，如果发现错误请尝试修复。正常输出回复\"无需处理\"。"


stream_manager = TerminalStreamManager()
