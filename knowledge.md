# TermMan RAG / Knowledge 技术文档

## 1. 文档目的

这份文档描述当前 TermMan 项目里知识库 / RAG 的真实实现，重点回答：

- 知识文件实际存在哪里
- `knowledge` 目录当前哪些结构还在生效，哪些是遗留
- 对外有哪些 HTTP 接口，请求和响应是什么
- `KnowledgeBaseService` 当前提供了哪些内部接口
- `ItemHandler` 如何绑定知识文件
- 用户提问时系统如何检索知识
- 为什么“语义问题”可以走当前 RAG，而“精确引用问题”不适合直接走当前 RAG

当前实现不是“直接读原文逐句回答”，而是标准的共享知识库 RAG：

> 文件入库 -> 增量索引 -> 切块 -> 向量化 -> 相似度检索 -> 把相关片段注入 Prompt -> 模型生成回答

## 2. 当前架构总览

### 2.1 核心结论

- 知识文件统一进入一个**共享知识库**
- 每个 `ItemHandler` 不保存文件本体，只保存自己启用了哪些知识文件
- 回答问题时不会扫描全部知识文件，只会扫描当前 `ItemHandler.enabled_knowledge_files`
- 知识文件管理和知识文件启用是两套接口
- 当前知识库是“按 chunk 检索 + 让模型生成答案”，不是“按句号/段号精确回原文”

也就是说：

- `Knowledge` 页面负责“管理共享知识文件”
- `ItemHandler` 页面负责“决定当前 handler 启用哪些共享知识文件”

### 2.2 当前运行时目录结论

代码里的配置是：

```python
CHROMA_PERSIST_DIR = "./chroma_data"
KNOWLEDGE_BASE_DIR = "./knowledge"
```

这里的相对路径是**相对于 backend 进程当前工作目录**解析的。

当前仓库和启动方式里：

- `development.md` 里是 `cd backend`
- `compose.yml` 里 backend 的 `working_dir` 是 `/app/backend`
- `backend/scripts/run_backend.sh` 也是在 backend 目录下启动 `fastapi run`

所以当前实际生效的知识目录是：

```text
backend/knowledge/
```

不是仓库根目录下当前这个空的：

```text
knowledge/
```

### 2.3 当前鉴权边界

- `/api/v1/knowledge/*` 这组共享知识库接口只要求已登录用户
- `/api/v1/item-handlers/{id}/knowledge/files` 和 `PUT /api/v1/item-handlers/{id}` 受 `ItemHandler` 所有权控制
- 非 superuser 只能操作自己的 `ItemHandler` 绑定关系

## 3. 关键模块

### 3.1 共享知识文件路由

- `backend/app/api/routes/knowledge.py`

职责：

- 列出共享知识文件
- 上传知识文件
- 下载知识文件
- 删除知识文件
- 删除后清理所有 `ItemHandler` 的绑定引用

### 3.2 ItemHandler 绑定路由

- `backend/app/api/routes/item_handlers.py`

职责：

- 返回“共享知识文件 + 当前 handler 是否启用”
- 通过 `PUT /item-handlers/{id}` 更新 `enabled_knowledge_files`

### 3.3 知识库核心服务

- `backend/app/services/agent/knowledge/service.py`

职责：

- 路径标准化
- 文件类型校验
- 文件保存
- 增量索引
- 文本切块
- 向量化
- Chroma 检索
- 文件删除

### 3.4 Prompt 注入

- `backend/app/services/agent/prompts/builder.py`

职责：

- 根据当前用户问题调用 `knowledge_base_service.search()`
- 把召回结果格式化为 `Relevant knowledge files:` 系统消息
- 注入最终 Prompt

### 3.5 Agent 上下文

- `backend/app/services/agent/agent.py`

职责：

- 把 `ItemHandler.enabled_knowledge_files` 放进 agent 上下文
- 在 handler 更新或知识文件删除后刷新缓存

## 4. 当前生效的 knowledge 存储结构

### 4.1 当前生效结构

当前实现真正使用的是 `KNOWLEDGE_BASE_DIR` 下面这两个位置：

