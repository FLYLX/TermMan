# ItemHandler Agent层架构设计文档

## 一、架构概览

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Daemon (终端进程)                                    │
│                                  ↓ 输出流                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ↓
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Backend Socket层                                    │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  ItemSocket (socket_pool/item_socket.py)                                  │   │
│  │  - 接收 ProtocolEvents.STREAM 事件                                        │   │
│  │  - 回调: on_stream(data) → stdout/stderr/stdin                           │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ↓ 【SDK监听注入点】
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Agent SDK Layer (新增)                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  AgentStreamSDK                                                           │   │
│  │  - 订阅终端输出流                                                         │  
│  │  - 提供标准化的输出事件接口                                               │   │
│  │  - 支持多个Agent实例同时监听                                              │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ↓
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         ItemHandler Agent核心层                                  │
│                                                                                 │
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌───────────────────┐  │
│  │   Input Filter      │    │   Agent Core        │    │  Output Filter    │  │
│  │   (输入过滤层)       │───→│   (Agent核心)        │───→│  (输出过滤层)      │  │
│  │                     │    │                     │    │                   │  │
│  │  - PatternMatcher   │    │  - LLMClient        │    │  - CommandFilter  │  │
│  │  - EventClassifier  │    │  - ContextManager   │    │  - SafetyChecker  │  │
│  │  - NoiseReducer     │    │  - ActionPlanner    │    │  - RateLimiter    │  │
│  └─────────────────────┘    └─────────────────────┘    └───────────────────┘  │
│           │                          │                          │              │
│           ↓                          ↓                          ↓              │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                        Memory System (记忆系统)                          │   │
│  │  - ShortTermMemory: 会话级记忆 (最近N条交互)                             │   │
│  │  - LongTermMemory: 持久化记忆 (向量存储)                                 │   │
│  │  - ItemContext: Item特定上下文                                          │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         ↓
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           Terminal Service层                                     │
│  - write_to_terminal(item_uuid, command)                                        │
│  - 执行经过安全检查的命令                                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、文件结构设计

```
backend/
├── app/
│   ├── services/
│   │   ├── agent/                          # 新增: Agent层核心目录
│   │   │   ├── __init__.py
│   │   │   │
│   │   │   ├── core/                       # Agent核心模块
│   │   │   │   ├── __init__.py
│   │   │   │   ├── agent_engine.py         # Agent主引擎
│   │   │   │   ├── agent_context.py        # Agent上下文管理
│   │   │   │   └── action_planner.py       # 行动规划器
│   │   │   │
│   │   │   ├── filters/                    # 过滤器模块
│   │   │   │   ├── __init__.py
│   │   │   │   ├── input_filter.py         # 输入过滤器(终端输出→Agent)
│   │   │   │   ├── output_filter.py        # 输出过滤器(Agent→终端)
│   │   │   │   ├── pattern_matcher.py      # 模式匹配器
│   │   │   │   ├── command_validator.py    # 命令验证器
│   │   │   │   └── sensitive_filter.py     # 敏感词过滤器
│   │   │   │
│   │   │   ├── memory/                     # 记忆系统
│   │   │   │   ├── __init__.py
│   │   │   │   ├── memory_manager.py       # 记忆管理器
│   │   │   │   ├── short_term_memory.py    # 短期记忆
│   │   │   │   ├── long_term_memory.py     # 长期记忆(向量存储)
│   │   │   │   └── item_context.py         # Item特定上下文
│   │   │   │
│   │   │   ├── llm/                        # LLM集成模块
│   │   │   │   ├── __init__.py
│   │   │   │   ├── llm_client.py           # LLM客户端抽象
│   │   │   │   ├── openai_client.py        # OpenAI实现
│   │   │   │   ├── anthropic_client.py     # Anthropic实现
│   │   │   │   └── prompt_templates.py     # Prompt模板
│   │   │   │
│   │   │   ├── sdk/                        # Agent SDK层
│   │   │   │   ├── __init__.py
│   │   │   │   ├── stream_sdk.py           # 输出流SDK
│   │   │   │   ├── event_bus.py            # 事件总线
│   │   │   │   └── agent_subscriber.py     # Agent订阅者接口
│   │   │   │
│   │   │   ├── handlers/                   # ItemHandler实例管理
│   │   │   │   ├── __init__.py
│   │   │   │   ├── handler_manager.py      # Handler管理器
│   │   │   │   ├── handler_instance.py     # Handler实例
│   │   │   │   └── handler_config.py       # Handler配置
│   │   │   │
│   │   │   └── safety/                     # 安全模块
│   │   │       ├── __init__.py
│   │   │       ├── safety_checker.py       # 安全检查器
│   │   │       ├── command_whitelist.py    # 命令白名单
│   │   │       └── risk_assessor.py        # 风险评估器
│   │   │
│   │   ├── socket_pool/                    # 现有: Socket连接池
│   │   │   └── item_socket.py              # 【修改点】注入SDK回调
│   │   │
│   │   └── terminal_service.py             # 【修改点】集成Agent层
│   │
│   ├── models.py                           # 【修改点】扩展ItemHandler模型
│   │
│   └── api/
│       └── routes/
│           ├── item_handlers.py            # 现有: Handler CRUD
│           └── agent_routes.py             # 新增: Agent API路由
```

