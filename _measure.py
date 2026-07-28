import sys, json
sys.path.insert(0, "/app/backend")

# Measure system prompt
from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.agent import Agent

# We need an agent instance - let's check what's available
from app.services.agent.prompts.builder import _build_skill_prompt, _build_installed_software_context, _build_active_task_ledger_context, _build_current_source_route_context

# Check system prompt size
try:
    sp = get_system_prompt(None)
    print(f"System prompt (no agent): {len(sp)} chars")
except Exception as e:
    print(f"System prompt error: {e}")

# Check installed software
ITEM = "ea52de0c-51b7-4b49-a43d-985ed2e09579"
try:
    sw = _build_installed_software_context(ITEM)
    print(f"Installed software: {len(sw)} chars")
except Exception as e:
    print(f"Installed software error: {e}")

# Check active task ledger
try:
    tl = _build_active_task_ledger_context(ITEM, None)
    print(f"Active task ledger: {len(tl) if tl else 0} chars")
except Exception as e:
    print(f"Task ledger error: {e}")

# Check source route
try:
    sr = _build_current_source_route_context(None, source="chat")
    print(f"Source route: {len(sr) if sr else 0} chars")
except Exception as e:
    print(f"Source route error: {e}")

# Check skills
from app.services.agent.skills.loader import skill_loader
try:
    all_skills = skill_loader.list_skills()
    print(f"\nAll skills ({len(all_skills)}):")
    for s in all_skills:
        prompt_len = len(s.action.prompt) if s.action and s.action.prompt else 0
        print(f"  {s.skill_id}: category={s.category}, prompt={prompt_len} chars")
except Exception as e:
    print(f"Skills error: {e}")