import pathlib, ast
for f in pathlib.Path("backend/skills").rglob("*.yaml"):
    t = f.read_text(encoding="utf-8")
    if "system_prompt" in f.name or "skill_id: system_prompt" in t:
        print("FILE:", f)
        print("LEN:", len(t))