---

## 三、核心组件设计

### 3.1 Agent SDK层 - 输出流监听注入点

**位置**: `app/services/agent/sdk/stream_sdk.py`

**设计思路**: 在现有的 `ItemSocket.on_stream()` 回调链中注入SDK层，作为Agent层的统一入口。

```python
class AgentStreamSDK:
    """
    Agent输出流SDK - 订阅终端输出，分发给所有注册的Agent
    
    注入点: ItemSocket.on_stream() → AgentStreamSDK.dispatch() → Agent实例
    """
    
    def __init__(self):
        self._subscribers: Dict[str, List[AgentSubscriber]] = {}
        self._event_bus = EventBus()
    
    def subscribe(self, item_uuid: str, subscriber: "AgentSubscriber"):
        """订阅指定item的输出流"""
        
    def unsubscribe(self, item_uuid: str, subscriber_id: str):
        """取消订阅"""
        
    def dispatch(self, item_uuid: str, stream_data: Dict):
        """
        分发输出流数据
        被ItemSocket.on_stream()调用
        """
        
    def get_sdk_interface(self, item_uuid: str) -> "StreamSDKInterface":
        """获取SDK接口，供外部使用"""
```

**修改点**: `app/services/socket_pool/item_socket.py`

```python
# 在 ItemSocket.on_stream() 中添加:
def on_stream(data):
    # 现有逻辑: 写日志
    if ProtocolEvents.STREAM in self.callbacks:
        self.callbacks[ProtocolEvents.STREAM](data)
    
    # 新增: 注入SDK分发
    agent_sdk.dispatch(self.item_uuid, data)  # ← 新增
```

---

### 3.2 输入过滤层 (Input Filter)

**位置**: `app/services/agent/filters/input_filter.py`

**功能**: 过滤终端输出，只将有价值的信息传递给Agent

