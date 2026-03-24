---
skill_id: npm_fixer
name: NPM 错误修复
description: 自动检测并修复 npm 相关错误
category: fix
trigger:
  type: event
  patterns:
    - npm ERR!
    - ENOTFOUND
    - EACCES
    - network
action:
  type: llm
  prompt: |
    检测到 npm 错误，请分析错误并生成修复命令。
    
    错误信息：
    {error_content}
    
    请生成最合适的修复命令，优先考虑：
    1. 清除缓存
    2. 重新安装依赖
    3. 权限修复
safety:
  requires_approval: true
  risk_level: medium
  max_retries: 3
  timeout: 120
---

# NPM 错误修复 Skill

这个 skill 用于自动检测和修复常见的 npm 错误。

## 支持的错误类型

- **网络错误**: ENOTFOUND, ETIMEDOUT
- **权限错误**: EACCES, EPERM
- **依赖错误**: 版本冲突、包不存在
- **缓存错误**: 损坏的缓存

## 使用方法

当终端输出包含 npm 错误时，此 skill 会自动触发并尝试修复。

## 安全说明

- 所有修复命令都需要用户确认
- 高风险操作会提示用户
- 不会自动删除 node_modules
