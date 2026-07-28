import sys, json
sys.path.insert(0, "/app/backend")

# Measure tools
from app.services.agent.mcp.local_server import build_local_tools
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
try:
    tools = build_local_tools(ITEM)
    total_chars = len(json.dumps(tools, ensure_ascii=False))
    print(f"Tools: {len(tools)} tools, {total_chars} chars total")
    for t in tools:
        name = t.get("function", {}).get("name", "?")
        desc = t.get("function", {}).get("description", "")
        params = json.dumps(t.get("function", {}).get("parameters", {}), ensure_ascii=False)
        print(f"  {name}: desc={len(desc)} chars, params={len(params)} chars")
except Exception as e:
    print(f"Tools error: {e}")
    import traceback
    traceback.print_exc()

# Measure skills
from pathlib import Path
skills_dir = Path("/app/backend/skills")
print(f"\nSkills directory:")
for skill_file in sorted(skills_dir.rglob("SKILL.md")):
    content = skill_file.read_text(encoding="utf-8")
    print(f"  {skill_file.parent.name}: {len(content)} chars")

# Also check SYSTEM_PROMPT.md
sp = Path("/app/backend/skills/system/SYSTEM_PROMPT.md")
if sp.exists():
    print(f"\nSYSTEM_PROMPT.md: {len(sp.read_text(encoding='utf-8'))} chars")