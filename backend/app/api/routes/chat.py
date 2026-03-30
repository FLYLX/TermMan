import asyncio
import json
import logging
import queue
import re
import threading
import time
from typing import Any, Generator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep
from app.models import Item, ItemHandler, ItemHandlerItem, ItemChatSession
from app.services.agent.memory.vector_store import vector_store
from app.services.agent.agent import agent_manager
from app.services.agent.stream_manager import stream_manager
from app.services.agent.item_handler_context import item_handler_context

from litellm import completion

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1
REQUEST_TIMEOUT = 120

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class ChatStreamRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


def get_item_handler_llm_config(
    session: Session, item_id: str, user: CurrentUser
) -> tuple[ItemHandler, Item] | None:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    handler_item = session.exec(
        select(ItemHandlerItem).where(ItemHandlerItem.item_id == item_id)
    ).first()
    
    if not handler_item:
        return None
    
    handler = session.get(ItemHandler, handler_item.item_handler_id)
    if not handler:
        return None
    
    return handler, item


def get_or_create_chat_session(session: Session, item_id: str) -> ItemChatSession:
    chat_session = session.exec(
        select(ItemChatSession).where(ItemChatSession.item_id == item_id)
    ).first()
    
    if not chat_session:
        chat_session = ItemChatSession(item_id=item_id, messages=[])
        session.add(chat_session)
        session.commit()
        session.refresh(chat_session)
    
    return chat_session


def get_relevant_memories(item_id: str, query: str, n_results: int = 3) -> str:
    try:
        memories = vector_store.search_memories(
            item_id=item_id,
            query=query,
            n_results=n_results,
        )
        
        if not memories:
            return ""
        
        memory_texts = []
        for m in memories:
            memory_texts.append(f"- {m['content']}")
        
        return "\n".join(memory_texts)
    except Exception as e:
        logger.warning(f"[Chat] Failed to retrieve memories: {e}")
        return ""


def extract_important_info(user_msg: str, assistant_msg: str) -> str | None:
    if len(user_msg) < 20 and len(assistant_msg) < 50:
        return None
    
    important_keywords = [
        "password", "密码", "key", "密钥", "token",
        "config", "配置", "setting", "设置",
        "error", "错误", "bug", "问题",
        "solution", "解决方案", "fix", "修复",
        "important", "重要", "remember", "记住",
    ]
    
    combined = f"{user_msg} {assistant_msg}".lower()
    if any(kw in combined for kw in important_keywords):
        return f"User: {user_msg}\nAssistant: {assistant_msg}"
    
    return None


def build_system_prompt_with_skills(
    handler: ItemHandler,
    message: str,
    agent: "Agent" = None,
    memories: str = "",
) -> tuple[str, list, list[dict]]:
    if agent is None:
        agent = agent_manager.get_or_create(handler)
    
    all_skills = agent.get_skills()
    matched_skills = agent.match_skills(message)
    tools = agent.get_tools_for_litellm()
    
    parts = ["You are a helpful AI assistant."]
    
    if all_skills:
        parts.append("\n## Your Loaded Skills:\n")
        parts.append("You have the following skills loaded. When user asks about your skills, list them:\n")
        for skill in all_skills:
            parts.append(f"- **{skill.name}** (ID: {skill.skill_id})")
            if skill.description:
                parts.append(f"  Description: {skill.description}")
        parts.append("")
    
    if matched_skills:
        parts.append("\n## Skills Relevant to Current Query:\n")
        for skill in matched_skills:
            parts.append(f"### {skill.name}")
            if skill.description:
                parts.append(f"Description: {skill.description}")
            
            if skill.action and skill.action.prompt:
                parts.append(f"\n{skill.action.prompt}\n")
            
            if skill.content:
                content_without_frontmatter = skill.content
                match = re.match(r"^---\s*\n.*?\n---\s*\n", skill.content, re.DOTALL)
                if match:
                    content_without_frontmatter = skill.content[match.end():].strip()
                if content_without_frontmatter:
                    parts.append(f"Additional Info:\n{content_without_frontmatter}")
            parts.append("")
    
    if memories:
        parts.append(f"\n## Relevant Memories:\n{memories}")
    
    return "\n".join(parts), matched_skills, tools


