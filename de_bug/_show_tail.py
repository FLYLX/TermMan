import pathlib
src = pathlib.Path("backend/app/services/agent/mcp/local_server.py").read_text(encoding="utf-8")
i = src.index("Always deliver immediately")
print(repr(src[i-700:i+300]))
