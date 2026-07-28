import json, sys
filepath = "/app/.runtime/installed_software/ea52de0c-51b7-4b49-a43d-985ed2e09579.json"
with open(filepath, "r", encoding="utf-8") as f:
    data = json.load(f)

# Show current entries
items = data if isinstance(data, list) else data.get("items", data.get("software", []))
print(f"Total entries: {len(items)}")
for item in items:
    name = item.get("name", "?")
    print(f"  {name}")

# Remove java/openjdk/temurin entries
if isinstance(data, list):
    data = [x for x in data if not any(k in str(x.get("name","")).lower() for k in ["java", "jdk", "jre", "temurin", "openjdk"])]
elif isinstance(data, dict):
    for key in list(data.keys()):
        if isinstance(data[key], list):
            data[key] = [x for x in data[key] if not any(k in str(x.get("name","")).lower() for k in ["java", "jdk", "jre", "temurin", "openjdk"])]

with open(filepath, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("\nJava entries removed")