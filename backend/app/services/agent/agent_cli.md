# Agent 系统架构文档

## 核心概念关系图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              TermMan Agent System                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│    User                                                                          │
│     │ owns                                                                       │
│     ▼                                                                            │
│  ┌────────────────┐         ┌────────────────┐                                  │
│  │     Item       │◄───────►│  ItemHandler   │                                  │
│  │                │  N:N    │                │                                  │
│  │ - id           │         │ - id           │                                  │
│  │ - title        │         │ - name         │                                  │
│  │ - owner_id     │         │ - model        │                                  │
│  └────────────────┘         │ - api_key      │                                  │
│         │                   │ - api_url      │                                  │
│         │                   │ - enabled_     │                                  │
│         │                   │   skills[]     │                                  │
│         │                   └────────────────┘                                  │
│         │                          │                                             │
│         │                          │ 1:1                                        │
│         │                          ▼                                             │
│         │                   ┌────────────────┐                                  │
│         │                   │     Agent      │                                  │
│         │                   │                │                                  │
│         │                   │ - handler_id   │                                  │
│         │                   │ - _skills{}    │                                  │
│         │                   └────────────────┘                                  │
│         │                          │                                             │
│         │                          │ 反射加载                                    │
│         │                          ▼                                             │
│         │                   ┌────────────────┐                                  │
│         │                   │     Skill      │                                  │
│         │                   │                │                                  │
│         │                   │ - skill_id     │                                  │
│         │                   │ - name         │                                  │
│         │                   │ - trigger      │                                  │
│         │                   └────────────────┘                                  │
│         │                                                                         │
│         │ has                                                                     │
│         ▼                                                                         │
│  ┌────────────────┐         ┌────────────────┐                                  │
│  │ ItemChatSession│         │   Memory       │                                  │
│  │ (Short-Term)   │         │ (Long-Term)    │                                  │
│  │                │         │                │                                  │
│  │ - item_id      │         │ - item_id      │                                  │
│  │ - messages[]   │         │ - embedding    │                                  │
│  └────────────────┘         │ - document     │                                  │
│                             └────────────────┘                                  │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
services/agent/
├── __init__.py              # 导出 Agent, AgentManager, agent_manager
├── agent.py                 # Agent 核心类（135 行）
├── agent_cli.md             # 本文档
│
├── memory/
│   ├── __init__.py          # 导出 VectorStoreService, vector_store
│   └── vector_store.py      # 向量存储（长期记忆 + Embedding）
│
└── skills/
    ├── __init__.py          # 导出 skill_loader, skill_manager
    ├── definition.py        # SkillDefinition 数据类
    ├── loader.py            # SkillLoader（扫描加载 SKILL.md）
    └── manager.py           # SkillManager（CRUD API 用）
```

---

## 核心组件

### 1. Agent（智能代理）

**文件**: `agent.py`

**职责**:
- 一个 ItemHandler 对应一个 Agent 单例
- 反射加载 ItemHandler.enabled_skills 指定的 Skills
- 匹配用户消息与 Skills

**核心代码**:
```python
class Agent:
    _instances: dict[str, "Agent"] = {}  # 单例缓存
    
    def __init__(self, handler_id: str):
        self.handler_id = handler_id
        self._context: AgentContext | None = None
        self._skills: dict[str, SkillDefinition] = {}  # 私有字典，Agent 隔离
    
    def _load_skills(self):
        """反射加载 - 通过 skill_id 字符串动态获取"""
        self._skills.clear()
        for skill_id in self._context.enabled_skills:
            skill = skill_loader.get(skill_id)  # 反射获取，不 import
            if skill:
                self._skills[skill_id] = skill
    
    def reload_skills(self):
        """热重载"""
        self._load_skills()
    
    def match_skills(self, query: str) -> list[SkillDefinition]:
        """匹配用户消息与 Skills"""
        ...
```

### 2. AgentManager（代理管理器）

**文件**: `agent.py`

**职责**:
- 单例模式管理所有 Agent 实例
- 自动更新 Agent 的 skills 配置

```python
class AgentManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._agents = {}
        return cls._instance
    
    def get_or_create(self, handler: ItemHandler) -> Agent:
        handler_id = str(handler.id)
        if handler_id in self._agents:
            agent = self._agents[handler_id]
            agent.update_skills(handler.enabled_skills or [])  # 热更新
            return agent
        agent = Agent.from_handler(handler)
        self._agents[handler_id] = agent
        return agent
```

### 3. SkillLoader（技能加载器）

**文件**: `skills/loader.py`

**职责**:
- 启动时扫描 `backend/skills/` 目录
- 解析 SKILL.md 的 YAML Frontmatter
- 缓存到内存字典

```python
class SkillLoader:
    def __init__(self, skills_dir: Path | None = None):
        self.skills_dir = skills_dir or Path("backend/skills/")
        self._skills: dict[str, SkillDefinition] = {}
        self._load_all()
    
    def get(self, skill_id: str) -> SkillDefinition | None:
        return self._skills.get(skill_id)  # O(1) 查找
