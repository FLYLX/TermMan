# Agent System - 技术文档

## 概述

Agent 系统采用**混合存储架构**，结合短期记忆（数据库）和长期记忆（向量数据库），为每个 Item 提供独立的记忆空间。每个 ItemHandler 对应一个 Agent 实例，自动加载启用的 Skills。

---

## 架构设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent System Architecture                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────────┐     ┌────────────────┐     ┌────────────────┐  │
│  │  ItemHandler   │────▶│     Agent      │────▶│     Skills     │  │
│  │  - model       │     │  - handler_id  │     │  - skill_id    │  │
│  │  - api_key     │     │  - skills[]    │     │  - name        │  │
│  │  - enabled_    │     │  - memory      │     │  - trigger     │  │
│  │    skills[]    │     │  - llm_client  │     │  - action      │  │
│  └────────────────┘     └────────────────┘     └────────────────┘  │
│          │                      │                      │            │
│          │                      ▼                      │            │
│          │              ┌────────────────┐             │            │
│          │              │  Memory System │             │            │
│          │              ├────────────────┤             │            │
│          │              │ Short-Term     │             │            │
│          │              │ (SQLite)       │             │            │
│          │              │ - messages[]   │             │            │
│          │              ├────────────────┤             │            │
│          │              │ Long-Term      │             │            │
│          │              │ (ChromaDB)     │             │            │
│          │              │ - embeddings   │             │            │
│          │              │ - documents    │             │            │
│          │              └────────────────┘             │            │
│          │                      │                      │            │
│          ▼                      ▼                      ▼            │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                        Chat Flow                              │  │
│  │  1. Load Agent from ItemHandler                              │  │
│  │  2. Match Skills by user message                             │  │
│  │  3. Load history from SQLite                                 │  │
│  │  4. Search relevant memories from ChromaDB                   │  │
│  │  5. Build System Prompt with Skills + Memories               │  │
│  │  6. Inject context to LLM                                    │  │
│  │  7. Save conversation to SQLite                              │  │
│  │  8. Extract important info to ChromaDB                       │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Agent 架构

### 1. Agent 类

**位置**: `app/services/agent/agent.py`

**核心职责**:
- 一个 ItemHandler 对应一个 Agent 实例
- 自动加载 ItemHandler 配置的 Skills
- 管理记忆（短期 + 长期）
- 处理对话请求

**类设计**:
```python
class Agent:
    _instances: dict[str, "Agent"] = {}  # 单例模式
    
    def __init__(self, handler_id: str):
        self.handler_id = handler_id
        self._context: AgentContext | None = None
        self._skills: dict[str, SkillDefinition] = {}
        self._llm_client: LLMClient | None = None
    
    @classmethod
    def from_handler(cls, handler: ItemHandler) -> "Agent":
        """从 ItemHandler 创建 Agent"""
        ...
    
    def match_skills(self, query: str) -> list[SkillDefinition]:
        """根据用户消息匹配 Skills"""
        ...
    
    def build_system_prompt(self, matched_skills) -> str:
        """构建包含 Skills 的 System Prompt"""
        ...
```

### 2. AgentManager

**位置**: `app/services/agent/agent.py`

**核心职责**:
- 管理 Agent 实例的生命周期
- 缓存 Agent 实例
- 提供 get_or_create 方法

```python
class AgentManager:
    _instance = None  # 单例
    
    def get_or_create(self, handler: ItemHandler) -> Agent:
        """获取或创建 Agent"""
        ...
    
    def get(self, handler_id: str) -> Agent | None:
        """获取 Agent"""
        ...
    
    def remove(self, handler_id: str):
        """移除 Agent"""
        ...
```

---

## Skill 集成

### Skill 加载流程

```
ItemHandler.enabled_skills = ["git_helper", "npm_fixer"]
            │
            ▼
┌─────────────────────────────────────┐
│ Agent.from_handler(handler)         │
│   └─> _load_skills()                │
│        └─> skill_loader.get(id)     │
└─────────────────────────────────────┘
            │
            ▼
Agent._skills = {
    "git_helper": SkillDefinition(...),
    "npm_fixer": SkillDefinition(...),
}
```

