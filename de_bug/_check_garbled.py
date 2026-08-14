import json, sys
sys.path.insert(0, r"E:\dev\TermPaws\dev\TermPaws\backend")

# Re-measure after compression
filepath = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\mcp\local_server.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Count register_tool calls and extract descriptions
import re
tools = re.findall(r'name="([^"]+)",\s*description=(?:"([^"]*)"|\(\s*"([^"]*(?:"[^"]*)*?)"?\s*\))', content)
print(f"Found {len(tools)} tools via regex")

# Better: just count chars in the file between register_tool calls
# Actually let me just re-run the measurement in docker after syncing
print("File size:", len(content), "chars")

# Check for garbled text
garbled = re.findall(r'description="([^"]*[\u9354\u935b\u935c\u935d][^"]*)"', content)
if garbled:
    print(f"\nGarbled descriptions found: {len(garbled)}")
    for g in garbled[:3]:
        print(f"  {g[:80]}...")