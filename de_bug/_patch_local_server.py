import io

path = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\mcp\local_server.py"
with io.open(path, "r", encoding="utf-8") as handle:
    text = handle.read()

old_reg = '''            handler=self._update_task_workflow,
            skip_memory=True,
        )
        self.register_tool(
            name="add_terminal_input_filter_rule",'''
new_reg = '''            handler=self._update_task_workflow,
            skip_memory=True,
        )
        self.register_tool(
            name="prepare_capabilities",
            description=(
                "Load on-demand capabilities listed in the capability catalog. "
                "Pass the exact tool names and/or guide ids you need; returns "
                "their full schemas/guidance and keeps them available for this "
                "item. Call this before using any catalog-listed tool."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id.",
                    },
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tool names and/or guide ids to load.",
                    },
                },
                "required": ["item_id", "names"],
            },
            handler=self._prepare_capabilities,
            skip_memory=True,
        )
        self.register_tool(
            name="add_terminal_input_filter_rule",'''
assert text.count(old_reg) == 1, "reg anchor=%d" % text.count(old_reg)
text = text.replace(old_reg, new_reg, 1)

old_handler_anchor = "    def _execute_command(self, args: dict) -> list:"
new_handler = '''    def _resolve_agent_for_item(self, item_id: str):
        try:
            import uuid as _uuid

            from sqlmodel import Session

            from app.core.db import engine
            from app.models import ItemHandler
            from app.services.agent.agent import agent_manager, item_handler_context

            handler_id = item_handler_context.get_handler(str(item_id))
            if not handler_id:
                return None
            with Session(engine) as session:
                handler = session.get(ItemHandler, _uuid.UUID(str(handler_id)))
            if handler is None:
                return None
            return agent_manager.get_or_create(handler)
        except Exception as exc:
            debug_log(f"[LocalMCPServer] _resolve_agent_for_item error: {exc}")
            return None

    def _prepare_capabilities(self, args: dict) -> list:
        import json as _json

        from app.services.agent.capability_state import ensure_loaded

        item_id = str(args.get("item_id") or "").strip()
        names = [str(name).strip() for name in (args.get("names") or []) if str(name).strip()]
        if not item_id or not names:
            return [{"type": "text", "text": "Error: item_id and names are required."}]

        agent = self._resolve_agent_for_item(item_id)
        if agent is None:
            return [{"type": "text", "text": "Error: no agent context available for this item."}]

        try:
            tool_index = {}
            for tool in agent.get_tools_for_litellm():
                function = tool.get("function") if isinstance(tool, dict) else None
                if isinstance(function, dict):
                    tool_name = str(function.get("name") or "").strip()
                    if tool_name:
                        tool_index[tool_name] = tool
        except Exception:
            tool_index = {}

        guide_index = {}
        try:
            for skill in agent.get_skills():
                category = str(getattr(skill, "category", "") or "")
                if category in {"system", "persona"}:
                    continue
                action = getattr(skill, "action", None)
                prompt = str(getattr(action, "prompt", "") or "").strip() if action else ""
                if prompt:
                    guide_index[str(getattr(skill, "skill_id", "") or "")] = prompt
        except Exception:
            guide_index = {}

        loaded_tools: list[str] = []
        loaded_guides: list[str] = []
        unknown: list[str] = []
        for name in names:
            if name in tool_index:
                loaded_tools.append(name)
            elif name in guide_index:
                loaded_guides.append(name)
            else:
                unknown.append(name)

        ensure_loaded(item_id, tools=loaded_tools, guides=loaded_guides)

        parts: list[str] = []
        for name in loaded_tools:
            parts.append(
                f"Tool `{name}` is now loaded. Schema:\\n{_json.dumps(tool_index[name], ensure_ascii=False)}"
            )
        for guide_id in loaded_guides:
            parts.append(f"Guide `{guide_id}` is now loaded:\\n{guide_index[guide_id]}")
        if unknown:
            parts.append(
                "Unknown names (not present in the capability catalog): "
                + ", ".join(unknown)
            )
        parts.append(
            "Loaded capabilities stay available for this item; call them normally now."
        )
        return [{"type": "text", "text": "\\n\\n".join(parts)}]

    def _execute_command(self, args: dict) -> list:'''
assert text.count(old_handler_anchor) == 1, "handler anchor=%d" % text.count(old_handler_anchor)
text = text.replace(old_handler_anchor, new_handler, 1)

with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(text)
print("local_server patched")