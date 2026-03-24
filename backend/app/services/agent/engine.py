import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from enum import Enum

from .filters.input_filter import InputFilter, InputFilterConfig, EventType
from .filters.output_filter import OutputFilter, OutputFilterConfig, FilterAction
from .llm.llm_client import LLMClient, LLMConfig
from .llm.prompt_templates import PromptTemplates
from .memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class AgentState(Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    ERROR = "error"


@dataclass
class AgentConfig:
    handler_id: str
    llm_config: LLMConfig
    input_filter_config: InputFilterConfig
    output_filter_config: OutputFilterConfig
    auto_execute: bool = False
    max_retries: int = 3

    @classmethod
    def from_handler_and_items(cls, handler: Any, item: Any) -> "AgentConfig":
        return cls(
            handler_id=str(handler.id),
            llm_config=LLMConfig.from_handler(handler),
            input_filter_config=InputFilterConfig.from_item(item),
            output_filter_config=OutputFilterConfig.from_item(item),
        )


@dataclass
class PendingCommand:
    command: str
    reason: str
    item_uuid: str
    timestamp: str


class AgentEngine:
    """
    Agent 主引擎 - 协调各组件完成智能终端操作

    工作流程:
    1. 接收终端输出 → InputFilter 过滤
    2. 有价值事件 → LLM 分析
    3. LLM 生成命令 → OutputFilter 检查
    4. 安全命令 → 执行
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self.input_filter = InputFilter(config.input_filter_config)
        self.output_filter = OutputFilter(config.output_filter_config)
        self.llm_client = LLMClient(config.llm_config)
        self.memory = MemoryManager(handler_id=config.handler_id)

        self._state = AgentState.IDLE
        self._pending_commands: dict[str, PendingCommand] = {}
        self._command_callback: Callable[[str, str], bool] | None = None
        self._approval_callback: Callable[[str, PendingCommand], bool] | None = None

    @property
    def state(self) -> AgentState:
        return self._state

    def set_command_callback(self, callback: Callable[[str, str], bool]):
        self._command_callback = callback

    def set_approval_callback(self, callback: Callable[[str, PendingCommand], bool]):
        self._approval_callback = callback

    def process_stream(self, item_uuid: str, stream_data: dict[str, Any]) -> str | None:
        """
        处理终端输出流

        Returns:
            str | None: 需要执行的命令，或 None
        """
        if self._state == AgentState.PROCESSING:
            return None

        self._state = AgentState.PROCESSING

        try:
            filtered_event = self.input_filter.filter(stream_data)
            if not filtered_event:
                self._state = AgentState.IDLE
                return None

            if filtered_event.event_type == EventType.NOISE:
                self._state = AgentState.IDLE
                return None

            self.memory.record_command(
                item_uuid=item_uuid,
                command=None,
                result=filtered_event.raw_content,
            )

            if filtered_event.event_type == EventType.NEEDS_ACTION:
                command = self._analyze_and_respond(item_uuid, filtered_event)
                if command:
                    return self._handle_command(item_uuid, command)

            self._state = AgentState.IDLE
            return None

        except Exception as e:
            logger.error(f"[AgentEngine] Error processing stream: {e}")
            self._state = AgentState.ERROR
            return None

    def _analyze_and_respond(self, item_uuid: str, event: Any) -> str | None:
        context = self.memory.get_relevant_context(item_uuid)

        prompt = PromptTemplates.format_prompt(
            PromptTemplates.EVENT_ANALYSIS_PROMPT,
            output=event.raw_content,
            context=context or "No recent context",
        )

        try:
            response = self.llm_client.chat(
                message=prompt,
                system_prompt=PromptTemplates.SYSTEM_PROMPT,
            )

            command = self._extract_command(response)
            return command

        except Exception as e:
            logger.error(f"[AgentEngine] LLM error: {e}")
            return None

    def _extract_command(self, response: str) -> str | None:
        lines = response.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("Command:"):
                command = line.replace("Command:", "").strip()
                if command and command != "None":
                    return command

        code_blocks = response.split("```")
        if len(code_blocks) >= 2:
            for i in range(1, len(code_blocks), 2):
                block = code_blocks[i].strip()
                if block.startswith("bash") or block.startswith("sh"):
                    lines = block.split("\n")
                    if len(lines) > 1:
                        return "\n".join(lines[1:]).strip()
                elif not any(block.startswith(kw) for kw in ["python", "javascript", "json"]):
                    return block

        return None

    def _handle_command(self, item_uuid: str, command: str) -> str | None:
        filter_result = self.output_filter.filter(command, item_uuid)

        if filter_result.is_allowed:
            self.memory.record_command(item_uuid, filter_result.command)
            if self._command_callback:
                self._command_callback(item_uuid, filter_result.command)
            return filter_result.command

        if filter_result.needs_approval:
            pending = PendingCommand(
                command=filter_result.command,
                reason=filter_result.reason,
                item_uuid=item_uuid,
                timestamp=str(datetime.now()),
            )
            self._pending_commands[item_uuid] = pending
            self._state = AgentState.WAITING_FOR_APPROVAL

            if self._approval_callback:
                approved = self._approval_callback(item_uuid, pending)
                if approved:
                    return self.approve_command(item_uuid)
                else:
                    self.reject_command(item_uuid)

            logger.info(f"[AgentEngine] Command needs approval: {filter_result.reason}")
            return None

        if filter_result.is_blocked:
            logger.warning(f"[AgentEngine] Command blocked: {filter_result.reason}")
            return None

        if filter_result.action == FilterAction.MODIFIED:
            self.memory.record_command(item_uuid, filter_result.command)
            if self._command_callback:
                self._command_callback(item_uuid, filter_result.command)
            return filter_result.command

        return None

    def approve_command(self, item_uuid: str) -> str | None:
        if item_uuid not in self._pending_commands:
            return None

        pending = self._pending_commands.pop(item_uuid)
        self.memory.record_command(item_uuid, pending.command)
        self._state = AgentState.IDLE

        if self._command_callback:
            self._command_callback(item_uuid, pending.command)

        return pending.command

    def reject_command(self, item_uuid: str) -> bool:
        if item_uuid not in self._pending_commands:
            return False

        del self._pending_commands[item_uuid]
        self._state = AgentState.IDLE
        return True

    def execute_command(self, item_uuid: str, command: str) -> bool:
        filter_result = self.output_filter.filter(command, item_uuid)

        if not filter_result.is_allowed:
            logger.warning(f"[AgentEngine] Manual command blocked: {filter_result.reason}")
            return False

        self.memory.record_command(item_uuid, filter_result.command)

        if self._command_callback:
            return self._command_callback(item_uuid, filter_result.command)

        return True

    def chat(self, item_uuid: str, message: str) -> str:
        context = self.memory.get_relevant_context(item_uuid)

        response = self.llm_client.chat(
            message=message,
            system_prompt=PromptTemplates.SYSTEM_PROMPT,
            context=context,
        )

        self.memory.record_exchange(item_uuid, message, response)
        return response

    def reset(self, item_uuid: str | None = None):
        if item_uuid:
            self.memory.clear_item_memory(item_uuid)
            if item_uuid in self._pending_commands:
                del self._pending_commands[item_uuid]
        else:
            self.memory.clear_all()
            self._pending_commands.clear()

        self._state = AgentState.IDLE
        self.llm_client.clear_history()

    def get_pending_command(self, item_uuid: str) -> PendingCommand | None:
        return self._pending_commands.get(item_uuid)

    def get_stats(self, item_uuid: str) -> dict[str, Any]:
        return {
            "handler_id": self.config.handler_id,
            "state": self._state.value,
            "memory": self.memory.get_stats(item_uuid),
            "has_pending_command": item_uuid in self._pending_commands,
        }
