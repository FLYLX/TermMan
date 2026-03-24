# Skill 系统开发文档

## 目录结构

```
backend/
├── skills/                          # Skill 存储目录
│   ├── my_skill_1/
│   │   ├── SKILL.md                 # 核心定义文件（必须）
│   │   ├── scripts/                 # 脚本文件
│   │   ├── templates/               # 模板文件
│   │   ├── Resources/               # 资源文件（二进制）
│   │   └── examples/                # 示例文件
│   └── my_skill_2/
│       └── SKILL.md
│
└── app/services/agent/skills/
    ├── __init__.py                  # 导出
    ├── definition.py                # 数据类定义
    ├── loader.py                    # 文件加载器
    └── manager.py                   # CRUD 管理器
```

## SKILL.md 格式

```markdown
---
skill_id: npm_fixer
name: NPM 修复器
description: 自动修复 npm 依赖问题
category: devtools
trigger:
  type: auto
  patterns:
    - "npm ERR!"
    - "ECONNREFUSED"
action:
  type: llm
  prompt: "分析以下 npm 错误并提供修复方案"
safety:
  requires_approval: false
  risk_level: low
  max_retries: 3
  timeout: 60
---

# Skill 说明

这里写详细的 skill 使用说明...

## 触发条件

- npm 网络错误
- 依赖版本冲突

## 执行流程

1. 解析错误信息
2. 查找解决方案
3. 执行修复命令
```

## 数据模型

### SkillDefinition

```python
@dataclass
class SkillDefinition:
    skill_id: str                    # 唯一标识
    name: str                        # 显示名称
    description: str                 # 描述
    category: str                    # 分类
    trigger: TriggerConfig           # 触发配置
    action: ActionConfig             # 动作配置
    safety: SafetyConfig             # 安全配置
    content: str                     # SKILL.md 原始内容
    scripts: dict[str, str]          # 脚本文件
    templates: dict[str, str]        # 模板文件
    resources: dict[str, bytes]      # 资源文件
    examples: list[dict]             # 示例数据
```

### TriggerConfig

```python
@dataclass
class TriggerConfig:
    type: str = "manual"             # manual | auto | event
    patterns: list[str] = []         # 触发模式
    interval: int | None = None      # 定时间隔
```

### ActionConfig

```python
@dataclass
class ActionConfig:
    type: str = "llm"                # llm | command | script
    prompt: str | None = None        # LLM 提示词
    command: str | None = None       # 命令
    script: str | None = None        # 脚本名
    params: dict = {}                # 参数
```

### SafetyConfig

```python
@dataclass
class SafetyConfig:
    requires_approval: bool = False  # 需要审批
    risk_level: str = "low"          # low | medium | high | critical
    max_retries: int = 3             # 最大重试
    timeout: int = 60                # 超时秒数
```

## API 接口

### 列出 Skills

```
GET /api/v1/skills/
```

响应：
```json
{
  "data": [
    {
      "skill_id": "npm_fixer",
      "name": "NPM 修复器",
      "description": "自动修复 npm 依赖问题",
      "category": "devtools"
    }
  ],
  "count": 1
}
```

### 获取 Skill 详情

```
GET /api/v1/skills/{skill_id}
```

响应：
```json
{
  "skill_id": "npm_fixer",
  "name": "NPM 修复器",
  "description": "自动修复 npm 依赖问题",
  "category": "devtools",
  "trigger": {...},
  "action": {...},
  "safety": {...},
  "content": "...",
  "scripts": ["fix.sh"],
  "templates": ["report.md"],
  "resources": ["icon.png"],
  "examples": [...]
}
```

### 创建 Skill

```
POST /api/v1/skills/
```

请求：
```json
{
  "skill_id": "my_skill",
  "name": "我的技能",
  "description": "技能描述",
  "category": "general"
}
```

### 更新 Skill

```
PUT /api/v1/skills/{skill_id}
```

请求：
```json
{
  "name": "新名称",
  "description": "新描述"
}
```

### 删除 Skill

```
DELETE /api/v1/skills/{skill_id}
```

### 文件操作

```
GET    /api/v1/skills/{skill_id}/files           # 列出文件
GET    /api/v1/skills/{skill_id}/files/{path}    # 获取文件
PUT    /api/v1/skills/{skill_id}/files/{path}    # 更新文件
POST   /api/v1/skills/{skill_id}/files/{path}    # 创建文件
DELETE /api/v1/skills/{skill_id}/files/{path}    # 删除文件
```

### 上传 Zip

```
POST /api/v1/skills/upload-zip
Content-Type: multipart/form-data

file: skill.zip
```

Zip 结构：
```
skill.zip
└── my_skill/
    ├── SKILL.md
    ├── scripts/
    └── templates/
```

### 重载 Skills

```
POST /api/v1/skills/reload
```

## 使用方式

### 在 Agent 中使用

```python
from app.services.agent.skills import skill_loader

# 获取 ItemHandler 启用的 skills
handler = session.get(ItemHandler, handler_id)
for skill_id in handler.enabled_skills or []:
    skill = skill_loader.get(skill_id)
    if skill:
        # 使用 skill...
        print(f"Skill: {skill.name}")
        print(f"Trigger: {skill.trigger.type}")
```

### ItemHandler 关联

ItemHandler 通过 JSON 字段存储启用的 skill：

```python
class ItemHandler(ItemHandlerBase, table=True):
    enabled_skills: Optional[List[str]] = Field(default=None, sa_type=JSON)
    # 例如: ["npm_fixer", "git_helper"]
```

更新启用的 skills：

```
PUT /api/v1/item-handlers/{id}
{
  "enabled_skills": ["npm_fixer", "git_helper"]
}
```

## 核心组件

### SkillLoader

负责从文件系统加载 skill：

```python
from app.services.agent.skills import skill_loader

# 获取单个
skill = skill_loader.get("npm_fixer")

# 获取全部
skills = skill_loader.get_all()

# 重载
skill_loader.reload()
```

### SkillManager

负责 CRUD 操作：

```python
from app.services.agent.skills import skill_manager

# 创建
skill = skill_manager.create_skill(
    skill_id="my_skill",
    name="我的技能",
    description="描述",
)

# 更新
skill = skill_manager.update_skill(
    skill_id="my_skill",
    name="新名称",
)

# 删除
skill_manager.delete_skill("my_skill")

# 文件操作
skill_manager.create_skill_file("my_skill", "scripts/test.sh", "#!/bin/bash")
skill_manager.update_skill_file("my_skill", "scripts/test.sh", "new content")
skill_manager.delete_skill_file("my_skill", "scripts/test.sh")
```

## 设计原则

1. **纯文件系统** - 无数据库，直接操作文件夹
2. **简单直观** - 一个目录 = 一个 skill
3. **灵活扩展** - 支持脚本、模板、资源
4. **热重载** - 修改文件后自动生效