```text
backend/knowledge/
  files/
  index.json
```

在你当前仓库里，实际能看到的是：

```text
backend/knowledge/
  files/
    2049.txt
  index.json
  7a23b03e-5343-4290-9d3f-2de06d075f2a/
  b2b5d783-7166-4cfe-92fb-664ad0f55b3f/
  d4eb4de9-72e2-4cc6-bd5e-075dd512735c/
  ecd4e870-5baf-4150-827f-4fec01887fe6/
```

### 4.2 原始文件目录

原始知识文件当前保存于：

```text
backend/knowledge/files/
```

例如：

```text
backend/knowledge/files/
  2049.txt
```

说明：

- 共享知识文件本体只放在这里
- 当前 HTTP 上传接口保存时只保留文件名，不保留客户端传来的目录层级
- 所以**通过当前上传接口实际是扁平文件结构**

### 4.3 索引文件

索引文件当前保存于：

```text
backend/knowledge/index.json
```

当前 `index.json` 的结构是：

```json
{
  "version": 1,
  "files": {
    "2049.txt": {
      "file_name": "2049.txt",
      "size": 16365,
      "mtime_ns": 1775546634000000000,
      "updated_at": 1775546634,
      "content_hash": "edb09b9c722c6871560ab04a443d9248a0b42014204931178a32e8a90c9e74a9",
      "chunk_ids": [
        "knowledge:be02c1b7714204a0:edb09b9c722c6871:0"
      ]
    }
  }
}
```

每个文件记录：

- `file_name`: 文件名
- `size`: 文件大小
- `mtime_ns`: 纳秒级修改时间
- `updated_at`: 秒级修改时间
- `content_hash`: 原始文件字节的 SHA-256
- `chunk_ids`: 该文件当前对应的全部向量 chunk id

### 4.4 向量库

向量不写入 `index.json`，而是持久化到：

```text
CHROMA_PERSIST_DIR = ./chroma_data
```

当前 collection 名称固定为：

```text
shared_knowledge
```

### 4.5 当前存在的 UUID 子目录如何理解

当前 `backend/knowledge/` 下那几个 UUID 目录，代码里没有任何引用。

换句话说：

- **当前生效结构**：`backend/knowledge/files/` + `backend/knowledge/index.json`
- **当前未被引用的结构**：这些 UUID 子目录

可以把这些 UUID 目录理解为历史遗留数据或旧结构残留，而不是当前共享知识库的正式目录布局。

## 5. 支持的文件类型与路径规则

### 5.1 当前支持的扩展名

当前只支持：

- `.md`
- `.markdown`
- `.txt`

### 5.2 路径标准化规则

`KnowledgeBaseService.normalize_relative_path()` 的规则是：

