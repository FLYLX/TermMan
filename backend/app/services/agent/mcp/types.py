from dataclasses import dataclass, field


@dataclass
class MCPServer:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    description: str = ""


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict
    server_name: str
    skip_memory: bool = False

    def to_litellm_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": f"mcp_{self.server_name}_{self.name}",
                "description": _slim_text(self.description, 80),
                "parameters": _slim_schema(self.input_schema),
            }
        }


def _slim_text(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _slim_schema(schema: dict) -> dict:
    """裁掉参数描述的冗余文案，schema 结构/约束不变。"""
    if not isinstance(schema, dict):
        return schema
    import copy

    slimmed = copy.deepcopy(schema)
    properties = slimmed.get("properties")
    if isinstance(properties, dict):
        for prop in properties.values():
            if isinstance(prop, dict) and "description" in prop:
                prop["description"] = _slim_text(prop["description"], 60)
    if "description" in slimmed:
        slimmed["description"] = _slim_text(slimmed["description"], 80)
    return slimmed
