import sys, json
sys.path.insert(0, "/app/backend")

# Measure skills
from pathlib import Path
skills_dir = Path("/app/backend/skills")
print("Skills directory:")
total_skill = 0
for skill_file in sorted(skills_dir.rglob("SKILL.md")):
    content = skill_file.read_text(encoding="utf-8")
    total_skill += len(content)
    print(f"  {skill_file.parent.name}: {len(content)} chars")
print(f"Total skills: {total_skill} chars")

sp = Path("/app/backend/skills/system/SYSTEM_PROMPT.md")
if sp.exists():
    print(f"\nSYSTEM_PROMPT.md: {len(sp.read_text(encoding='utf-8'))} chars")

# Measure MCP tools by instantiating the server
from app.services.agent.mcp.local_server import LocalMcpServer
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
try:
    server = LocalMcpServer(ITEM)
    tools = server.list_tools()
    total_chars = len(json.dumps(tools, ensure_ascii=False))
    print(f"\nMCP Tools: {len(tools)} tools, {total_chars} chars total")
    for t in tools:
        name = t.get("name", "?")
        desc = t.get("description", "")
        schema = json.dumps(t.get("inputSchema", {}), ensure_ascii=False)
        print(f"  {name}: desc={len(desc)}, schema={len(schema)}")
except Exception as e:
    print(f"MCP error: {e}")
    import traceback
    traceback.print_exc()