```python
class InputFilter:
    """
    输入过滤器 - 从终端输出中提取有价值信息
    
    过滤策略:
    1. PatternMatcher: 匹配关键模式 (错误、警告、提示符等)
    2. EventClassifier: 分类事件类型 (需要Action/仅记录/忽略)
    3. NoiseReducer: 降低噪音 (重复行、进度条等)
    """
    
    def __init__(self, config: "InputFilterConfig"):
        self.pattern_matcher = PatternMatcher(config.patterns)
        self.event_classifier = EventClassifier()
        self.noise_reducer = NoiseReducer()
    
    def filter(self, stream_data: Dict) -> Optional["FilteredEvent"]:
        """
        过滤输出数据
        
        Returns:
            FilteredEvent: 有价值的事件，或None(忽略)
        """
        stdout = stream_data.get("stdout", "")
        stderr = stream_data.get("stderr", "")
        
        # 降噪处理
        cleaned = self.noise_reducer.reduce(stdout + stderr)
        if not cleaned:
            return None
        
        # 模式匹配
        matches = self.pattern_matcher.match(cleaned)
        
        # 事件分类
        event_type = self.event_classifier.classify(cleaned, matches)
        
        return FilteredEvent(
            raw_content=cleaned,
            event_type=event_type,
            matches=matches,
            timestamp=datetime.now()
        )


class PatternMatcher:
    """模式匹配器 - 匹配预定义的正则模式"""
    
    DEFAULT_PATTERNS = {
        "error": [r"error:", r"failed:", r"exception:"],
        "warning": [r"warning:", r"warn:"],
        "prompt": [r"\$\s*$", r"#\s*$", r">>>\s*$"],
        "progress": [r"\d+%", r"\[\s*=+\s*\]"],
        "input_required": [r"\(y/n\)", r"enter.*:", r"password:"],
    }
    
    def match(self, content: str) -> List["PatternMatch"]:
        """返回所有匹配的模式"""


class EventClassifier:
    """事件分类器"""
    
    class EventType(Enum):
        NEEDS_ACTION = "needs_action"      # 需要Agent响应
        INFORMATIONAL = "informational"    # 信息性，可记录
        NOISE = "noise"                    # 噪音，忽略
    
    def classify(self, content: str, matches: List) -> EventType:
        """根据内容和匹配结果分类事件"""
```

---

### 3.3 输出过滤层 (Output Filter)

**位置**: `app/services/agent/filters/output_filter.py`

**功能**: 过滤Agent生成的命令，防止执行敏感/危险操作

```python
class OutputFilter:
    """
    输出过滤器 - 安全检查Agent生成的命令
    
    过滤策略:
    1. CommandFilter: 命令过滤 (黑名单/白名单)
    2. SafetyChecker: 安全检查 (危险操作检测)
    3. RateLimiter: 频率限制 (防止命令风暴)
    4. SensitiveDataFilter: 敏感数据过滤
    """
    
    def __init__(self, config: "OutputFilterConfig"):
        self.command_filter = CommandFilter(config)
        self.safety_checker = SafetyChecker(config)
        self.rate_limiter = RateLimiter(config.rate_limit)
        self.sensitive_filter = SensitiveDataFilter(config.sensitive_patterns)
    
    def filter(self, command: str, context: "AgentContext") -> "FilterResult":
        """
        过滤命令
        
        Returns:
            FilterResult:
                - ALLOWED: 允许执行
                - BLOCKED: 阻止执行
                - MODIFIED: 修改后执行
                - NEEDS_APPROVAL: 需要人工审批
        """
        # 频率检查
        if not self.rate_limiter.allow(context.item_uuid):
            return FilterResult.BLOCKED("Rate limit exceeded")
        
        # 敏感数据检查
        if self.sensitive_filter.contains_sensitive(command):
            return FilterResult.BLOCKED("Contains sensitive data")
        
        # 命令过滤
        filter_result = self.command_filter.check(command)
        if filter_result.is_blocked:
            return FilterResult.BLOCKED(filter_result.reason)
        
        # 安全检查
        safety_result = self.safety_checker.assess(command, context)
        if safety_result.risk_level == RiskLevel.HIGH:
            return FilterResult.NEEDS_APPROVAL(safety_result.reason)
        
        # 修改命令 (如添加sudo检查等)
        modified_command = self._modify_if_needed(command)
        
        return FilterResult.ALLOWED(modified_command)


class CommandFilter:
    """命令过滤器"""
    
    # 默认黑名单 - 危险命令
    DEFAULT_BLACKLIST = [
        r"rm\s+-rf\s+/",
        r"mkfs",
        r"dd\s+if=",
        r">\s*/dev/sd",
        r":(){ :|:& };:",  # Fork bomb
        r"chmod\s+777",
        r"chown\s+.*:.*\s+/",
    ]
    
    # 默认白名单 - 安全命令
    DEFAULT_WHITELIST = [
        r"ls", r"cat", r"grep", r"find", r"ps", r"top",
        r"git\s+status", r"git\s+log", r"git\s+diff",
    ]
    
    def check(self, command: str) -> "CommandCheckResult":
        """检查命令是否允许"""


class SafetyChecker:
    """安全检查器"""
    
    def assess(self, command: str, context: "AgentContext") -> "SafetyAssessment":
        """
        评估命令风险
        
        风险等级:
        - LOW: 安全操作 (ls, cat等)
        - MEDIUM: 需要注意 (安装包、修改配置)
        - HIGH: 高风险 (删除文件、网络操作)
        - CRITICAL: 极高风险 (系统级操作)
        """
```