### Skill 匹配机制

```python
def match_skills(self, query: str) -> list[SkillDefinition]:
    matched = []
    query_lower = query.lower()
    
    for skill in self._skills.values():
        # 1. 正则匹配 trigger.patterns
        if skill.trigger and skill.trigger.patterns:
            for pattern in skill.trigger.patterns:
                if re.search(pattern, query_lower):
                    matched.append(skill)
                    break
        
        # 2. 关键词匹配（skill_id, name, description）
        else:
            skill_keywords = [
                skill.skill_id.lower(),
                skill.name.lower(),
            ]
            if skill.description:
                skill_keywords.extend(skill.description.lower().split())
            
            for keyword in skill_keywords:
                if keyword in query_lower:
                    matched.append(skill)
                    break
    
    return matched
```

### System Prompt 构建

```python
def build_system_prompt(self, matched_skills) -> str:
    parts = ["You are a helpful AI assistant."]
    
    if matched_skills:
        parts.append("\n## Available Skills:\n")
        for skill in matched_skills:
            parts.append(f"### {skill.name}")
            if skill.description:
                parts.append(f"Description: {skill.description}")
            if skill.content:
                parts.append(f"Instructions:\n{skill.content}")
            parts.append("")
    
    return "\n".join(parts)
```

**生成示例**:
```
You are a helpful AI assistant.

## Available Skills:

### Git Helper
Description: Help with git operations
Instructions:
When user asks about git, provide helpful commands...

### NPM Fixer
Description: Fix npm network errors
Instructions:
When npm install fails with network error...
```

---

## 存储层详解

### 1. 短期记忆 - SQLite

**位置**: `app/models.py` - `ItemChatSession`

**表结构**:
```python
class ItemChatSession(table=True):
    id: uuid.UUID           # 主键
    item_id: uuid.UUID      # 关联的 Item ID（外键）
    messages: List[dict]    # 对话历史（JSON 格式）
    created_at: datetime    # 创建时间
    updated_at: datetime    # 更新时间
```

**特点**:
- 存储完整对话历史
- 支持快速读写
- 页面刷新后恢复对话
- 按 `item_id` 隔离

**API 端点**:
```
GET    /api/v1/memory/{item_id}/session     # 获取对话历史
POST   /api/v1/memory/{item_id}/session     # 保存对话
DELETE /api/v1/memory/{item_id}/session     # 清空对话
```

---

### 2. 长期记忆 - ChromaDB

**位置**: `app/services/agent/memory/vector_store.py`

**存储结构**:
```python
Collection: "item_memories"
├── id: str                    # 记忆唯一 ID
├── embedding: List[float]     # 向量（384 维）
├── document: str              # 原始文本
└── metadata: dict
    ├── item_id: str           # 所属 Item（隔离键）
    ├── type: str              # 记忆类型
    ├── skills: List[str]      # 使用的 Skills
    └── ...                    # 其他元数据
```

**向量模型**: `all-MiniLM-L6-v2`
- 维度: 384
- 大小: ~80MB
- 速度: CPU 友好，5-20ms/条

**持久化**:
- 存储路径: `./chroma_data/`（可配置）
- 配置项: `CHROMA_PERSIST_DIR`

**API 端点**:
```
GET    /api/v1/memory/{item_id}/memories              # 获取所有记忆
GET    /api/v1/memory/{item_id}/memories/search       # 语义检索
POST   /api/v1/memory/{item_id}/memories              # 添加记忆
DELETE /api/v1/memory/{item_id}/memories/{memory_id}  # 删除单条
DELETE /api/v1/memory/{item_id}/memories              # 清空所有
```

---

## Chat 流程

### 完整流程

