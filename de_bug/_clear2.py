import json

# Clear jq/curl from installed software
filepath = "/app/.runtime/installed_software/ea52de0c-51b7-4b49-a43d-985ed2e09579.json"
with open(filepath, "r", encoding="utf-8") as f:
    data = json.load(f)
items = data if isinstance(data, list) else []
before = len(items)
items = [x for x in items if not any(k in str(x.get("name","")).lower() for k in ["jq", "curl"])]
with open(filepath, "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False, indent=2)
print(f"Installed software: removed {before - len(items)} entries, {len(items)} remain")