---

### 3.4 记忆系统 (Memory System)

**位置**: `app/services/agent/memory/`

```python
class MemoryManager:
    """
    记忆管理器 - 管理Agent的记忆系统
    
    记忆类型:
    1. ShortTermMemory: 短期记忆 (最近N条交互，会话级)
    2. LongTermMemory: 长期记忆 (向量存储，持久化)
    3. ItemContext: Item特定上下文 (工作目录、环境变量等)
    """
    
    def __init__(self, item_handler_id: str):
        self.short_term = ShortTermMemory(max_entries=100)
        self.long_term = LongTermMemory(handler_id=item_handler_id)
        self.item_contexts: Dict[str, ItemContext] = {}
    
    def add_interaction(self, item_uuid: str, interaction: "Interaction"):
        """添加交互记录"""
        self.short_term.add(item_uuid, interaction)
        self.long_term.store(interaction)
    
    def get_relevant_context(self, item_uuid: str, query: str) -> str:
        """获取相关上下文，用于LLM prompt"""
        recent = self.short_term.get_recent(item_uuid, limit=10)
        relevant = self.long_term.search(query, top_k=5)
        context = self.item_contexts.get(item_uuid)
        
        return self._build_context(recent, relevant, context)
    
    def update_item_context(self, item_uuid: str, context_update: Dict):
        """更新Item上下文"""


class ShortTermMemory:
    """短期记忆 - 使用环形缓冲区存储最近交互"""
    
    def __init__(self, max_entries: int = 100):
        self._buffer: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_entries))
    
    def add(self, item_uuid: str, interaction: "Interaction"):
        self._buffer[item_uuid].append(interaction)
    
    def get_recent(self, item_uuid: str, limit: int = 10) -> List["Interaction"]:
        return list(self._buffer[item_uuid])[-limit:]


class LongTermMemory:
    """
    长期记忆 - 向量存储
    
    实现:
    - 使用向量数据库 (ChromaDB / Pinecone / Qdrant)
    - 存储重要的交互、学习到的模式、用户偏好
    """
    
    def __init__(self, handler_id: str, vector_store: "VectorStore" = None):
        self.handler_id = handler_id
        self.vector_store = vector_store or ChromaStore(handler_id)
    
    def store(self, interaction: "Interaction"):
        """存储交互到向量数据库"""
        embedding = self._embed(interaction.to_text())
        self.vector_store.add(
            id=interaction.id,
            embedding=embedding,
            metadata=interaction.to_dict()
        )
    
    def search(self, query: str, top_k: int = 5) -> List["MemoryEntry"]:
        """语义搜索相关记忆"""
        query_embedding = self._embed(query)
        return self.vector_store.search(query_embedding, top_k)


class ItemContext:
    """
    Item特定上下文
    
    存储:
    - 工作目录
    - 环境变量
    - 最近执行的命令
    - 当前状态 (是否在vim中、是否在等待输入等)
    """
    
    def __init__(self, item_uuid: str):
        self.item_uuid = item_uuid
        self.working_directory: str = "~"
        self.environment: Dict[str, str] = {}
        self.last_commands: List[str] = []
        self.state: "TerminalState" = TerminalState.NORMAL
        self.custom_data: Dict = {}
```

---

### 3.5 Agent核心引擎

**位置**: `app/services/agent/core/agent_engine.py`

