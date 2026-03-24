---
skill_id: git_helper
name: Git 辅助
description: 自动处理常见的 Git 操作和错误
category: vcs
trigger:
  type: event
  patterns:
    - git:
    - fatal:
    - CONFLICT
    - merge conflict
    - detached HEAD
action:
  type: llm
  prompt: |
    检测到 Git 问题，请分析并提供解决方案。
    
    输出内容：
    {error_content}
    
    请生成合适的 Git 命令来解决问题。
safety:
  requires_approval: true
  risk_level: medium
  max_retries: 2
  timeout: 60
---

# Git 辅助 Skill

自动处理常见的 Git 操作和错误。

## 支持的操作

- **冲突解决**: 自动检测合并冲突
- **分支管理**: 创建、切换、删除分支
- **远程同步**: fetch, pull, push 问题
- **撤销操作**: reset, revert 建议

## 注意事项

- 强制推送操作需要额外确认
- 删除分支前会检查是否合并
- 提供 undo 命令备份
