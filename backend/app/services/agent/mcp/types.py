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
    
    def to_litellm_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": f"mcp_{self.server_name}_{self.name}",
                "description": self.description,
                "parameters": self.input_schema,
            }
        }