```python
class AgentEngine:
    """
    Agent核心引擎
    
    职责:
    1. 接收过滤后的事件
    2. 构建LLM prompt (包含记忆上下文)
    3. 调用LLM生成响应
    4. 通过输出过滤器执行命令
    """
    
    def __init__(
        self,
        handler_config: "HandlerConfig",
        llm_client: "LLMClient",
        memory_manager: "MemoryManager",
        input_filter: "InputFilter",
        output_filter: "OutputFilter"
    ):
        self.config = handler_config
        self.llm = llm_client
        self.memory = memory_manager
        self.input_filter = input_filter
        self.output_filter = output_filter
        self.action_planner = ActionPlanner()
    
    async def process_event(self, item_uuid: str, event: "FilteredEvent"):
        """处理过滤后的事件"""
        
        # 1. 判断是否需要响应
        if not self._should_respond(event):
            return
        
        # 2. 获取上下文
        context = self.memory.get_relevant_context(item_uuid, event.raw_content)
        
        # 3. 构建prompt
        prompt = self._build_prompt(event, context)
        
        # 4. 调用LLM
        response = await self.llm.generate(prompt)
        
        # 5. 解析响应，提取命令
        commands = self._parse_response(response)
        
        # 6. 过滤并执行命令
        for command in commands:
            result = self.output_filter.filter(command, self._get_context(item_uuid))
            
            if result.is_allowed:
                await self._execute_command(item_uuid, result.command)
            elif result.needs_approval:
                await self._request_approval(item_uuid, command, result.reason)
            
            # 记录交互
            self.memory.add_interaction(item_uuid, Interaction(
                event=event,
                command=command,
                result=result,
                timestamp=datetime.now()
            ))
    
    def _build_prompt(self, event: "FilteredEvent", context: str) -> str:
        """构建LLM prompt"""
        return f"""
You are an intelligent terminal assistant for item {event.item_uuid}.

## Context
{context}

## Current Event
Type: {event.event_type.value}
Content: {event.raw_content}

## Instructions
{self.config.system_prompt}

## Constraints
- Only execute safe commands
- Do not modify system files
- Ask for confirmation before destructive operations

## Response Format
Respond with commands to execute, one per line, prefixed with 'CMD:'
Or respond with 'WAIT' if no action needed.
"""
```

---

### 3.6 ItemHandler实例管理

**位置**: `app/services/agent/handlers/handler_manager.py`

```python
class HandlerManager:
    """
    ItemHandler管理器
    
    职责:
    1. 管理所有Handler实例的生命周期
    2. 将Item绑定到Handler
    3. 分发事件到对应的Handler
    """
    
    def __init__(self):
        self._handlers: Dict[str, "HandlerInstance"] = {}  # handler_id -> instance
        self._item_bindings: Dict[str, str] = {}  # item_uuid -> handler_id
    
    def create_handler(self, config: "HandlerConfig") -> "HandlerInstance":
        """创建新的Handler实例"""
        handler = HandlerInstance(config)
        self._handlers[config.id] = handler
        return handler
    
    def bind_item(self, item_uuid: str, handler_id: str):
        """将Item绑定到Handler"""
        self._item_bindings[item_uuid] = handler_id
    
    def get_handler_for_item(self, item_uuid: str) -> Optional["HandlerInstance"]:
        """获取Item对应的Handler"""
        handler_id = self._item_bindings.get(item_uuid)
        return self._handlers.get(handler_id) if handler_id else None
    
    def dispatch_event(self, item_uuid: str, event: "FilteredEvent"):
        """分发事件到对应的Handler"""
        handler = self.get_handler_for_item(item_uuid)
        if handler:
            asyncio.create_task(handler.process_event(item_uuid, event))


class HandlerInstance:
    """
    Handler实例 - 封装完整的Agent能力
    
    每个Handler实例包含:
    - 独立的配置
    - 独立的记忆系统
    - 独立的过滤器配置
    - 独立的LLM客户端
    """
    
    def __init__(self, config: "HandlerConfig"):
        self.config = config
        self.memory = MemoryManager(config.id)
        self.input_filter = InputFilter(config.input_filter_config)
        self.output_filter = OutputFilter(config.output_filter_config)
        self.llm_client = LLMClientFactory.create(config.llm_config)
        self.engine = AgentEngine(
            config, self.llm_client, self.memory,
            self.input_filter, self.output_filter
        )
```