```
用户发送消息
    │
    ▼
┌─────────────────────────────────────┐
│ 1. 获取 ItemHandler                 │
│    get_item_handler_llm_config()    │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 2. 获取/创建 Agent                  │
│    agent_manager.get_or_create()    │
│    - 加载 enabled_skills            │
│    - 初始化 LLM Client              │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 3. 匹配 Skills                      │
│    agent.match_skills(message)      │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 4. 检索长期记忆                     │
│    vector_store.search_memories()   │
│    query: 用户消息                  │
│    where: {"item_id": xxx}          │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 5. 构建 System Prompt               │
│    build_system_prompt_with_skills()│
│    - Skills 指令                    │
│    - 相关记忆                       │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 6. LLM 生成回复                     │
│    litellm.completion()             │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 7. 保存短期记忆                     │
│    POST /memory/{item_id}/session   │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 8. 提取重要信息 → 长期记忆          │
│    extract_important_info()         │
│    vector_store.add_memory()        │
│    metadata: {skills: [...]}        │
└─────────────────────────────────────┘
```

### Chat API

**位置**: `app/api/routes/chat.py`

```python
@router.post("/{item_id}/stream")
async def chat_stream(item_id: str, request: ChatStreamRequest, ...):
    # 1. 获取 ItemHandler
    handler, item = get_item_handler_llm_config(session, item_id, user)
    
    # 2. 获取 Agent
    agent = agent_manager.get_or_create(handler)
    agent.set_item_context(item_id)
    
    # 3. 流式生成
    return StreamingResponse(
        generate_stream(message, history, handler, item_id),
        media_type="text/event-stream",
    )
```

---

## 代码结构

```
backend/app/
├── models.py                          # ItemChatSession, ItemHandler
├── api/routes/
│   ├── chat.py                        # Chat 端点 + Agent 集成
│   └── memory.py                      # Memory API
└── services/agent/
    ├── __init__.py                    # 导出 Agent, AgentManager
    ├── agent.py                       # Agent 类 + AgentManager
    ├── engine.py                      # AgentEngine（终端自动化）
    ├── handler_manager.py             # HandlerManager
    ├── llm/
    │   ├── llm_client.py              # LLM Client
    │   └── prompt_templates.py        # Prompt 模板
    ├── memory/
    │   ├── vector_store.py            # 向量存储服务
    │   ├── memory_manager.py          # 记忆管理
    │   ├── short_term_memory.py       # 短期记忆
    │   └── item_context.py            # Item 上下文
    └── skills/
        ├── loader.py                  # Skill 加载器
        ├── manager.py                 # Skill 管理器
        └── definition.py              # Skill 定义
```

---

## 前端集成

### ChatPanel 组件

**位置**: `frontend/src/components/Items/ChatPanel.tsx`

**功能**:
1. 加载对话历史
2. 发送消息（SSE 流式）
3. 保存对话
4. 记忆管理 UI

### ItemHandler 配置

**位置**: `frontend/src/components/ItemHandlers/ItemHandlerEdit.tsx`

**功能**:
- 配置 LLM 模型、API Key、API URL
- 选择启用的 Skills（`enabled_skills`）

---

## 配置项

### 环境变量

```bash
# ChromaDB 持久化目录
CHROMA_PERSIST_DIR=./chroma_data
```

### ItemHandler 配置

```python
class ItemHandler(table=True):
    name: str
    model: str | None              # LLM 模型，如 "deepseek/deepseek-chat"
    api_key: str | None            # API Key
    api_url: str | None            # API URL
    enabled_skills: List[str]      # 启用的 Skill IDs
```

---

## 总结

| 特性 | 实现 |
|------|------|
| Agent 实例 | ItemHandler 1:1 Agent |
| Skill 加载 | 自动加载 enabled_skills |
| Skill 匹配 | 正则 + 关键词匹配 |
| 短期记忆 | SQLite (ItemChatSession) |
| 长期记忆 | ChromaDB (Vector Store) |
| 向量化 | all-MiniLM-L6-v2 (本地) |
| 隔离机制 | item_id metadata 过滤 |
| 持久化 | 磁盘存储 (./chroma_data) |
| 前端 UI | 记忆面板 + 对话恢复 |

**设计原则**: 简单、高效、隔离、可扩展