def generate_stream(
    message: str,
    history: list[ChatMessage],
    handler: ItemHandler,
    item_id: str,
    agent: "Agent" = None,
) -> Generator[str, None, None]:
    memories = get_relevant_memories(item_id, message)
    system_prompt, matched_skills, tools = build_system_prompt_with_skills(handler, message, agent, memories)
    
    logger.info(f"[Chat] Tools count: {len(tools)}, Skills: {[s.skill_id for s in matched_skills]}")
    logger.info(f"[Chat] System prompt length: {len(system_prompt)}, Tools: {[t.get('function', {}).get('name') for t in tools]}")
    
    messages = [{"role": "system", "content": system_prompt}]
    
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})
    
    messages.append({"role": "user", "content": message})
    
    AgentMessageQueue.clear_abort(item_id)
    
    full_content = ""
    last_error = None
    max_iterations = 10
    tool_call_history: list[tuple[str, str]] = []
    
    for iteration in range(max_iterations):
        if AgentMessageQueue.is_aborted(item_id):
            yield f"data: {json.dumps({'type': 'aborted', 'content': '对话已中断'})}\n\n"
            return
        
        kwargs: dict[str, Any] = {
            "model": handler.model,
            "messages": messages,
            "stream": True,
            "timeout": REQUEST_TIMEOUT,
            "temperature": 0.1,
        }
        
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
            logger.info(f"[Chat] Passing {len(tools)} tools to LLM: {[t.get('function', {}).get('name') for t in tools]}")
        
        if handler.api_key:
            kwargs["api_key"] = handler.api_key
        if handler.api_url:
            kwargs["api_base"] = handler.api_url
        
        for attempt in range(MAX_RETRIES):
            try:
                response = completion(**kwargs)
                
                tool_calls_map = {}
                iteration_content = ""
                
                for chunk in response:
                    delta = chunk.choices[0].delta
                    finish_reason = chunk.choices[0].finish_reason
                    
                    if delta and delta.content:
                        content = delta.content
                        iteration_content += content
                        full_content += content
                        yield f"data: {json.dumps({'content': content})}\n\n"
                    
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = getattr(tc, 'index', 0)
                            if idx not in tool_calls_map:
                                tool_calls_map[idx] = {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""}
                                }
                            
                            if hasattr(tc, 'id') and tc.id:
                                tool_calls_map[idx]["id"] = tc.id
                            if hasattr(tc, 'function') and tc.function:
                                if hasattr(tc.function, 'name') and tc.function.name:
                                    tool_calls_map[idx]["function"]["name"] += tc.function.name
                                if hasattr(tc.function, 'arguments') and tc.function.arguments:
                                    tool_calls_map[idx]["function"]["arguments"] += tc.function.arguments
                
                if tool_calls_map:
                    logger.info(f"[Chat] Iteration {iteration}: Accumulated tool calls: {tool_calls_map}")
                    
                    assistant_message = {
                        "role": "assistant",
                        "content": iteration_content or "",
                        "tool_calls": []
                    }
                    
                    tool_results = []
                    
                    for idx in sorted(tool_calls_map.keys()):
                        if AgentMessageQueue.is_aborted(item_id):
                            yield f"data: {json.dumps({'type': 'aborted', 'content': '对话已中断'})}\n\n"
                            return
                        
                        tc = tool_calls_map[idx]
                        if tc["id"] and tc["function"]["name"]:
                            tool_name = tc["function"]["name"]
                            tool_args_str = tc["function"]["arguments"]
                            
                            call_signature = f"{tool_name}:{tool_args_str}"
                            tool_call_history.append((tool_name, tool_args_str))
                            
                            recent_calls = tool_call_history[-6:]
                            if len(recent_calls) >= 4:
                                call_counts = {}
                                for call in recent_calls:
                                    call_counts[call] = call_counts.get(call, 0) + 1
                                
                                for call_sig, count in call_counts.items():
                                    if count >= 3:
                                        logger.warning(f"[Chat] Detected loop: {call_sig[0]} called {count} times")
                                        yield f"data: {json.dumps({'warning': f'检测到循环调用，已终止。工具 {call_sig[0]} 重复调用 {count} 次。'})}\n\n"
                                        yield f"data: {json.dumps({'done': True})}\n\n"
                                        return
                            
                            try:
                                tool_args = json.loads(tool_args_str) if tool_args_str else {}
                            except json.JSONDecodeError:
                                logger.error(f"[Chat] Failed to parse tool args: {tool_args_str}")
                                continue
                            
                            tool_args["item_id"] = item_id
                            logger.info(f"[Chat] Force set item_id: {item_id}")
                            
                            if tool_name == "mcp_local_execute_command":
                                stream_manager.open_agent_window(item_id, message)
                            
                            logger.info(f"[Chat] Executing tool: {tool_name} with args: {tool_args}")
                            yield f"data: {json.dumps({'tool_call': {'name': tool_name, 'args': tool_args}})}\n\n"
                            
                            from app.services.agent.agent import agent_manager
                            agent = agent_manager.get_or_create(handler)
                            
                            import asyncio
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                result = loop.run_until_complete(agent.execute_tool(tool_name, tool_args))
                            finally:
                                loop.close()
                            
                            logger.info(f"[Chat] Tool result: {result}")
                            
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
                            
                            yield f"data: {json.dumps({'tool_result': {'name': tool_name, 'result': result_text}})}\n\n"
                            
                            assistant_message["tool_calls"].append({
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["function"]["name"],
                                    "arguments": tc["function"]["arguments"]
                                }
                            })
                            
                            tool_results.append({
                                "tool_call_id": tc["id"],
                                "content": result_text
                            })
                    
                    messages.append(assistant_message)
                    for tr in tool_results:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tr["tool_call_id"],
                            "content": tr["content"]
                        })
                    
                    continue
                
                yield f"data: {json.dumps({'done': True})}\n\n"
                
                important_info = extract_important_info(message, full_content)
                if important_info:
                    metadata = {"type": "conversation"}
                    if matched_skills:
                        metadata["skills"] = [s.skill_id for s in matched_skills]
                    vector_store.add_memory(
                        item_id=item_id,
                        content=important_info,
                        metadata=metadata,
                    )
                return
                
            except Exception as e:
                last_error = e
                logger.warning(f"[Chat] Stream attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
    
    logger.error(f"[Chat] Stream error after {MAX_RETRIES} retries: {last_error}")
    yield f"data: {json.dumps({'error': str(last_error)})}\n\n"


@router.post("/{item_id}")
async def chat(
    item_id: str,
    request: ChatRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict:
    result = get_item_handler_llm_config(session, item_id, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="No handler found for this item")
    
    handler, item = result
    
    if not handler.model:
        raise HTTPException(status_code=400, detail="Handler has no model configured")
    
    agent = agent_manager.get_or_create(handler)
    agent.set_item_context(item_id, item)
    
    item_handler_context.set_handler(item_id, str(handler.id))
    
    await agent.start_mcp_servers()
    
    memories = get_relevant_memories(item_id, request.message)
    system_prompt, matched_skills, tools = build_system_prompt_with_skills(handler, request.message, memories)
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in request.history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": request.message})
    
    kwargs: dict[str, Any] = {
        "model": handler.model,
        "messages": messages,
        "timeout": REQUEST_TIMEOUT,
    }
    
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    
    if handler.api_key:
        kwargs["api_key"] = handler.api_key
    if handler.api_url:
        kwargs["api_base"] = handler.api_url
    
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = completion(**kwargs)
            message = response.choices[0].message
            
            if hasattr(message, 'tool_calls') and message.tool_calls:
                messages.append({"role": "assistant", "content": message.content or "", "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]})
                
                agent = agent_manager.get_or_create(handler)
                
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)
                    
                    logger.info(f"[Chat] Tool call: {tool_name} with args: {tool_args}")
                    
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(agent.execute_tool(tool_name, tool_args))
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": json.dumps(result)
                    })
                
                kwargs["messages"] = messages
                response = completion(**kwargs)
                message = response.choices[0].message
            
            content = message.content
            
            chat_session = get_or_create_chat_session(session, item_id)
            chat_session.messages.append({"role": "user", "content": request.message})
            chat_session.messages.append({"role": "assistant", "content": content})
            session.commit()
            
            important_info = extract_important_info(request.message, content)
            if important_info:
                metadata = {"type": "conversation"}
                if matched_skills:
                    metadata["skills"] = [s.skill_id for s in matched_skills]
                vector_store.add_memory(
                    item_id=item_id,
                    content=important_info,
                    metadata=metadata,
                )
            
            return {
                "content": content,
                "model": handler.model,
                "matched_skills": [s.skill_id for s in matched_skills],
            }
        except Exception as e:
            last_error = e
            logger.warning(f"[Chat] Attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
    
    logger.error(f"[Chat] Error after {MAX_RETRIES} retries: {last_error}")
    raise HTTPException(status_code=500, detail=str(last_error))


@router.post("/{item_id}/stream")
async def chat_stream(
    item_id: str,
    request: ChatStreamRequest,
    session: SessionDep,
    current_user: CurrentUser,
):
    logger.info(f"[Chat] Stream request for item_id: {item_id}")
    
    result = get_item_handler_llm_config(session, item_id, current_user)
    if not result:
        logger.warning(f"[Chat] No ItemHandler found for item_id: {item_id}")
        raise HTTPException(
            status_code=404, 
            detail="No ItemHandler associated with this item. Please associate an ItemHandler first."
        )
    
    handler, item = result
    logger.info(f"[Chat] Found handler: {handler.name}, model: {handler.model}")
    
    if not handler.model:
        raise HTTPException(
            status_code=400, 
            detail=f"ItemHandler '{handler.name}' has no model configured. Please configure a model."
        )
    
    agent = agent_manager.get_or_create(handler)
    agent.set_item_context(item_id, item)
    
    item_handler_context.set_handler(item_id, str(handler.id))
    
    await agent.start_mcp_servers()
    
    logger.info(f"[Chat] Agent loaded with {len(agent.get_skills())} skills, {len(agent.get_mcp_servers())} MCP servers, {len(agent.get_tools_for_litellm())} tools")
    
    return StreamingResponse(
        generate_stream(
            message=request.message,
            history=request.history,
            handler=handler,
            item_id=item_id,
            agent=agent,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{item_id}/skills")
async def get_matched_skills(
    item_id: str,
    query: str,
    session: SessionDep,
    current_user: CurrentUser,
):
    result = get_item_handler_llm_config(session, item_id, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="No handler found for this item")
    
    handler, item = result
    
    agent = agent_manager.get_or_create(handler)
    matched = agent.match_skills(query)
    
    return {
        "matched_skills": [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "description": s.description,
            }
            for s in matched
        ]
    }


class AgentMessageQueue:
    _queues: dict[str, queue.Queue] = {}
    _abort_flags: dict[str, bool] = {}
    _lock = threading.Lock()
    
    @classmethod
    def get_queue(cls, item_id: str) -> queue.Queue:
        with cls._lock:
            if item_id not in cls._queues:
                cls._queues[item_id] = queue.Queue()
            return cls._queues[item_id]
    
    @classmethod
    def put_message(cls, item_id: str, message: dict):
        with cls._lock:
            if item_id in cls._queues:
                cls._queues[item_id].put(message)
    
    @classmethod
    def remove_queue(cls, item_id: str):
        with cls._lock:
            if item_id in cls._queues:
                del cls._queues[item_id]
            if item_id in cls._abort_flags:
                del cls._abort_flags[item_id]
    
    @classmethod
    def set_abort(cls, item_id: str, abort: bool = True):
        with cls._lock:
            cls._abort_flags[item_id] = abort
    
    @classmethod
    def is_aborted(cls, item_id: str) -> bool:
        with cls._lock:
            return cls._abort_flags.get(item_id, False)
    
    @classmethod
    def clear_abort(cls, item_id: str):
        with cls._lock:
            cls._abort_flags.pop(item_id, None)


def _agent_message_callback(item_id: str):
    def callback(message: dict):
        AgentMessageQueue.put_message(item_id, message)
    return callback


@router.get("/{item_id}/agent-events")
async def agent_events(
    item_id: str,
    session: SessionDep,
    current_user: CurrentUser,
):
    result = get_item_handler_llm_config(session, item_id, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="No handler found for this item")
    
    handler, _ = result
    
    stream_manager.register_chat(
        item_id, 
        _agent_message_callback(item_id)
    )
    
    msg_queue = AgentMessageQueue.get_queue(item_id)
    
    def event_generator():
        try:
            while True:
                try:
                    message = msg_queue.get(timeout=30)
                    yield f"data: {json.dumps(message)}\n\n"
                except queue.Empty:
                    yield f": heartbeat\n\n"
        except GeneratorExit:
            stream_manager.unregister_chat(item_id)
            AgentMessageQueue.remove_queue(item_id)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{item_id}/abort")
async def abort_chat(
    item_id: str,
    session: SessionDep,
    current_user: CurrentUser,
):
    result = get_item_handler_llm_config(session, item_id, current_user)
    if not result:
        raise HTTPException(status_code=404, detail="No handler found for this item")
    
    AgentMessageQueue.set_abort(item_id, True)
    AgentMessageQueue.put_message(item_id, {
        "type": "aborted",
        "content": "用户中断了对话",
        "timestamp": time.time(),
    })
    
    logger.info(f"[Chat] Aborted chat for item_id: {item_id}")
    
    return {"success": True, "message": "Chat aborted"}