---

## 四、数据模型扩展

### 4.1 扩展 ItemHandler 模型

**位置**: `app/models.py`

```python
class InputFilterConfig(SQLModel, table=False):
    """输入过滤器配置"""
    enabled: bool = True
    patterns: Dict[str, List[str]] = {}  # 自定义模式
    noise_patterns: List[str] = []  # 噪音模式
    event_types_to_ignore: List[str] = []  # 忽略的事件类型


class OutputFilterConfig(SQLModel, table=False):
    """输出过滤器配置"""
    enabled: bool = True
    mode: str = "whitelist"  # "whitelist" | "blacklist" | "hybrid"
    command_whitelist: List[str] = []
    command_blacklist: List[str] = []
    sensitive_patterns: List[str] = []  # 敏感词模式
    rate_limit_per_minute: int = 10
    require_approval_for_high_risk: bool = True


class LLMConfig(SQLModel, table=False):
    """LLM配置"""
    provider: str = "openai"  # "openai" | "anthropic" | "local"
    model: str = "gpt-4"
    api_key: Optional[str] = None
    api_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 1000


class MemoryConfig(SQLModel, table=False):
    """记忆系统配置"""
    short_term_size: int = 100
    enable_long_term: bool = True
    vector_store: str = "chroma"  # "chroma" | "pinecone" | "qdrant"


class ItemHandlerBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    
    # LLM配置
    llm_config: Optional[LLMConfig] = Field(default=None, sa_type=JSON)
    
    # 过滤器配置
    input_filter_config: Optional[InputFilterConfig] = Field(default=None, sa_type=JSON)
    output_filter_config: Optional[OutputFilterConfig] = Field(default=None, sa_type=JSON)
    
    # 记忆配置
    memory_config: Optional[MemoryConfig] = Field(default=None, sa_type=JSON)
    
    # 系统Prompt
    system_prompt: Optional[str] = Field(default=None, max_length=5000)
    
    # 启用状态
    is_active: bool = True
    
    # 自动执行模式 (无需人工确认)
    auto_execute: bool = False


class ItemHandler(ItemHandlerBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=get_datetime_utc)
    updated_at: datetime = Field(default_factory=get_datetime_utc, sa_column_kwargs={"onupdate": get_datetime_utc})
    owner_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    
    # 关联
    items: List[Item] = Relationship(back_populates="handlers", link_model=ItemHandlerItem)
    users: List[User] = Relationship(back_populates="handlers", link_model=ItemHandlerUser)
    owner: Optional[User] = Relationship(back_populates="owned_handlers")
```

---

## 五、API路由设计

### 5.1 Agent控制API

**位置**: `app/api/routes/agent_routes.py`

```python
router = APIRouter(prefix="/agent", tags=["agent"])

@router.post("/handlers/{handler_id}/activate")
async def activate_handler(handler_id: uuid.UUID):
    """激活Handler，开始监听绑定Items的输出"""

@router.post("/handlers/{handler_id}/deactivate")
async def deactivate_handler(handler_id: uuid.UUID):
    """停用Handler"""

@router.post("/items/{item_id}/bind-handler/{handler_id}")
async def bind_item_to_handler(item_id: uuid.UUID, handler_id: uuid.UUID):
    """将Item绑定到Handler"""

@router.post("/items/{item_id}/unbind-handler")
async def unbind_item_from_handler(item_id: uuid.UUID):
    """解除Item与Handler的绑定"""

@router.post("/execute")
async def execute_manual_command(
    item_id: uuid.UUID,
    command: str,
    require_approval: bool = False
):
    """人工命令接口 - 让Agent执行指定命令"""

@router.get("/handlers/{handler_id}/memory")
async def get_handler_memory(handler_id: uuid.UUID, limit: int = 50):
    """获取Handler的记忆"""

@router.delete("/handlers/{handler_id}/memory")
async def clear_handler_memory(handler_id: uuid.UUID):
    """清空Handler记忆"""

@router.get("/handlers/{handler_id}/interactions")
async def get_handler_interactions(
    handler_id: uuid.UUID,
    item_id: Optional[uuid.UUID] = None,
    skip: int = 0,
    limit: int = 100
):
    """获取Handler的交互历史"""

@router.post("/approve/{approval_id}")
async def approve_command(approval_id: str):
    """审批待执行的命令"""

@router.post("/reject/{approval_id}")
async def reject_command(approval_id: str):
    """拒绝待执行的命令"""
```

