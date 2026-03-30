import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from litellm import completion

from app.services.agent.agent import agent_manager

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60
COMMAND_WAIT_TIMEOUT = 20
MAX_COMMANDS_PER_SESSION = 5
SESSION_TIMEOUT = 120


@dataclass
class AgentWaitWindow:
    send_time: datetime
    query: str = ""
    waiting: bool = True
    command_count: int = 0
    session_start: datetime = None


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
        self._mcp_callbacks: dict[str, Callable] = {}
        self._chat_callbacks: dict[str, Callable] = {}
        
        logger.info("[TerminalStreamManager] Initialized")
    
    def register_chat(self, item_id: str, callback: Callable):
        self._chat_callbacks[item_id] = callback
    
    def unregister_chat(self, item_id: str):
        self._chat_callbacks.pop(item_id, None)
    
    def register_mcp_callback(self, item_id: str, callback: Callable):
        self._mcp_callbacks[item_id] = callback
    
    def unregister_mcp_callback(self, item_id: str):
        self._mcp_callbacks.pop(item_id, None)
    
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
        session_start = existing.session_start if existing and existing.session_start else datetime.now()
        command_count = existing.command_count if existing else 0
        
        self._agent_windows[item_id] = AgentWaitWindow(
            send_time=datetime.now(),
            query=query,
            waiting=True,
            command_count=command_count,
            session_start=session_start
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
        
        if window.session_start and (datetime.now() - window.session_start).total_seconds() > SESSION_TIMEOUT:
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
        else:
            self._handle_mcp_stream(item_id, filtered_output)
    
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
            
            system_prompt = self._get_skill_prompt(agent, query)
            
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"终端输出:\n{filtered_output}"}
            ]
            
            max_iterations = 10
            tool_call_history: list[tuple[str, str]] = []
            
            for iteration in range(max_iterations):
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
                
                response = completion(**kwargs)
                message = response.choices[0].message
                
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    assistant_message = {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": []
                    }
                    
                    for tool_call in message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args_str = tool_call.function.arguments
                        
                        tool_call_history.append((tool_name, tool_args_str))
                        
                        recent_calls = tool_call_history[-6:]
                        if len(recent_calls) >= 4:
                            call_counts = {}
                            for call in recent_calls:
                                call_counts[call] = call_counts.get(call, 0) + 1
                            
                            for call_sig, count in call_counts.items():
                                if count >= 3:
                                    logger.warning(f"[StreamManager] Detected loop: {call_sig[0]} called {count} times")
                                    self._emit_to_chat(item_id, f"检测到循环调用，已终止。工具 {call_sig[0]} 重复调用 {count} 次。", "agent_warning")
                                    return
                        
                        tool_args = json.loads(tool_args_str)
                        
                        tool_args["item_id"] = item_id
                        
                        if tool_name == "mcp_local_execute_command":
                            should_stop, reason = self.should_stop_session(item_id)
                            if should_stop:
                                self._emit_to_chat(item_id, f"会话终止: {reason}", "agent_warning")
                                self.reset_session(item_id)
                                return
                            
                            self.increment_command_count(item_id)
                            
                            self._emit_to_chat(item_id, f"执行命令: {tool_args.get('command', '')}", "agent_action")
                            self.open_agent_window(item_id, query)
                        
                        result = loop.run_until_complete(agent.execute_tool(tool_name, tool_args))
                        logger.info(f"[StreamManager] Tool {tool_name} result: {result}")
                        
                        result_text = ""
                        if isinstance(result, dict):
                            if result.get("success"):
                                result_data = result.get("result", [])
                                if isinstance(result_data, list):
                                    for item in result_data:
                                        if isinstance(item, dict) and item.get("type") == "text":
                                            result_text += item.get("text", "") + "\n"
                                else:
                                    result_text = str(result_data)
                            else:
                                result_text = f"Error: {result.get('error', 'Unknown error')}"
                        else:
                            result_text = str(result)
                        
                        assistant_message["tool_calls"].append({
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": tool_call.function.arguments
                            }
                        })
                        
                        messages.append(assistant_message)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result_text
                        })
                    
                    continue
                
                if message.content:
                    self._emit_to_chat(item_id, message.content, "agent_response")
                break
            
            loop.close()
            
        except Exception as e:
            logger.error(f"[StreamManager] Error: {e}")
            self._emit_to_chat(item_id, f"处理失败: {str(e)}", "agent_error")
    
    def _get_skill_prompt(self, agent: "Agent", query: str = "") -> str:
        skills = agent.get_skills()
        for skill in skills:
            if skill.action and skill.action.prompt:
                prompt = skill.action.prompt
                if query:
                    prompt = f"{prompt}\n\n用户问题: {query}"
                return prompt
        
        return "你是服务器运维助手。分析终端输出，如果发现错误请尝试修复。正常输出回复\"无需处理\"。"
    
    def _handle_mcp_stream(self, item_id: str, filtered_output: str):
        if callback := self._mcp_callbacks.get(item_id):
            try:
                callback(filtered_output)
            except Exception as e:
                logger.error(f"[StreamManager] Error in MCP callback: {e}")


stream_manager = TerminalStreamManager()
