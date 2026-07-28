filepath = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\mcp\local_server.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

changes = 0
replacements = [
    # write_scheduled_task schema - remaining verbose parts
    ('''                    "schedule_type": {
                        "type": "string",
                        "enum": ["once", "interval", "daily"],
                    },
                    "run_at": {
                        "type": "string",
                        "description": "ISO datetime for a once task.",
                    },
                    "interval_seconds": {''',
     '''                    "schedule_type": {"type": "string", "enum": ["once", "interval", "daily"]},
                    "run_at": {"type": "string", "description": "ISO datetime for once."},
                    "interval_seconds": {'''),

    # compress_memories schema
    ('''                    "memory_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2, "description": "要合并的记忆 ID 列表（完整 ID 或 list_memories 显示的前 8 位）"},
                    "content": {"type": "string", "description": "压缩合并后的精炼记忆内容"},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "error", "context"], "description": "记忆类型；不填则取来源记忆中最多的类型"},
                    "ttl_days": {"type": "integer", "description": "事实或上下文的过期天数；偏好和错误永久保存"}''',
     '''                    "memory_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2, "description": "IDs to merge."},
                    "content": {"type": "string", "description": "Merged content."},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "error", "context"]},
                    "ttl_days": {"type": "integer"}'''),

    # record_installed_software schema
    ('''                    "item_id": {"type": "string", "description": "Current terminal item id."},
                    "name": {"type": "string", "description": "Software package name, e.g. nginx, python3.12, temurin-21-jdk."},
                    "manager": {"type": "string", "enum": ["apt", "snap", "pip", "npm", "cargo", "manual", "other"], "description": "How it was installed."},
                    "version": {"type": "string", "description": "Installed version string if known."},
                    "notes": {"type": "string", "description": "Verification evidence or extra context."}''',
     '''                    "item_id": {"type": "string"},
                    "name": {"type": "string", "description": "Package name."},
                    "manager": {"type": "string", "enum": ["apt", "snap", "pip", "npm", "cargo", "manual", "other"]},
                    "version": {"type": "string"},
                    "notes": {"type": "string", "description": "Verification evidence."}'''),

    # remove_installed_software schema
    ('''                    "item_id": {"type": "string", "description": "Current terminal item id."},
                    "name": {"type": "string", "description": "Exact software name used when it was recorded."},
                    "reason": {"type": "string", "description": "Why it was removed."}''',
     '''                    "item_id": {"type": "string"},
                    "name": {"type": "string", "description": "Software name."},
                    "reason": {"type": "string"}'''),

    # save_memory schema
    ('''                    "content": {"type": "string", "description": "要保存的记忆内容"},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "error", "context"], "description": "记忆类型: fact(事实), preference(偏好), error(错误), context(上下文)"},
                    "ttl_days": {"type": "integer", "description": "事实或上下文的过期天数；偏好和错误永久保存"}''',
     '''                    "content": {"type": "string", "description": "Memory content."},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "error", "context"]},
                    "ttl_days": {"type": "integer", "description": "Expiry days (optional)."}'''),

    # recall_memory schema
    ('''                    "query": {"type": "string", "description": "搜索关键词或问题"},
                    "n_results": {"type": "integer", "description": "返回结果数量，0 或不填表示不限条数（按相关性阈值过滤）", "default": 0},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "error", "context"], "description": "可选：限定记忆类型"}''',
     '''                    "query": {"type": "string", "description": "Search query."},
                    "n_results": {"type": "integer", "default": 0},
                    "memory_type": {"type": "string", "enum": ["fact", "preference", "error", "context"]}'''),

    # list_memories schema
    ('''                    "memory_type": {"type": "string", "enum": ["fact", "preference", "error", "context"], "description": "可选：限定记忆类型"}
                },
                "required": []
            },
            handler=self._list_memories''',
     '''                    "memory_type": {"type": "string", "enum": ["fact", "preference", "error", "context"]}
                },
                "required": []
            },
            handler=self._list_memories'''),

    # delete_memory schema
    ('''                    "memory_id": {"type": "string", "description": "要删除的记忆 ID"}''',
     '''                    "memory_id": {"type": "string", "description": "Memory ID."}'''),

    # execute_command schema
    ('''                    "command": {"type": "string", "description": "要执行的一条 shell 命令；默认不要拼接 &&、||、;、管道或换行。"},
                    "timeout_seconds": {"type": "integer", "description": "可选。等待预期输出的秒数，默认 20，范围 1-600。", "default": 20},
                    "auto_interrupt_on_timeout": {"type": "boolean", "description": "可选，默认 false。只有用户明确要求超时停止进程时才设为 true。", "default": False}''',
     '''                    "command": {"type": "string", "description": "Shell command."},
                    "timeout_seconds": {"type": "integer", "default": 20},
                    "auto_interrupt_on_timeout": {"type": "boolean", "default": False}'''),

    # run_job schema
    ('''                    "command": {"type": "string", "description": "Non-interactive shell command to run as a one-shot job."},
                    "timeout_seconds": {"type": "integer", "description": "Maximum seconds before the job is terminated. Default 600, max 3600.", "default": 600},
                    "tail_lines": {"type": "integer", "description": "Number of final output lines returned to the agent. Default 80, max 300.", "default": 80}''',
     '''                    "command": {"type": "string", "description": "Shell command."},
                    "timeout_seconds": {"type": "integer", "default": 600},
                    "tail_lines": {"type": "integer", "default": 80}'''),
]

for old, new in replacements:
    if old in content:
        content = content.replace(old, new, 1)
        changes += 1
    else:
        print(f"NOT FOUND: {old[:60]}...")

with open(filepath, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
print(f"Total changes: {changes}")