- 把 `\` 统一转成 `/`
- 去掉前导 `/`
- 不允许空路径
- 不允许绝对路径
- 不允许 `.`、`..`
- 不允许非支持扩展名

例如：

- `guide.md` -> 合法
- `docs/guide.md` -> 内部接口层面合法
- `../guide.md` -> 非法
- `bad.exe` -> 非法

### 5.3 上传接口的额外行为

虽然内部路径标准化支持相对目录，但当前上传接口实际调用的是：

```python
Path(filename).name
```

这意味着：

- 上传 `guide.md`，最终保存 `guide.md`
- 上传 `docs/guide.md`，最终也只会保存成 `guide.md`

所以当前**对外上传接口不支持子目录上传**。

### 5.4 启用列表标准化规则

`KnowledgeBaseService.normalize_enabled_files()` 会：

- 对每个路径做标准化
- 自动去重
- 自动忽略非法路径

所以当前 `PUT /api/v1/item-handlers/{id}` 更新 `enabled_knowledge_files` 时：

- 重复项不会保留
- 非法项不会报错返回 400
- 非法项会被静默丢弃

## 6. 数据模型

### 6.1 对外返回的知识文件模型

共享知识相关接口统一返回这个结构：

```json
{
  "path": "guide.md",
  "name": "guide.md",
  "size": 1234,
  "modified_at": 1710000000,
  "enabled": false,
  "indexed": true,
  "missing": false,
  "chunk_count": 3
}
```

字段含义：

- `path`: 相对知识文件路径
- `name`: 展示用文件名
- `size`: 文件大小，缺失文件时可能为 `null`
- `modified_at`: 文件修改时间戳，缺失文件时可能为 `null`
- `enabled`: 当前是否被某个 `ItemHandler` 启用
- `indexed`: 当前是否已经有 chunk 被索引进 Chroma
- `missing`: 当前 `ItemHandler` 启用过该文件，但文件本体已不存在
- `chunk_count`: 当前索引里记录的 chunk 数量

### 6.2 列表响应模型

`GET /api/v1/knowledge/files` 和 `GET /api/v1/item-handlers/{id}/knowledge/files` 返回：

```json
{
  "data": [],
  "count": 0,
  "enabled_count": 0
}
```

字段含义：

- `data`: 文件列表
- `count`: 返回条数
- `enabled_count`: 当前列表里 `enabled=true` 的条数

### 6.3 上传响应模型

`POST /api/v1/knowledge/files/upload` 返回：

```json
{
  "uploaded": [],
  "count": 0
}
```

说明：

- 上传接口返回字段叫 `uploaded`
- 列表接口返回字段叫 `data`
- 这两者不是同一种响应模型

### 6.4 ItemHandler 绑定字段

`ItemHandler` 模型里知识库相关字段是：

```python
enabled_knowledge_files: list[str] | None
```

它表示：

- 当前这个 `ItemHandler`
- 启用了哪些共享知识文件

例如：

```json
["guide.md", "notes.txt"]
```

### 6.5 内部检索结果模型

`KnowledgeBaseService.search()` 返回的内部结构是：

```json
{
  "id": "knowledge:xxxx",
  "content": "chunk 文本",
  "metadata": {
    "file_path": "guide.md",
    "file_name": "guide.md",
    "chunk_index": 0,
    "content_hash": "sha256...",
    "source_type": "knowledge_file"
  },
  "distance": 0.123
}
```

这个结构不会直接返回给前端，而是继续被 Prompt Builder 组装。

## 7. 对外 HTTP 接口

### 7.1 接口总表

| 场景 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 列出共享知识文件 | `GET` | `/api/v1/knowledge/files` | 返回共享知识文件列表 |
| 上传共享知识文件 | `POST` | `/api/v1/knowledge/files/upload` | 支持多文件上传 |
| 下载共享知识文件 | `GET` | `/api/v1/knowledge/files/download/{file_path}` | 返回文件流 |
| 删除共享知识文件 | `DELETE` | `/api/v1/knowledge/files/{file_path}` | 删除文件、索引和 handler 绑定 |
| 查看 handler 的知识启用状态 | `GET` | `/api/v1/item-handlers/{id}/knowledge/files` | 返回所有文件及当前 handler 的启用状态 |
| 更新 handler 启用列表 | `PUT` | `/api/v1/item-handlers/{id}` | 通过 `enabled_knowledge_files` 修改绑定关系 |

### 7.2 `GET /api/v1/knowledge/files`

用途：

- 列出共享知识库里的全部现存文件

鉴权：

- 任意已登录用户

后端行为：

- 先执行 `knowledge_base_service.list_files()`
- `list_files()` 内部会先执行一次 `sync_library()`
- 所以这个接口带有“读取时顺手补齐索引状态”的效果

响应示例：

```json
{
  "data": [
    {
      "path": "2049.txt",
      "name": "2049.txt",
      "size": 16365,
      "modified_at": 1775546634,
      "enabled": false,
      "indexed": true,
      "missing": false,
      "chunk_count": 6
    }
  ],
  "count": 1,
  "enabled_count": 0
}
```

说明：

- 这里的 `enabled` 固定来自空的 `enabled_files` 集合
- 所以共享知识列表接口里，`enabled` 基本都会是 `false`
- `enabled_count` 也固定是 `0`

### 7.3 `POST /api/v1/knowledge/files/upload`

用途：

- 上传一个或多个共享知识文件

鉴权：

- 任意已登录用户

请求格式：

```http
POST /api/v1/knowledge/files/upload
Content-Type: multipart/form-data
```

表单字段：

- `files`: 可重复字段，每个值是一个上传文件

请求示例：

```text
files = ("guide.md", b"# Guide\nhello", "text/markdown")
files = ("notes.txt", b"plain text", "text/plain")
```

后端处理流程：

1. 校验 `upload.filename` 非空
2. `await upload.read()` 读取字节
3. 调用 `save_file_bytes(upload.filename, content)`
4. 内部把文件名压缩成 basename 后写入 `backend/knowledge/files/`
5. 所有文件保存完后统一调用 `sync_library()`
6. 再次 `list_files()` 组装上传结果

响应示例：

```json
{
  "uploaded": [
    {
      "path": "guide.md",
      "name": "guide.md",
      "size": 13,
      "modified_at": 1775546634,
      "enabled": false,
      "indexed": true,
      "missing": false,
      "chunk_count": 1
    },
    {
      "path": "notes.txt",
      "name": "notes.txt",
      "size": 10,
      "modified_at": 1775546634,
      "enabled": false,
      "indexed": true,
      "missing": false,
      "chunk_count": 1
    }
  ],
  "count": 2
}
```

错误行为：

- 文件名为空 -> `400 File name is required`
- 扩展名不支持 / 路径非法 -> `400`，错误来自 `ValueError`

### 7.4 `GET /api/v1/knowledge/files/download/{file_path:path}`

用途：

- 下载共享知识文件原文

鉴权：

- 任意已登录用户

路径参数：

- `file_path`: 相对知识路径，例如 `guide.md`

响应：

- 不是 JSON
- 返回 `application/octet-stream` 文件流
- `Content-Disposition` 里会带文件名

前端当前做法：

- 对路径按 segment 分别 `encodeURIComponent`
- 例如 `docs/guide.md` 会编码为 `docs/guide.md` 的分段 URL path

错误行为：

- 路径非法 -> `400`
- 文件不存在 -> `404 Knowledge file not found`

### 7.5 `DELETE /api/v1/knowledge/files/{file_path:path}`

用途：

- 删除共享知识文件

鉴权：

- 任意已登录用户

后端副作用：

1. 从 `index.json` 删除对应 entry
2. 删除对应 chunk ids 在 Chroma 里的向量
3. 删除 `backend/knowledge/files/` 下原始文件
4. 尝试清空已经变空的父目录
5. 扫描全部 `ItemHandler`
6. 把被删文件从所有 `enabled_knowledge_files` 里移除
7. 刷新相关 handler 的 agent 缓存

成功响应：

```json
{
  "message": "Knowledge file deleted successfully"
}
```

错误行为：

- 路径非法 -> `400`
- 文件不存在 -> `404 Knowledge file not found`

### 7.6 `GET /api/v1/item-handlers/{id}/knowledge/files`

用途：

- 获取“共享知识文件列表 + 当前 handler 的启用状态”

鉴权：

- superuser，或该 `ItemHandler` 的 owner

后端行为：

- 先查 `ItemHandler`
- 取出 `item_handler.enabled_knowledge_files`
- 调用 `knowledge_base_service.list_files(enabled_files)`
- 返回全部现存文件，并把当前 handler 已启用的文件标成 `enabled=true`

响应示例：

```json
{
  "data": [
    {
      "path": "guide.md",
      "name": "guide.md",
      "size": 13,
      "modified_at": 1775546634,
      "enabled": true,
      "indexed": true,
      "missing": false,
      "chunk_count": 1
    },
    {
      "path": "notes.txt",
      "name": "notes.txt",
      "size": 10,
      "modified_at": 1775546634,
      "enabled": false,
      "indexed": true,
      "missing": false,
      "chunk_count": 1
    }
  ],
  "count": 2,
  "enabled_count": 1
}
```

关于 `missing`：

- 如果某个 handler 还引用了一个不存在的知识文件，这个接口会把它补出来
- 此时该条目会是 `enabled=true` 且 `missing=true`
- 正常删除流程会自动清理这种脏引用，所以这个状态一般只会在历史数据不一致时出现

### 7.7 `PUT /api/v1/item-handlers/{id}`

用途：

- 更新 `ItemHandler`
- 知识库相关场景主要用于更新 `enabled_knowledge_files`

鉴权：

- superuser，或该 `ItemHandler` 的 owner

请求示例：

```json
{
  "enabled_knowledge_files": [
    "guide.md",
    "guide.md",
    "notes.txt",
    "bad.exe",
    "../escape.md"
  ]
}
```

知识库相关实际行为：

- `guide.md` 重复项会去重
- `bad.exe` 因扩展名非法被丢弃
- `../escape.md` 因路径非法被丢弃
- 最终写回数据库的是：

```json
{
  "enabled_knowledge_files": ["guide.md", "notes.txt"]
}
```

成功响应会返回完整 `ItemHandlerPublic`，其中包含更新后的：

```json
{
  "enabled_knowledge_files": ["guide.md", "notes.txt"]
}
```

补充说明：

- 这是一个通用更新接口，不是专门的知识绑定接口
- 只要请求体里带了 `enabled_knowledge_files`，后端就会先做标准化
- 更新成功后会刷新 agent 缓存

## 8. 内部服务接口

### 8.1 `KnowledgeBaseService` 对外可用方法

#### `normalize_relative_path(raw_path: str) -> str`

用途：

- 把原始路径转成安全、规范的相对知识文件路径

失败时：

- 抛 `ValueError`

#### `normalize_enabled_files(file_paths: list[str] | None) -> list[str]`

用途：

- 对启用列表做标准化、去重、过滤非法值

特点：

- 不抛出单个非法路径导致的整体失败
- 非法项直接忽略

#### `save_file_bytes(filename: str, content: bytes) -> dict[str, Any]`

用途：

- 保存上传文件到知识目录

返回字段：

```json
{
  "path": "guide.md",
  "name": "guide.md",
  "size": 13,
  "modified_at": 1775546634
}
```

说明：

- 实际保存时会用 `Path(filename).name`
- 所以只保留 basename

#### `list_files(enabled_files: list[str] | None = None) -> list[dict[str, Any]]`

用途：

- 返回知识文件列表

行为：

- 进入时会先跑一次 `sync_library()`
- 同时合并磁盘状态和 `index.json` 状态
- 如果传入 `enabled_files`，会按这个集合标注 `enabled`
- 如果 `enabled_files` 里有不存在文件，会返回 `missing=true` 的占位条目

#### `sync_library() -> dict[str, Any]`

用途：

- 对共享知识库做增量同步

返回示例：

```json
{
  "added": ["guide.md"],
  "updated": ["notes.txt"],
  "removed": ["old.md"],
  "skipped": ["stable.txt"]
}
```

它负责：

- 扫描 `files/`
- 读取 `index.json`
- 删除已丢失文件的旧索引
- 跳过未变化文件
- 对新文件或变更文件重建 chunk 和向量
- 回写 `index.json`

#### `search(query: str, enabled_files: list[str] | None, n_results: int = 4) -> list[dict[str, Any]]`

用途：

- 在当前 handler 启用的知识文件里做语义检索

特点：

- 若 `query` 为空，直接返回空列表
- 若 `enabled_files` 为空，直接返回空列表
- 先把问题编码成一个 query embedding
- 再对每个已启用文件分别调用一次 Chroma `query`
- 每个文件查询时都使用 `n_results`
- 最后按 chunk id 去重、按 `distance` 全局排序，再截成前 `n_results`

#### `delete_file(file_path: str) -> bool`

用途：

- 删除原始文件和索引

返回值：

- `True`: 文件本体存在且已删除
- `False`: 索引已清理，但原始文件本体不存在

### 8.2 关键内部辅助方法

#### `_decode_content(raw_bytes: bytes) -> str`

当前解码顺序：

1. `utf-8`
2. `utf-8-sig`
3. `gb18030`
4. `latin-1`
5. 最后兜底 `utf-8(errors="ignore")`

#### `_chunk_text(text: str) -> list[str]`

当前参数：

- `DEFAULT_CHUNK_SIZE = 1200`
- `DEFAULT_CHUNK_OVERLAP = 180`

行为：

- 空文本返回空列表
- 短文本直接作为一个 chunk
- 长文本优先尝试在空行、换行、空格处分割
- 相邻 chunk 保留重叠区

#### `_build_chunk_id(file_path: str, content_hash: str, index: int) -> str`

当前 chunk id 形如：

```text
knowledge:<file_path_sha1_前16位>:<content_hash_前16位>:<chunk_index>
```

### 8.3 Prompt Builder 接口

`backend/app/services/agent/prompts/builder.py` 里知识库相关的关键入口是：

```python
_collect_handler_knowledge(agent, query, n_results=4) -> str
```

它会：

1. 读取 `agent.enabled_knowledge_files`
2. 调用 `knowledge_base_service.search(query, enabled_files, n_results=4)`
3. 把结果格式化成：

```text
Relevant knowledge files:
- [guide.md] 片段内容
- [notes.txt] 片段内容
```

4. 作为系统消息注入 Prompt

### 8.4 AgentContext 接口

`agent.py` 里上下文相关的知识字段是：

```python
enabled_knowledge_files: list[str]
```

它来自：

- `ItemHandler.enabled_knowledge_files`

它会在这两类场景刷新：

- `PUT /api/v1/item-handlers/{id}` 更新 handler 后
- `DELETE /api/v1/knowledge/files/{file_path}` 清理绑定后

## 9. 入库流程

### 9.1 上传入口

前端在 `Knowledge` 页面上传文件，调用：

```text
POST /api/v1/knowledge/files/upload
```

### 9.2 后端处理流程

上传后会经过这些步骤：

1. 读取 multipart 文件
2. 校验文件名
3. 标准化并验证扩展名
4. 写入 `backend/knowledge/files/`
5. 统一执行一次 `sync_library()`
6. 重新列出文件并返回上传结果

### 9.3 增量索引逻辑

`sync_library()` 的核心逻辑是：

1. 扫描知识文件目录
2. 读取 `index.json`
3. 找出已从磁盘消失的旧文件，删除其索引
4. 对现有文件按 `mtime_ns + size` 做第一层跳过判断
5. 若第一层未命中，再按 `content_hash` 做第二层判断
6. 内容变更时删除旧 chunk，重建新 chunk 和新向量
7. 回写 `index.json`

### 9.4 如何判断文件是否变化

当前用两层判断：

1. `mtime_ns + size`
2. `content_hash`

规则如下：

- 修改时间和大小都没变，并且已有 `chunk_ids` -> 直接 `skipped`
- 时间或大小变了，但 `content_hash` 没变 -> 只更新元信息，不重做 embedding
- `content_hash` 变了 -> 删除旧向量并重建

## 10. 向量化与检索逻辑

### 10.1 切块逻辑

切块发生在：

- `KnowledgeBaseService._chunk_text()`

当前参数：

- `DEFAULT_CHUNK_SIZE = 1200`
- `DEFAULT_CHUNK_OVERLAP = 180`

规则：

- 文本短于阈值时不切块
- 文本较长时按长度推进
- 优先尝试在空行、换行、空格处断开
- 保留 overlap，减少语义断裂

### 10.2 向量化逻辑

切块后，每个 chunk 会经过 `EmbeddingService` 生成向量。

写入 Chroma 时，每个 chunk 当前附带这些 metadata：

- `file_path`
- `file_name`
- `chunk_index`
- `content_hash`
- `source_type = knowledge_file`

### 10.3 检索逻辑

用户发问后，系统不会直接逐句扫描原文，而是：

1. 读取当前 `agent.enabled_knowledge_files`
2. 把 query 编码成 embedding
3. 对每个已启用文件分别查询一次 Chroma
4. 收集全部结果，按 chunk id 去重
5. 按 `distance` 排序
6. 最后截成前 `4` 条

默认召回条数：

- `n_results = 4`

### 10.4 Prompt 注入格式

召回内容最终会被组装成：

```text
Relevant knowledge files:
- [文件名] 片段内容
- [文件名] 片段内容
```

然后以系统消息形式注入最终 Prompt。

## 11. 生成流程

完整回答流程可以理解成：

```text
用户提问
  -> 构建 Prompt
  -> 读取当前 ItemHandler 启用的知识文件
  -> 做向量检索
  -> 取回相关 chunk
  -> 把 chunk 注入 Prompt
  -> LLM 生成回答