```

### 4. VectorStoreService（向量存储）

**文件**: `memory/vector_store.py`

**职责**:
- Embedding: `all-MiniLM-L6-v2` 模型
- 向量存储: ChromaDB 持久化
- Item 隔离: `where={"item_id": xxx}`

```python
class VectorStoreService:
    def add_memory(self, item_id: str, content: str, metadata: dict) -> str:
        embedding = self._embedding_service.encode_single(content)
        self._collection.add(
            ids=[memory_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[{"item_id": item_id, **metadata}],
        )
    
    def search_memories(self, item_id: str, query: str, n_results: int = 3):
        embedding = self._embedding_service.encode_single(query)
        return self._collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where={"item_id": item_id},  # Item 隔离
        )
```

---

## Skill 存储格式

### 目录结构

```
backend/skills/
├── git_helper/
│   ├── SKILL.md           # 必需
│   ├── scripts/           # 可选
│   ├── templates/         # 可选
│   └── examples/          # 可选
│
└── npm_fixer/
    └── SKILL.md
```

### SKILL.md 格式

```yaml
---
skill_id: git_helper
name: Git 辅助
description: 自动处理常见的 Git 操作和错误
category: vcs
trigger:
  type: event
  patterns:
    - git
    - fatal
    - CONFLICT
action:
  type: llm
  prompt: |
    检测到 Git 问题...
safety:
  requires_approval: true
  risk_level: medium
---

# Markdown 内容（Skill 指令）

自动处理常见的 Git 操作和错误...
```

---

## 数据流

### Chat 请求流程

```
用户消息: "帮我解决 git 冲突"
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. 查询 Item → ItemHandler                                   │
│    ItemHandler.enabled_skills = ["git_helper", "npm_fixer"] │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Agent 反射加载 Skills                                     │
│    agent._skills = {                                        │
│      "git_helper": skill_loader.get("git_helper"),          │
│      "npm_fixer": skill_loader.get("npm_fixer"),            │
│    }                                                        │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 匹配 Skills                                               │
│    matched = agent.match_skills("git 冲突")                 │
│    → [git_helper]                                           │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. 检索长期记忆                                              │
│    memories = vector_store.search_memories(item_id, query)  │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. 构建 System Prompt                                        │
│    - Your Loaded Skills: [git_helper, npm_fixer]            │
│    - Skills Relevant to Current Query: [git_helper]         │
│    - Relevant Memories: [...]                               │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. LLM 生成回复                                              │
│    litellm.completion(model, messages)                      │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. 保存记忆                                                  │
│    - Short-Term: ItemChatSession.messages.append()          │
│    - Long-Term: vector_store.add_memory()                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 关系总结

| 实体 A | 关系 | 实体 B | 说明 |
|--------|------|--------|------|
| User | 1:N | Item | 用户拥有多个 Item |
| Item | N:N | ItemHandler | Item 可关联多个 ItemHandler |
| ItemHandler | 1:1 | Agent | 一个 ItemHandler 对应一个 Agent 实例 |
| ItemHandler | 1:N | Skill | ItemHandler 启用多个 Skills |
| Item | 1:1 | ItemChatSession | Item 有一个对话会话 |
| Item | 1:N | Memory | Item 有多条长期记忆 |

---

## API 端点

### Chat API
```
POST /api/v1/chat/{item_id}             # 发送消息
POST /api/v1/chat/{item_id}/stream      # 流式发送消息
GET  /api/v1/chat/{item_id}/skills      # 获取匹配的 Skills
```

### Memory API
```
GET    /api/v1/memory/{item_id}/session           # 获取对话历史
DELETE /api/v1/memory/{item_id}/session           # 清空对话
GET    /api/v1/memory/{item_id}/memories          # 获取所有记忆
POST   /api/v1/memory/{item_id}/memories          # 添加记忆
DELETE /api/v1/memory/{item_id}/memories/{id}     # 删除单条
```

### Skill API
```
GET    /api/v1/skills/                    # 列出所有 Skills
POST   /api/v1/skills/                    # 创建 Skill
GET    /api/v1/skills/{id}                # 获取 Skill
PUT    /api/v1/skills/{id}                # 更新 Skill
DELETE /api/v1/skills/{id}                # 删除 Skill
```

---

## 核心设计原则

### 1. 反射加载
- 不硬编码 Skill
- 不 import 任何 Skill
- 完全通过 `skill_id` 字符串从 `SkillLoader.get()` 动态获取

### 2. Agent 隔离
- 每个 Agent 有独立的 `_skills` 字典
- 不同 Agent 之间技能完全隔离

### 3. 热重载
- 修改 `ItemHandler.enabled_skills` 后
- 调用 `agent.reload_skills()` 立即生效
- 无需重启服务

### 4. Item 记忆隔离
- ChromaDB 使用 `where={"item_id": xxx}` 过滤
- 每个 Item 的记忆完全隔离