---

## 六、集成流程

### 6.1 TerminalService集成

**修改**: `app/services/terminal_service.py`

```python
from app.services.agent import AgentStreamSDK, HandlerManager

class TerminalService:
    def __init__(self, ...):
        # 现有初始化
        self.connection_manager = connection_manager
        self.socket_manager = socket_manager
        
        # 新增: Agent层初始化
        self.agent_sdk = AgentStreamSDK()
        self.handler_manager = HandlerManager()
    
    def _create_backend_room_subscriber(self, item_uuid, token, daemon_url, api_key, owner_uuid):
        # 现有逻辑...
        socket = self.socket_manager.create_backend_socket(...)
        
        def log_callback(data):
            # 现有: 写日志
            log_manager.write_to_log(...)
            
            # 新增: 分发到Agent SDK
            self.agent_sdk.dispatch(item_uuid, data)
        
        socket.on(ProtocolEvents.STREAM, log_callback)
```

### 6.2 启动流程

```
1. Backend启动
   ↓
2. 初始化TerminalService
   - 初始化AgentStreamSDK
   - 初始化HandlerManager
   ↓
3. 用户创建ItemHandler (通过API)
   - 保存配置到数据库
   - HandlerManager.create_handler()
   ↓
4. 用户绑定Item到Handler
   - HandlerManager.bind_item()
   ↓
5. 用户启动Item终端
   - TerminalService.start_terminal()
   - 创建Backend Socket订阅者
   - 注册Agent SDK回调
   ↓
6. 终端输出流
   - ItemSocket.on_stream()
   - AgentStreamSDK.dispatch()
   - InputFilter.filter()
   - AgentEngine.process_event()
   - OutputFilter.filter()
   - 执行命令 / 请求审批
```

---

## 七、安全设计

### 7.1 多层安全防护

```
┌─────────────────────────────────────────────────────────────────┐
│                     Agent命令执行流程                            │
│                                                                 │
│  Agent生成命令                                                  │
│       │                                                         │
│       ↓                                                         │
│  ┌─────────────────┐                                           │
│  │ Layer 1: 黑名单 │ → 阻止已知危险命令                         │
│  └────────┬────────┘                                           │
│           ↓ 通过                                                │
│  ┌─────────────────┐                                           │
│  │ Layer 2: 白名单 │ → 快速放行已知安全命令                     │
│  └────────┬────────┘                                           │
│           ↓ 未匹配                                              │
│  ┌─────────────────┐                                           │
│  │ Layer 3: 敏感词 │ → 检测敏感数据 (密码、密钥等)              │
│  └────────┬────────┘                                           │
│           ↓ 通过                                                │
│  ┌─────────────────┐                                           │
│  │ Layer 4: 风险评估│ → 评估命令风险等级                        │
│  └────────┬────────┘                                           │
│           │                                                     │
│     ┌─────┴─────┐                                              │
│     ↓           ↓                                              │
│  LOW/MEDIUM   HIGH/CRITICAL                                    │
│     │           │                                              │
│     ↓           ↓                                              │
│  直接执行    需要审批                                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 审批机制

```python
class ApprovalRequest:
    """审批请求"""
    id: str
    item_uuid: str
    handler_id: str
    command: str
    risk_level: RiskLevel
    reason: str
    created_at: datetime
    expires_at: datetime  # 超时自动拒绝
    status: str  # "pending" | "approved" | "rejected" | "expired"