```

所以当前系统本质上是：

- “检索相关片段后生成答案”
- 不是“严格按原文精确抽取”

## 12. 为什么有时回答不准

这是当前实现最重要的限制。

### 12.1 当前擅长的问题

当前实现更擅长：

- “这篇文档的主题是什么”
- “这份知识如何评价某个概念”
- “这份文档里关于某个问题的大意是什么”

因为这些属于**语义问题**。

### 12.2 当前不擅长的问题

当前实现不擅长：

- “最后一句原文是什么”
- “倒数第二句话是什么”
- “第 17 句是什么”
- “第 3 段第 2 句是什么”

因为这些属于：

- 原文定位问题
- 精确引用问题

而当前索引不是按句子号或段落号建立的，也不是直接按原文位置返回。

### 12.3 为什么会答偏

原因主要有三层：

1. 检索单元是 chunk，不是句子
2. 模型拿到 chunk 后会“理解并生成”，不是机械复述原文
3. Prompt 里还可能同时包含近期对话、摘要、长期记忆等其他上下文

所以当前这套实现应该这样使用：

- 语义问题走当前 RAG
- 精确引用问题走原文定位

## 13. 删除流程

删除共享知识文件时，后端会做三类清理：

1. 删除原始文件
2. 删除向量索引和 `index.json` 记录
3. 自动把该文件从所有 `ItemHandler.enabled_knowledge_files` 中移除

所以当前删除是完整删除，不是“只删文件不删向量”，也不是“只删文件不清 handler 引用”。

## 14. 前端对应关系

### 14.1 Knowledge 页面

共享知识文件管理调用的是：

- `GET /api/v1/knowledge/files`
- `POST /api/v1/knowledge/files/upload`
- `GET /api/v1/knowledge/files/download/{file_path}`
- `DELETE /api/v1/knowledge/files/{file_path}`

### 14.2 ItemHandler 页面

知识绑定调用的是：

- `GET /api/v1/item-handlers/{id}/knowledge/files`
- `PUT /api/v1/item-handlers/{id}`，只更新 `enabled_knowledge_files`

## 15. 当前系统的准确描述

可以把当前知识库系统准确概括成一句话：

> TermMan 当前的知识库是一个“共享知识文件库 + ItemHandler 启用列表”的结构；知识文件统一落盘到 `backend/knowledge/files/`，通过 `sync_library()` 做增量切块和向量化，提问时只在当前 `ItemHandler.enabled_knowledge_files` 范围内做 Chroma 相似度检索，再把召回 chunk 以 `Relevant knowledge files:` 系统消息注入 Prompt，由模型生成最终答案。

## 16. 当前最适合的使用方式

如果你问的是：

- 文档主题
- 某段内容的大意
- 某个概念是否出现在知识里
- 某份知识对某个问题的整体判断

当前 RAG 很适合。

如果你问的是：

- 精确原句
- 第几句
- 倒数第几句
- 逐字引用

当前 RAG 不适合，应该走：

- 直接读原文
- 按句号、段落或换行做原文定位
- 返回原始文本而不是让模型自由生成

## 17. 后续优化建议

如果后续要支持“原文级准确回答”，建议在当前共享知识 RAG 旁边增加一条精确定位旁路。

### 方案 A：位置型精确检索

- 对原文额外做句子级切分
- 建立句号级 / 段落级位置索引
- 遇到“第 N 句 / 倒数第二句”时直接按位置取原文

### 方案 B：原文直读模式

- 当问题命中“最后一句 / 倒数第二句 / 原文”这类关键词
- 直接读取原始 `.md` / `.txt`
- 不走向量检索

### 方案 C：混合检索

- 语义问题走当前 RAG
- 精确引用问题走原文定位

这是最实用的方案。
