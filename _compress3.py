filepath = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\mcp\local_server.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

changes = 0
replacements = [
    # update_task_workflow schema - shorten descriptions
    ('''                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id.",
                    },
                    "action": {
                        "type": "string",
                        "enum": [
                            "create",
                            "record_progress",
                            "complete_current_step",
                            "set_current_step",
                            "insert_recovery_step",
                            "mark_ready_to_report",
                            "mark_blocked",
                            "resume",
                            "cancel",
                        ],
                    },
                    "force_new": {
                        "type": "boolean",
                        "description": "Create new workflow even if existing ones present.",
                    },
                    "note": {
                        "type": "string",
                        "description": "Observed evidence, progress, or blocker reason.",
                    },
                    "step_index": {
                        "type": "integer",
                        "description": "Zero-based step index for set_current_step.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Recovery step title for insert_recovery_step.",
                    },''',
     '''                    "item_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["create", "record_progress", "complete_current_step", "set_current_step", "insert_recovery_step", "mark_ready_to_report", "mark_blocked", "resume", "cancel"]},
                    "force_new": {"type": "boolean"},
                    "note": {"type": "string", "description": "Evidence or reason."},
                    "step_index": {"type": "integer"},
                    "title": {"type": "string", "description": "Step title for create/recovery."},'''),

    # add_terminal_input_filter_rule schema
    ('''                    "item_id": {"type": "string", "description": "Current terminal item id."},
                    "name": {"type": "string", "description": "Short rule name, for example noise_ftb_backups."},
                    "regex_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Case-insensitive regex patterns to match noisy terminal output.",
                    },
                    "action_type": {
                        "type": "string",
                        "enum": ["block", "ignore", "log"],
                        "description": "block drops the whole matching chunk; ignore removes matching text; log marks it as needs-action. Default block.",
                        "default": "block",
                    },
                    "reason": {"type": "string", "description": "Optional human-readable reason for this rule."},''',
     '''                    "item_id": {"type": "string"},
                    "name": {"type": "string", "description": "Rule name."},
                    "regex_patterns": {"type": "array", "items": {"type": "string"}, "description": "Regex patterns to filter."},
                    "action_type": {"type": "string", "enum": ["block", "ignore", "log"], "default": "block"},
                    "reason": {"type": "string"},'''),

    # list_terminal_input_filter_rules description
    ('description="List terminal output -> Agent input filter rules for the current item. Use before adding a new noise rule when unsure whether one already exists."',
     'description="List terminal input filter rules."'),

    # delete_terminal_input_filter_rule
    ('description="Delete one terminal output -> Agent input filter rule for the current item by rule name."',
     'description="Delete a terminal input filter rule by name."'),

    # delete_terminal_input_filter_rule schema
    ('''                    "item_id": {"type": "string", "description": "Current terminal item id."},
                    "name": {"type": "string", "description": "Rule name returned by list_terminal_input_filter_rules."},
                    "disable_when_empty": {
                        "type": "boolean",
                        "description": "Disable input_filter_enabled when no rules remain. Default true.",
                        "default": True,
                    },''',
     '''                    "item_id": {"type": "string"},
                    "name": {"type": "string", "description": "Rule name."},
                    "disable_when_empty": {"type": "boolean", "default": True},'''),

    # clear_terminal_input_filter_rules
    ('description="Delete all terminal output -> Agent input filter rules for the current item."',
     'description="Delete all terminal input filter rules."'),

    # clear_terminal_input_filter_rules schema
    ('''                    "item_id": {"type": "string", "description": "Current terminal item id."},
                    "disable": {
                        "type": "boolean",
                        "description": "Disable input_filter_enabled after clearing. Default true.",
                        "default": True,
                    },''',
     '''                    "item_id": {"type": "string"},
                    "disable": {"type": "boolean", "default": True},'''),
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