class ApprovalManager:
    """审批管理器"""
    
    def create_approval(self, command: str, context: "AgentContext") -> "ApprovalRequest":
        """创建审批请求"""
        
    def approve(self, approval_id: str, approver: str) -> bool:
        """审批通过"""
        
    def reject(self, approval_id: str, reason: str) -> bool:
        """审批拒绝"""
        
    def get_pending_approvals(self, user_id: str) -> List["ApprovalRequest"]:
        """获取待审批列表"""
```

---

## 八、配置示例

### 8.1 Handler配置示例

```json
{
  "name": "DevOps Assistant",
  "description": "用于DevOps任务的智能助手",
  
  "llm_config": {
    "provider": "openai",
    "model": "gpt-4",
    "temperature": 0.7
  },
  
  "input_filter_config": {
    "enabled": true,
    "patterns": {
      "error": ["error:", "failed:", "exception:"],
      "warning": ["warning:", "warn:"],
      "deploy_success": ["deployed successfully", "build succeeded"]
    },
    "noise_patterns": [
      "^\\s*$",
      "^\\d+%$",
      "^\\[=*\\s*\\]$"
    ]
  },
  
  "output_filter_config": {
    "enabled": true,
    "mode": "hybrid",
    "command_whitelist": [
      "ls", "cat", "grep", "find", "git status", "git log", "docker ps"
    ],
    "command_blacklist": [
      "rm -rf /", "mkfs", "dd if="
    ],
    "sensitive_patterns": [
      "password",
      "api_key",
      "secret",
      "token"
    ],
    "rate_limit_per_minute": 10,
    "require_approval_for_high_risk": true
  },
  
  "memory_config": {
    "short_term_size": 100,
    "enable_long_term": true,
    "vector_store": "chroma"
  },
  
  "system_prompt": "You are a DevOps assistant. Help manage deployments, monitor logs, and assist with common DevOps tasks. Always verify before executing destructive operations.",
  
  "auto_execute": false
}
```

---

## 九、扩展能力

### 9.1 插件系统 (未来)

```python
class AgentPlugin:
    """Agent插件基类"""
    
    def on_event(self, event: "FilteredEvent") -> Optional["PluginAction"]:
        """处理事件"""
        
    def on_command(self, command: str) -> Optional[str]:
        """修改命令"""
        
    def get_capabilities(self) -> List[str]:
        """返回插件能力"""


class PluginManager:
    """插件管理器"""
    
    def register_plugin(self, handler_id: str, plugin: "AgentPlugin"):
        """注册插件"""
        
    def dispatch_event(self, handler_id: str, event: "FilteredEvent"):
        """分发事件到插件"""
```

### 9.2 多Agent协作 (未来)

```python
class AgentOrchestrator:
    """多Agent编排器"""
    
    def coordinate(self, item_uuid: str, event: "FilteredEvent"):
        """协调多个Agent处理同一事件"""
```

---

## 十、总结

### 核心设计原则

1. **分层解耦**: SDK层 → 过滤层 → Agent核心 → 执行层，每层职责清晰
2. **安全优先**: 多层过滤 + 审批机制，确保不会执行危险命令
3. **记忆独立**: 每个Handler有独立的记忆系统，支持多Item上下文
4. **可配置性**: 所有过滤规则、敏感词、Prompt均可配置
5. **可扩展性**: 预留插件系统和多Agent协作能力

### 关键注入点

- **输出流监听**: `ItemSocket.on_stream()` → `AgentStreamSDK.dispatch()`
- **命令执行**: `AgentEngine` → `OutputFilter` → `TerminalService.write_to_terminal()`

### 下一步实施建议

1. 先实现 `AgentStreamSDK` 和基础的事件分发
2. 实现简单的 `InputFilter` 和 `OutputFilter`
3. 集成LLM客户端，实现基础Agent能力
4. 实现记忆系统
5. 添加审批机制和安全增强
6. 扩展插件系统
